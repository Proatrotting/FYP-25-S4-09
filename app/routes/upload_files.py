from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
import logging
import uuid
import base64
import hashlib
import requests
import os
import json
import traceback

# Import Reed-Solomon erasure coding
from app.core.erasure_coding import get_erasure_coder_for_account, get_erasure_coder_for_profile

# Import AES-256 encryption
from app.core.file_encryption import encrypt_file_data, get_file_encryption
from app.core.key_storage import get_key_storage_manager
from app.core.shamir_secret_sharing import create_key_shares, get_sss_config

# Remove SQLAlchemy dependencies since we're using master node API
from app.core.security import decode_access_token
from app.routes.login import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

# Master node configuration
MASTER_NODE_URL = os.getenv("MASTER_NODE_URL", "http://master-node:3000")


class FileUploadRequest(BaseModel):
    filename: str
    data: str  # base64 encoded file data
    content_type: Optional[str] = "application/octet-stream"
    folder_id: Optional[str] = None
    erasure_id: Optional[str] = "MEDIUM"


class FileUploadResponse(BaseModel):
    file_id: str
    version_id: str
    filename: str
    file_size: int  # Original file size
    content_type: str
    upload_status: str
    fragments_stored: int
    erasure_profile: str
    encrypted_size: int  # Size after encryption
    is_encrypted: bool

class FileUploadWithSessionResponse(BaseModel):
    session_id: str
    file_id: str
    version_id: str
    filename: str
    file_size: int  # Original file size
    content_type: str
    upload_status: str
    fragments_stored: int
    erasure_profile: str
    encrypted_size: int  # Size after encryption
    is_encrypted: bool


class FileInfo(BaseModel):
    file_id: str
    file_name: str
    file_size: int
    logical_path: str
    uploaded_at: str
    folder_id: Optional[str] = None
    erasure_id: Optional[str] = None


class FilesListResponse(BaseModel):
    files: List[FileInfo]
    total: int


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

async def process_file_upload(
    filename: str,
    file_data_base64: str,
    content_type: str,
    folder_id: Optional[str],
    erasure_id: str,
    account_id: str
) -> dict:
    """
    Core file upload logic that can be called directly without HTTP overhead.
    Returns a dict with upload results.
    """
    # Decode the base64 file data
    file_data = base64.b64decode(file_data_base64)
    original_file_size = len(file_data)
    
    # Generate file hash (before encryption for integrity verification)
    original_file_hash = hashlib.sha256(file_data).hexdigest()
    
    # Generate unique encryption key for this file
    encryption_handler = get_file_encryption()
    file_encryption_key = encryption_handler.generate_file_key()
    
    # Encrypt file data using AES-256-GCM with per-file key
    try:
        encrypted_file_data, encryption_metadata, returned_key = encrypt_file_data(
            data=file_data,
            account_id=account_id,
            additional_data={
                "filename": filename,
                "content_type": content_type,
                "original_hash": original_file_hash
            },
            file_key=file_encryption_key
        )
        encrypted_file_size = len(encrypted_file_data)
        logger.info(f"File encrypted successfully: {filename} ({original_file_size} -> {encrypted_file_size} bytes)")
    except Exception as e:
        logger.error(f"File encryption failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File encryption failed: {str(e)}"
        )
    
    # Use encrypted data for storage
    file_data = encrypted_file_data
    file_size = encrypted_file_size
    
    # Split encryption key using Shamir's Secret Sharing
    try:
        logger.info(f"Splitting encryption key using Shamir's Secret Sharing for file {filename}")
        key_shares = create_key_shares(file_encryption_key)
        threshold, num_shares = get_sss_config()
        logger.info(f"Created {len(key_shares)} key shares with {threshold}-of-{num_shares} threshold")
    except Exception as e:
        logger.error(f"Failed to split encryption key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to split encryption key: {str(e)}"
        )
    
    # Will store key_id and shares after file metadata is created
    key_shares_for_storage = key_shares

    # Create file metadata in master node
    logical_path = f"/{filename}"
    if folder_id:
        logical_path = f"/folders/{folder_id}/{filename}"
    
    create_file_payload = {
        "account_id": account_id,
        "file_name": filename,
        "file_size": encrypted_file_size,  # Store encrypted size
        "logical_path": logical_path,
        "folder_id": folder_id,
        "erasure_id": erasure_id,
        # Add encryption metadata
        "encryption_metadata": encryption_metadata,
        "original_file_size": original_file_size,
        "original_file_hash": original_file_hash,
        "is_encrypted": True
    }
    
    # Create file metadata
    response = requests.post(f"{MASTER_NODE_URL}/files", json=create_file_payload)
    if response.status_code not in [200, 201]:
        logger.error(f"Failed to create file metadata: Status {response.status_code}, Response: {response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create file metadata: {response.text}"
        )
    
    file_metadata = response.json()
    file_id = file_metadata["fileId"]
    version_id = file_metadata["versionId"]
    
    logger.info(f"File metadata created with ID: {file_id}")
    
    # Store encryption key shares using Shamir's Secret Sharing
    try:
        # Store key shares in database via master node
        key_shares_payload = {
            "version_id": version_id,
            "encryption_key": encryption_handler.key_to_string(file_encryption_key),
            "key_shares": [
                {
                    "share_index": share_idx,
                    "share_data": base64.b64encode(share_data).decode('utf-8')
                }
                for share_idx, share_data in key_shares_for_storage
            ]
        }
        
        response = requests.post(f"{MASTER_NODE_URL}/key-shares", json=key_shares_payload)
        if response.status_code not in [200, 201]:
            logger.error(f"Failed to store key shares: Status {response.status_code}, Response: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to store key shares: {response.text}"
            )
        
        logger.info(f"Stored {len(key_shares_for_storage)} key shares for file {file_id}")
        
    except Exception as e:
        logger.error(f"Failed to store key shares: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store key shares: {str(e)}"
        )
    
    # Get erasure profile and initialize Reed-Solomon encoder
    erasure_coder = get_erasure_coder_for_profile(erasure_id)
    profile_info = erasure_coder.get_fragment_info()
    k_fragments = profile_info["k"]
    m_fragments = profile_info["m"]
    total_fragments = profile_info["n"]
    logger.info(f"Using Reed-Solomon profile {erasure_id}: {k_fragments}+{m_fragments}={total_fragments} fragments")
    
    # Encode file data using Reed-Solomon
    try:
        fragments = erasure_coder.encode_data(file_data)
        logger.info(f"Reed-Solomon encoding produced {len(fragments)} fragments from {len(file_data)} bytes")
    except Exception as e:
        logger.error(f"Reed-Solomon encoding failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erasure coding failed: {str(e)}"
        )
    
    # Prepare fragment data for distribution
    fragment_data_list = []
    for i, fragment_data in enumerate(fragments):
        fragment_info = {
            "num_fragment": i,
            "bytes": len(fragment_data),
            "content_hash": hashlib.sha256(fragment_data).hexdigest(),
            "data": base64.b64encode(fragment_data).decode()
        }
        fragment_data_list.append(fragment_info)
    
    # Get distribution plan from master node
    fragment_payload = {
        "version_id": version_id,
        "segment_id": str(uuid.uuid4()),
        "fragment_data": fragment_data_list,
        "erasure_id": erasure_id
    }
    
    distribute_response = requests.post(f"{MASTER_NODE_URL}/file-fragments", json=fragment_payload)
    if distribute_response.status_code not in [200, 201]:
        logger.error(f"Failed to get distribution plan: Status {distribute_response.status_code}, Response: {distribute_response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fragment distribution plan: {distribute_response.text}"
        )
    
    distribution_result = distribute_response.json()
    
    if not distribution_result.get("success", False):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Master node failed to create distribution plan"
        )
    
    distributed_fragments = distribution_result.get("fragments", [])
    
    # Store fragments on storage nodes
    fragments_stored = 0
    for i, fragment_plan in enumerate(distributed_fragments):
        try:
            fragment_info = fragment_data_list[i]
            node_endpoint = fragment_plan["nodeEndpoint"]
            storage_url = node_endpoint
            fragment_id = fragment_plan["fragmentId"]
            
            fragment_payload = {
                "fragmentId": fragment_id,
                "data": fragment_info["data"],
                "contentHash": fragment_info["content_hash"],
                "bytes": fragment_info["bytes"],
                "fileId": file_id,
                "fragmentOrder": fragment_info["num_fragment"]
            }
            
            logger.info(f"Storing fragment {fragment_id} on {storage_url}")
            store_response = requests.post(f"{storage_url}/fragments", json=fragment_payload, timeout=30)
            
            if store_response.status_code in [200, 201]:
                fragments_stored += 1
                logger.info(f"✅ Fragment {fragment_id} stored successfully")
            else:
                logger.error(f"❌ Failed to store fragment {fragment_id}: {store_response.text}")
                
        except Exception as e:
            logger.error(f"❌ Exception storing fragment {i}: {e}")
            continue
    
    total_fragments_expected = len(fragment_data_list)
    upload_status = "complete" if fragments_stored == total_fragments_expected else "partial"
    if fragments_stored == 0:
        upload_status = "failed"
    
    logger.info(f"File upload completed: {filename}, fragments: {fragments_stored}/{total_fragments_expected}")
    
    return {
        "file_id": file_id,
        "version_id": version_id,
        "filename": filename,
        "file_size": original_file_size,  # Return original file size to user
        "content_type": content_type,
        "upload_status": upload_status,
        "fragments_stored": fragments_stored,
        "erasure_profile": erasure_id,
        "encrypted_size": encrypted_file_size,
        "is_encrypted": True
    }


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    # Multipart form fields (for XMLHttpRequest)
    file: Optional[UploadFile] = File(None),
    filename: Optional[str] = Form(None),
    folder_id: Optional[str] = Form(None),
    erasure_id: Optional[str] = Form("MEDIUM"),
    # JSON body fallback (for base64 uploads)
    upload_data: Optional[FileUploadRequest] = None,
    current_account = Depends(get_current_account)
):
    """
    Upload a file to the distributed storage system using the new master node schema.
    
    Supports TWO input methods:
    1. Multipart/form-data (XMLHttpRequest with FormData) - PREFERRED for progress tracking
    2. JSON with base64 data (legacy/backward compatibility)
    
    Files are processed with erasure coding and distributed across storage nodes.
    """
    try:
        # Detect input method
        content_type_header = request.headers.get("content-type", "")
        
        if "multipart/form-data" in content_type_header:
            # Method 1: Multipart upload (XMLHttpRequest)
            if not file:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No file provided in multipart request"
                )
            
            # Read raw file bytes
            file_contents = await file.read()
            file_data_base64 = base64.b64encode(file_contents).decode('utf-8')
            
            # Use form fields
            actual_filename = filename or file.filename or "unnamed_file"
            actual_content_type = file.content_type or "application/octet-stream"
            actual_folder_id = folder_id if folder_id and folder_id != '' else None
            actual_erasure_id = erasure_id or "MEDIUM"
            
            logger.info(f"Multipart upload: {actual_filename} ({len(file_contents)} bytes)")
            
        else:
            # Method 2: JSON with base64 (backward compatibility)
            if not upload_data:
                # Try to parse JSON body manually
                try:
                    body = await request.json()
                    upload_data = FileUploadRequest(**body)
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid request: expected multipart/form-data or JSON body"
                    )
            
            file_data_base64 = upload_data.data
            actual_filename = upload_data.filename
            actual_content_type = upload_data.content_type
            actual_folder_id = upload_data.folder_id
            actual_erasure_id = upload_data.erasure_id
            
            logger.info(f"Base64 JSON upload: {actual_filename}")
        
        # Process upload using unified logic
        result = await process_file_upload(
            filename=actual_filename,
            file_data_base64=file_data_base64,
            content_type=actual_content_type,
            folder_id=actual_folder_id,
            erasure_id=actual_erasure_id,
            account_id=current_account["account_id"]
        )
        return FileUploadResponse(**result)


    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading file: {str(e)}",
        )


@router.post("/upload-with-session", response_model=FileUploadWithSessionResponse, status_code=status.HTTP_201_CREATED)
def upload_file_with_session(
    upload_data: FileUploadRequest,
    request: Request,
    current_account = Depends(get_current_account)
):
    """
    Upload a file with session tracking for cancellation support.
    Returns session_id that can be used to cancel the upload.
    """
    from app.core.upload_with_session import process_file_upload_with_session
    
    try:
        result = process_file_upload_with_session(
            filename=upload_data.filename,
            file_data_base64=upload_data.data,
            content_type=upload_data.content_type,
            folder_id=upload_data.folder_id,
            erasure_id=upload_data.erasure_id,
            account_id=current_account["account_id"]
        )
        return FileUploadWithSessionResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file with session: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading file: {str(e)}",
        )


@router.get("/list", response_model=FilesListResponse)
def list_files(
    current_account = Depends(get_current_account)
):
    """
    List all files for the current authenticated user.
    """
    try:
        # Query master node for user's files with folder information
        # Exclude files that are currently in the recycle bin (not recovered)
        response = requests.post(f"{MASTER_NODE_URL}/query", json={
            "sql": """
                SELECT f.file_id, f.file_name, f.file_size, f.logical_path, f.uploaded_at, 
                       f.folder_id, fv.erasure_id
                FROM file_objects f
                LEFT JOIN file_versions fv ON f.file_id = fv.file_id
                LEFT JOIN recycle_bin rb ON (f.file_id = rb.resource_id AND rb.resource_type = 'FILE' AND rb.is_recovered = 'FALSE')
                WHERE f.account_id = $1
                AND rb.resource_id IS NULL
                ORDER BY f.uploaded_at DESC
            """,
            "params": [current_account["account_id"]]
        })
        
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Master node error")
        
        result = response.json()
        if not result.get("success"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to query files")
        
        files_data = result.get("data", [])
        
        # Convert to FileInfo objects
        files = []
        for file_data in files_data:
            file_info = FileInfo(
                file_id=file_data["file_id"],
                file_name=file_data["file_name"],
                file_size=file_data["file_size"],
                logical_path=file_data["logical_path"],
                uploaded_at=file_data["uploaded_at"],
                folder_id=file_data.get("folder_id"),
                erasure_id=file_data.get("erasure_id", "MEDIUM")
            )
            files.append(file_info)
        
        return FilesListResponse(
            files=files,
            total=len(files)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing files: {str(e)}"
        )