import base64
import requests
import httpx
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.security import decode_access_token
from app.routes.login import oauth2_scheme
from app.core.config import get_settings
from app.core.erasure_coding import get_erasure_coder_for_profile, get_erasure_coder_for_account
from app.core.lazy_repair import LazyRepair
# Import AES-256 decryption
from app.core.file_encryption import decrypt_file_data
from app.core.key_storage import get_key_storage_manager
from app.core.shamir_secret_sharing import reconstruct_key_from_shares, get_sss_config
import logging

router = APIRouter(prefix="/files", tags=["files"])
logger = logging.getLogger(__name__)
settings = get_settings()
MASTER_NODE_URL = settings.master_node_url

class FileInfo(BaseModel):
    file_id: str
    file_name: str
    file_size: int
    logical_path: str
    uploaded_at: str
    erasure_id: str
    content_hash: str

class FileListResponse(BaseModel):
    files: List[FileInfo]

def get_current_account_from_master(token: str):
    """Get account info from master node API."""
    try:
        # Decode token to get account_id and username
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
        account_id = payload.get("sub")  # account_id is stored in sub
        username = payload.get("username")  # username is in username field
        
        if not account_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        
        # Query master node for account info using account_id
        response = requests.post(f"{MASTER_NODE_URL}/query", json={
            "sql": "SELECT account_id, username, email, account_type, created_at FROM ACCOUNT WHERE account_id = $1",
            "params": [account_id]
        })
        
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Master node error")
        
        result = response.json()
        if not result.get("success") or not result.get("data") or len(result.get("data")) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        
        return result["data"][0]  # Return first account record
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to master node: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Master node unavailable")

def get_current_account(token=Depends(oauth2_scheme)):
    """Get the current authenticated account from master node."""
    token_str = token.credentials if hasattr(token, "credentials") else token
    return get_current_account_from_master(token_str)

@router.get("/list", response_model=FileListResponse)
async def list_files(current_account = Depends(get_current_account)):
    """List all files for the authenticated user."""
    try:
        account_id = current_account["account_id"]
        
        # Get files from master node
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{MASTER_NODE_URL}/files/{account_id}")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve files: {response.text}"
            )
        
        result = response.json()
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve files from master node"
            )
        
        return {"files": result["files"]}
    
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Master node unavailable: {str(e)}"
        )

async def process_file_download(
    file_id: str,
    account_id: str,
    skip_ownership_check: bool = False
) -> bytes:
    """
    Core file download logic that can be called directly without HTTP overhead.
    Returns reconstructed file data as bytes.
    
    Args:
        file_id: ID of the file to download
        account_id: Account ID for decryption keys
        skip_ownership_check: If True, skips ownership verification (for shared files)
    """
    # Get file info to verify ownership
    async with httpx.AsyncClient() as client:
        file_info_response = await client.get(f"{MASTER_NODE_URL}/files/info/{file_id}")
    
    if file_info_response.status_code == 404:
        raise HTTPException(status_code=404, detail="File not found")
    
    if file_info_response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve file info: {file_info_response.text}"
        )
    
    file_info = file_info_response.json()["file"]
    
    # Check if user owns this file (unless ownership check is skipped for shared files)
    if not skip_ownership_check and file_info["account_id"] != account_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get fragment information
    async with httpx.AsyncClient() as client:
        fragments_response = await client.get(f"{MASTER_NODE_URL}/fragments/{file_id}")
    
    if fragments_response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve fragments: {fragments_response.text}"
        )
    
    fragments = fragments_response.json()
    
    if not fragments:
        raise HTTPException(status_code=404, detail="File fragments not found")
    
    # Initialize erasure decoder
    try:
        erasure_coder = get_erasure_coder_for_profile(file_info["erasure_id"])
        logger.info(f"Using file's original Reed-Solomon profile {file_info['erasure_id']} for download")
    except Exception as e:
        logger.error(f"Failed to initialize erasure decoder: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize erasure decoder: {str(e)}"
        )
    
    # Download available fragments from storage nodes
    available_fragments = []
    fragment_indexes = []
    sorted_fragments = sorted(fragments, key=lambda x: x["num_fragment"])
    
    logger.info(f"Attempting to download {len(sorted_fragments)} fragments for file {file_id}")
    
    async with httpx.AsyncClient() as client:
        for fragment in sorted_fragments:
            if not fragment.get("fragment_id") or not fragment.get("api_endpoint"):
                logger.warning(f"Fragment missing required fields: {fragment}")
                continue
                
            node_endpoint = fragment["api_endpoint"]
            storage_url = node_endpoint
            fragment_url = f"{storage_url}/fragments/{fragment['fragment_id']}"
            
            logger.info(f"Requesting fragment {fragment['num_fragment']} from {fragment_url}")
            
            try:
                frag_response = await client.get(fragment_url, timeout=30)
                if frag_response.status_code == 200:
                    fragment_data = frag_response.json()
                    if fragment_data.get("success") and fragment_data.get("data"):
                        decoded_data = base64.b64decode(fragment_data["data"])
                        available_fragments.append(decoded_data)
                        fragment_indexes.append(fragment["num_fragment"])
                        logger.info(f"Successfully retrieved fragment {fragment['num_fragment']} ({len(decoded_data)} bytes)")
                    else:
                        logger.warning(f"Storage node returned empty data for fragment {fragment['fragment_id']}")
                else:
                    logger.warning(f"Storage node failed to retrieve fragment {fragment['fragment_id']}: {frag_response.status_code}")
            except httpx.RequestError as e:
                logger.warning(f"Failed to fetch fragment {fragment['fragment_id']} from {fragment_url}: {e}")
                continue
    
    # Check if we have enough fragments
    logger.info(f"Retrieved {len(available_fragments)} of {len(sorted_fragments)} fragments")
    
    # Lazy repair: create repair job if fragments are missing but reconstruction is possible
    if len(available_fragments) < len(sorted_fragments) and erasure_coder.can_reconstruct(len(available_fragments)):
        logger.warning(f"Triggering lazy repair: {len(available_fragments)}/{len(sorted_fragments)} fragments available")
        try:
            lazy_repair = LazyRepair()
            version_id = file_info.get("version_id") or file_id
            await lazy_repair.check_and_create_repair_job(
                version_id=version_id,
                total_fragments_expected=len(sorted_fragments),
                fragments_available=len(available_fragments)
            )
        except Exception as repair_error:
            logger.error(f"Lazy repair failed: {repair_error}")
            # Don't fail the download if repair job creation fails
    
    # Verify we can reconstruct the file
    if not erasure_coder.can_reconstruct(len(available_fragments)):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Not enough fragments for reconstruction. Need {erasure_coder.k}, got {len(available_fragments)}"
        )
    
    # Reconstruct original file using Reed-Solomon decoding
    try:
        reconstructed_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
        
        # Truncate to the stored file size (encrypted size)
        stored_file_size = int(file_info["file_size"])
        if len(reconstructed_data) > stored_file_size:
            reconstructed_data = reconstructed_data[:stored_file_size]
        
        logger.info(f"File reconstructed successfully: {len(reconstructed_data)} bytes")
        
        # Check if file is encrypted and decrypt if necessary
        is_encrypted = file_info.get("is_encrypted", False)
        if is_encrypted:
            encryption_metadata = file_info.get("encryption_metadata")
            version_id = file_info.get("version_id")
            
            # Retrieve encryption key shares using Shamir's Secret Sharing
            if not version_id:
                logger.error("No version_id available for key retrieval")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="File version information not available"
                )
            
            try:
                # Query master node for key shares
                response = requests.get(f"{MASTER_NODE_URL}/key-shares/{version_id}")
                if response.status_code != 200:
                    logger.error(f"Failed to retrieve key shares: Status {response.status_code}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to retrieve key shares: {response.text}"
                    )
                
                key_shares_data = response.json()
                key_shares = key_shares_data.get("shares", [])
                
                if not key_shares:
                    logger.error("No key shares found for file")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="No key shares found for file"
                    )
                
                logger.info(f"Retrieved {len(key_shares)} key shares from master node")
                
                # Retrieve share data from storage nodes
                threshold, num_shares = get_sss_config()
                retrieved_shares = []
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for share_info in key_shares:
                        node_id = share_info["node_id"]
                        share_address = share_info["share_address"]
                        fragment_id = share_info.get("fragment_id")  # The UUID used to store the fragment
                        share_index = share_info["key_share_id"]
                        
                        # Get node endpoint
                        node_response = requests.get(f"{MASTER_NODE_URL}/nodes/{node_id}")
                        if node_response.status_code != 200:
                            logger.warning(f"Failed to get node info for {node_id}")
                            continue
                        
                        node_info = node_response.json()
                        node_endpoint = node_info.get("api_endpoint")
                        
                        if not node_endpoint or not fragment_id:
                            logger.warning(f"No endpoint or fragment_id for node {node_id}")
                            continue
                        
                        try:
                            # Retrieve share from storage node using fragment_id
                            share_url = f"{node_endpoint}/fragments/{fragment_id}"
                            share_response = await client.get(share_url)
                            
                            if share_response.status_code == 200:
                                share_data_b64 = share_response.json().get("data")
                                share_data = base64.b64decode(share_data_b64)
                                retrieved_shares.append((share_index, share_data))
                                logger.info(f"Retrieved key share {share_index} from {node_id}")
                            else:
                                logger.warning(f"Failed to retrieve share from {node_id}: {share_response.status_code}")
                        
                        except Exception as e:
                            logger.warning(f"Failed to fetch share from {node_id}: {e}")
                            continue
                
                # Check if we have enough shares to reconstruct
                if len(retrieved_shares) < threshold:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Not enough key shares to reconstruct. Need {threshold}, got {len(retrieved_shares)}"
                    )
                
                logger.info(f"Reconstructing encryption key from {len(retrieved_shares)} shares (threshold: {threshold})")
                
                # Reconstruct the encryption key
                file_encryption_key = reconstruct_key_from_shares(retrieved_shares, key_length=32)
                logger.info("Encryption key successfully reconstructed from shares")
                
            except HTTPException:
                raise
            except Exception as key_error:
                logger.error(f"Failed to retrieve and reconstruct encryption key: {key_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to retrieve encryption key: {str(key_error)}"
                )
            
            # Decrypt using the reconstructed key
            try:
                logger.info(f"Decrypting file for account {account_id}")
                decrypted_data = decrypt_file_data(
                    encrypted_data=reconstructed_data,
                    account_id=account_id,
                    encryption_metadata=encryption_metadata,
                    file_info=file_info,
                    file_key=file_encryption_key
                )
                
                # Verify decrypted file size matches expected original size
                expected_original_size = file_info.get("original_file_size")
                if expected_original_size and len(decrypted_data) != int(expected_original_size):
                    logger.error(
                        f"Decrypted file size mismatch: got {len(decrypted_data)}, "
                        f"expected {expected_original_size}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="File decryption resulted in unexpected file size"
                    )
                
                logger.info(f"File decrypted successfully")
                return decrypted_data
                
            except Exception as decrypt_error:
                logger.error(f"SSS decryption failed: {decrypt_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"File decryption failed: {str(decrypt_error)}"
                )
        else:
            # File is not encrypted, return as-is
            logger.info("File is not encrypted, returning reconstructed data")
            return reconstructed_data
            
    except Exception as e:
        logger.error(f"Reed-Solomon reconstruction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File reconstruction failed: {str(e)}"
        )


@router.get("/download/{file_id}")
async def download_file(
    file_id: str, 
    current_account = Depends(get_current_account)
):
    """Download a file by ID."""
    try:
        account_id = current_account["account_id"]
        reconstructed_data = await process_file_download(file_id, account_id)
        
        # Get file info for filename
        async with httpx.AsyncClient() as client:
            file_info_response = await client.get(f"{MASTER_NODE_URL}/files/info/{file_id}")
        file_info = file_info_response.json()["file"]
        
        # Return file with proper headers
        return Response(
            content=reconstructed_data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={file_info['file_name']}",
                "Content-Length": str(len(reconstructed_data))
            }
        )
    
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Master node unavailable: {str(e)}"
        )

@router.get("/download-with-session/{file_id}")
async def download_file_with_session(
    file_id: str,
    session_id: str = None,
    current_account = Depends(get_current_account)
):
    """Download a file with session tracking for cancellation support."""
    from app.core.download_with_session import process_file_download_with_session
    
    try:
        account_id = current_account["account_id"]
        reconstructed_data, download_session_id = await process_file_download_with_session(
            file_id, account_id, session_id
        )
        
        # Get file info for filename
        async with httpx.AsyncClient() as client:
            file_info_response = await client.get(f"{MASTER_NODE_URL}/files/info/{file_id}")
        file_info = file_info_response.json()["file"]
        
        # Return file with proper headers and session info
        return Response(
            content=reconstructed_data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={file_info['file_name']}",
                "Content-Length": str(len(reconstructed_data)),
                "X-Session-ID": download_session_id
            }
        )
    
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Master node unavailable: {str(e)}"
        )

@router.get("/info/{file_id}", response_model=FileInfo)
async def get_file_info(file_id: str, current_account = Depends(get_current_account)):
    """Get file information by ID."""
    try:
        # Get file info from master node
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{MASTER_NODE_URL}/files/info/{file_id}")
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="File not found")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file info: {response.text}"
            )
        
        file_info = response.json()["file"]
        
        # Check if user owns this file
        if file_info["account_id"] != current_account["account_id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return file_info
    
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Master node unavailable: {str(e)}"
        )