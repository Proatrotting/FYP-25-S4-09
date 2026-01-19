from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Dict
import logging
import requests
import os
import traceback
import uuid
import base64
import json

from app.core.security import decode_access_token
from app.routes.login import oauth2_scheme
from app.master_node_db import MasterNodeDB, get_master_db
from app.routes.upload_files import process_file_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

# Internal URLs for calling our own FastAPI endpoints
FASTAPI_INTERNAL_URL = os.getenv("FASTAPI_INTERNAL_URL", "http://localhost:8000")


# ===== DATA MODELS =====

class FileInFolder(BaseModel):
    """Represents a file within a folder structure."""
    filename: str
    data: str  # base64 encoded file data
    relative_path: str  # e.g., "subfolder1/subfolder2/file.txt"
    content_type: Optional[str] = "application/octet-stream"


class FolderUploadRequest(BaseModel):
    """Request model for uploading an entire folder."""
    folder_name: str
    files: List[FileInFolder]
    parent_folder_id: Optional[str] = None
    erasure_id: Optional[str] = "MEDIUM"


class FileUploadResult(BaseModel):
    """Result of uploading a single file."""
    filename: str
    relative_path: str
    success: bool
    file_id: Optional[str] = None
    version_id: Optional[str] = None
    file_size: Optional[int] = None
    fragments_stored: Optional[int] = None
    error: Optional[str] = None


class FolderUploadResponse(BaseModel):
    """Response model for folder upload operation."""
    success: bool
    root_folder_id: str
    folder_name: str
    total_files: int
    files_uploaded: int
    files_failed: int
    upload_results: List[FileUploadResult]
    folder_structure: Dict[str, str]  # path -> folder_id mapping
    errors: List[str]


# ===== HELPER FUNCTIONS =====

def get_current_account(
    token=Depends(oauth2_scheme),
    master_db: MasterNodeDB = Depends(get_master_db)
) -> dict:
    """Get the current authenticated account."""
    token_str = token.credentials if hasattr(token, "credentials") else token
    payload = decode_access_token(token_str)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    
    account_id = payload.get("sub")
    if not account_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    
    account_result = master_db.select(
        "SELECT ACCOUNT_ID, USERNAME, EMAIL, ACCOUNT_TYPE FROM ACCOUNT WHERE ACCOUNT_ID = $1",
        [account_id]
    )
    
    if not account_result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    
    result = account_result[0]
    account_dict = {}
    for k, v in result.items():
        key_lower = k.lower()
        account_dict[key_lower] = v
    
    return account_dict


def parse_folder_structure(files: List[FileInFolder]) -> List[Dict]:
    """
    Extract folder structure from file paths.
    Returns a list of folder definitions sorted by depth (parents before children).
    """
    folder_paths = set()
    
    # Extract all unique folder paths
    for file_data in files:
        # Split path and remove filename
        path_parts = file_data.relative_path.split('/')
        if len(path_parts) > 1:  # Has folders
            for i in range(len(path_parts) - 1):
                folder_path = '/'.join(path_parts[:i + 1])
                folder_paths.add(folder_path)
    
    # Convert to list of folder definitions
    folders = []
    for path in folder_paths:
        path_parts = path.split('/')
        folders.append({
            'path': path,
            'name': path_parts[-1],
            'parent_path': '/'.join(path_parts[:-1]) if len(path_parts) > 1 else None
        })
    
    # Sort by depth (parents before children)
    folders.sort(key=lambda f: f['path'].count('/'))
    
    return folders


def create_single_folder_direct(
    folder_name: str,
    parent_folder_id: Optional[str],
    account_id: str,
    master_db: MasterNodeDB
) -> str:
    """
    Create a single folder using direct database calls.
    Returns the created folder_id or existing folder_id if it already exists.
    """
    try:
        # Validate parent folder exists if provided
        if parent_folder_id is not None:
            parent = master_db.select(
                "SELECT FOLDER_ID FROM FOLDER WHERE FOLDER_ID = $1 AND ACCOUNT_ID = $2",
                [parent_folder_id, account_id]
            )
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Parent folder {parent_folder_id} not found"
                )
        
        # Check if folder already exists
        if parent_folder_id is None:
            existing = master_db.select(
                "SELECT FOLDER_ID FROM FOLDER WHERE ACCOUNT_ID = $1 AND PARENT_FOLDER_ID IS NULL AND NAME = $2",
                [account_id, folder_name]
            )
        else:
            existing = master_db.select(
                "SELECT FOLDER_ID FROM FOLDER WHERE ACCOUNT_ID = $1 AND PARENT_FOLDER_ID = $2 AND NAME = $3",
                [account_id, parent_folder_id, folder_name]
            )
        
        if existing:
            # Return existing folder ID
            folder_id = str(existing[0]['folder_id'])
            logger.info(f"Folder '{folder_name}' already exists with ID: {folder_id}")
            return folder_id
        
        # Create new folder
        folder_id = str(uuid.uuid4())
        master_db.execute(
            """
            INSERT INTO FOLDER (FOLDER_ID, NAME, ACCOUNT_ID, PARENT_FOLDER_ID, CREATED_AT)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            [folder_id, folder_name.strip(), account_id, parent_folder_id]
        )
        
        logger.info(f"Created folder '{folder_name}' with ID: {folder_id}")
        return folder_id
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating folder '{folder_name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create folder: {str(e)}"
        )


def create_folder_structure_direct(
    root_folder_name: str,
    files: List[FileInFolder],
    parent_folder_id: Optional[str],
    account_id: str,
    master_db: MasterNodeDB
) -> Dict[str, str]:
    """
    Create the complete folder structure using direct database calls.
    Returns a mapping of folder paths to folder IDs.
    """
    folder_map = {}
    
    # Parse folder structure from file paths
    folders = parse_folder_structure(files)
    
    # Create root folder first
    try:
        root_folder_id = create_single_folder_direct(
            folder_name=root_folder_name,
            parent_folder_id=parent_folder_id,
            account_id=account_id,
            master_db=master_db
        )
        folder_map[root_folder_name] = root_folder_id
        logger.info(f"Created root folder: {root_folder_name} ({root_folder_id})")
    except Exception as e:
        logger.error(f"Failed to create root folder '{root_folder_name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create root folder: {str(e)}"
        )
    
    # Create subfolders in order (parents before children)
    for folder in folders:
        parent_path = folder['parent_path']
        # Parent is either another subfolder or the root
        parent_id = folder_map.get(parent_path, root_folder_id)
        
        try:
            folder_id = create_single_folder_direct(
                folder_name=folder['name'],
                parent_folder_id=parent_id,
                account_id=account_id,
                master_db=master_db
            )
            folder_map[folder['path']] = folder_id
            logger.info(f"Created subfolder: {folder['path']} ({folder_id})")
            
        except Exception as e:
            logger.error(f"Error creating folder {folder['path']}: {e}")
            # Continue with other folders even if one fails
            continue
    
    return folder_map


async def upload_file_direct(
    filename: str,
    file_data_base64: str,
    folder_id: str,
    erasure_id: str,
    content_type: str,
    account_id: str
) -> Dict:
    """
    Upload a single file by calling the upload logic directly (no HTTP overhead).
    Returns upload result with success status and details.
    """
    try:
        result = await process_file_upload(
            filename=filename,
            file_data_base64=file_data_base64,
            content_type=content_type,
            folder_id=folder_id,
            erasure_id=erasure_id,
            account_id=account_id
        )
        
        logger.info(f"Successfully uploaded {filename} directly")
        return {
            "success": True,
            "file_id": result["file_id"],
            "version_id": result["version_id"],
            "file_size": result["file_size"],
            "fragments_stored": result["fragments_stored"]
        }
            
    except HTTPException as e:
        logger.error(f"Upload failed for {filename}: {e.detail}")
        return {
            "success": False,
            "error": e.detail
        }
    except Exception as e:
        logger.error(f"Unexpected error uploading {filename}: {e}")
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }


# ===== MAIN ENDPOINT =====

@router.post("/upload-folder", response_model=FolderUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_folder(
    request: Request,
    # Multipart form fields
    folder_name: Optional[str] = Form(None),
    parent_folder_id: Optional[str] = Form(None),
    erasure_id: Optional[str] = Form("MEDIUM"),
    file_metadata: Optional[str] = Form(None),  # JSON string
    # Legacy JSON body
    upload_data: Optional[FolderUploadRequest] = None,
    current_account = Depends(get_current_account),
    token: str = Depends(oauth2_scheme),
    master_db: MasterNodeDB = Depends(get_master_db)
):
    """
    Upload an entire folder with its structure to distributed storage.
    
    Supports TWO methods:
    1. Multipart/form-data (PREFERRED) - Binary files with progress tracking + encryption
    2. JSON with base64 (legacy) - Backward compatibility
    
    This endpoint:
    1. Creates folder hierarchy using direct database calls (fast!)
    2. Uploads each file with AES-256-GCM encryption + SSS key storage
    """
    try:
        account_id = current_account["account_id"]
        token_str = token.credentials if hasattr(token, "credentials") else token
        
        # Detect upload method
        content_type_header = request.headers.get("content-type", "")
        
        if "multipart/form-data" in content_type_header:
            # Method 1: Multipart upload (NEW - with encryption)
            if not folder_name or not file_metadata:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="folder_name and file_metadata required for multipart upload"
                )
            
            # Parse file metadata JSON
            try:
                metadata_list = json.loads(file_metadata)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid file_metadata JSON"
                )
            
            # Extract files from form data
            form = await request.form()
            file_entries = []
            
            for i, meta in enumerate(metadata_list):
                file_key = f"file_{i}"
                if file_key not in form:
                    logger.warning(f"Missing file for index {i}")
                    continue
                
                file_obj = form[file_key]
                file_contents = await file_obj.read()
                file_data_b64 = base64.b64encode(file_contents).decode('utf-8')
                
                file_entries.append(FileInFolder(
                    filename=meta['filename'],
                    data=file_data_b64,
                    relative_path=meta['relative_path'],
                    content_type=meta.get('content_type', 'application/octet-stream')
                ))
            
            actual_folder_name = folder_name
            actual_parent_folder_id = parent_folder_id if parent_folder_id and parent_folder_id != '' else None
            actual_erasure_id = erasure_id
            
            logger.info(f"Multipart folder upload: {actual_folder_name} with {len(file_entries)} files")
            
        else:
            # Method 2: JSON with base64 (LEGACY)
            if not upload_data:
                try:
                    body = await request.json()
                    upload_data = FolderUploadRequest(**body)
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid request: expected multipart/form-data or JSON body"
                    )
            
            file_entries = upload_data.files
            actual_folder_name = upload_data.folder_name
            actual_parent_folder_id = upload_data.parent_folder_id
            actual_erasure_id = upload_data.erasure_id
            
            logger.info(f"Base64 JSON folder upload: {actual_folder_name} with {len(file_entries)} files")
        
        logger.info(f"Starting folder upload: {actual_folder_name} with {len(file_entries)} files for account {account_id}")
        
        # Step 1: Create folder structure using direct database calls (FAST!)
        try:
            folder_map = create_folder_structure_direct(
                root_folder_name=actual_folder_name,
                files=file_entries,
                parent_folder_id=actual_parent_folder_id,
                account_id=account_id,
                master_db=master_db
            )
            
            root_folder_id = folder_map[actual_folder_name]
            logger.info(f"Created folder structure with {len(folder_map)} folders")
            
        except Exception as e:
            logger.error(f"Failed to create folder structure: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create folder structure: {str(e)}"
            )
        
        # Step 2: Upload each file using existing /files/upload endpoint
        upload_results = []
        files_uploaded = 0
        files_failed = 0
        errors = []
        
        for file_data in file_entries:
            try:
                # Determine folder ID for this file
                path_parts = file_data.relative_path.split('/')
                if len(path_parts) > 1:
                    # File is in a subfolder
                    folder_path = '/'.join(path_parts[:-1])
                    folder_id = folder_map.get(folder_path, root_folder_id)
                else:
                    # File is in root folder
                    folder_id = root_folder_id
                
                logger.info(f"Uploading {file_data.relative_path} to folder {folder_id}")
                
                # Call upload logic directly (no HTTP overhead!)
                result = await upload_file_direct(
                    filename=file_data.filename,
                    file_data_base64=file_data.data,  # Pass as-is (already base64)
                    folder_id=folder_id,
                    erasure_id=actual_erasure_id,
                    content_type=file_data.content_type,
                    account_id=account_id
                )
                
                if result["success"]:
                    files_uploaded += 1
                    upload_results.append(FileUploadResult(
                        filename=file_data.filename,
                        relative_path=file_data.relative_path,
                        success=True,
                        file_id=result.get("file_id"),
                        version_id=result.get("version_id"),
                        file_size=result.get("file_size"),
                        fragments_stored=result.get("fragments_stored")
                    ))
                    logger.info(f"✅ Uploaded: {file_data.relative_path}")
                else:
                    files_failed += 1
                    error_msg = result.get("error", "Unknown error")
                    upload_results.append(FileUploadResult(
                        filename=file_data.filename,
                        relative_path=file_data.relative_path,
                        success=False,
                        error=error_msg
                    ))
                    errors.append(f"{file_data.relative_path}: {error_msg}")
                    logger.error(f"❌ Failed: {file_data.relative_path} - {error_msg}")
                    
            except Exception as e:
                files_failed += 1
                error_msg = str(e)
                upload_results.append(FileUploadResult(
                    filename=file_data.filename,
                    relative_path=file_data.relative_path,
                    success=False,
                    error=error_msg
                ))
                errors.append(f"{file_data.relative_path}: {error_msg}")
                logger.error(f"❌ Exception uploading {file_data.relative_path}: {e}")
        
        success = files_failed == 0
        
        logger.info(f"Folder upload completed: {files_uploaded}/{len(file_entries)} files uploaded successfully")
        
        return FolderUploadResponse(
            success=success,
            root_folder_id=root_folder_id,
            folder_name=actual_folder_name,
            total_files=len(file_entries),
            files_uploaded=files_uploaded,
            files_failed=files_failed,
            upload_results=upload_results,
            folder_structure=folder_map,
            errors=errors
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading folder: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading folder: {str(e)}"
        )


# ===== FOLDER BROWSING ENDPOINTS =====
# You might already have these in create_folders.py, so these are optional

@router.get("/folders/root")
async def get_root_folders(current_account = Depends(get_current_account)):
    """
    Get all root-level folders for the current user.
    This just forwards to your existing /folders/list endpoint.
    """
    try:
        # You can call your existing endpoint or duplicate the logic here
        # For now, we'll return a simple message
        return {
            "message": "Use GET /api/folders/list to get folders",
            "account_id": current_account["account_id"]
        }
    except Exception as e:
        logger.error(f"Error getting root folders: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting root folders: {str(e)}"
        )