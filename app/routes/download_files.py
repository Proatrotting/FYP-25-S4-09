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
    account_id: str
) -> bytes:
    """
    Core file download logic that can be called directly without HTTP overhead.
    Returns reconstructed file data as bytes.
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
    
    # Check if user owns this file
    if file_info["account_id"] != account_id:
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
    logger.info(f"Retrieved {len(available_fragments)} fragments out of {len(sorted_fragments)} total fragments")
    
    if not erasure_coder.can_reconstruct(len(available_fragments)):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Not enough fragments for reconstruction. Need {erasure_coder.k}, got {len(available_fragments)}"
        )
    
    # Reconstruct original file using Reed-Solomon decoding
    try:
        reconstructed_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
        
        # Truncate to original file size
        original_file_size = int(file_info["file_size"])
        if len(reconstructed_data) > original_file_size:
            reconstructed_data = reconstructed_data[:original_file_size]
            logger.info(f"Truncated reconstructed data to original size: {original_file_size} bytes")
        
        logger.info(f"Successfully reconstructed {len(reconstructed_data)} bytes using {len(available_fragments)} fragments")
        return reconstructed_data
    except Exception as e:
        logger.error(f"Reed-Solomon reconstruction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File reconstruction failed: {str(e)}"
        )


@router.get("/download/{file_id}")
async def download_file(file_id: str, current_account = Depends(get_current_account)):
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