from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict
import logging
import requests
import os
import io
import zipfile
import base64

from app.core.security import decode_access_token
from app.routes.login import oauth2_scheme
from app.master_node_db import MasterNodeDB, get_master_db
from app.routes.download_files import process_file_download

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

# Internal URLs for calling our own FastAPI endpoints
FASTAPI_INTERNAL_URL = os.getenv("FASTAPI_INTERNAL_URL", "http://localhost:8000")


# ===== HELPER FUNCTIONS =====

async def download_single_file_direct(
    file_id: str,
    account_id: str
) -> Dict:
    """
    Download a single file by calling download logic directly (no HTTP overhead).
    Returns file data in base64 encoding.
    """
    try:
        # Call download logic directly
        file_data = await process_file_download(file_id, account_id)
        
        logger.info(f"Downloaded file {file_id}: {len(file_data)} bytes")
        return {
            "success": True,
            "data": base64.b64encode(file_data).decode()
        }
    except HTTPException as e:
        if e.status_code == 403:
            logger.error(f"Access denied for file: {file_id}")
            return {
                "success": False,
                "error": "Access denied"
            }
        else:
            logger.error(f"Failed to download file {file_id}: {e.detail}")
            return {
                "success": False,
                "error": e.detail
            }
    except Exception as e:
        logger.error(f"Error downloading file {file_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


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
    
    return account_result[0]


def get_folder_hierarchy(folder_id: str, account_id: str, master_db: MasterNodeDB) -> Dict[str, Dict]:
    """
    Recursively get all subfolders within a folder.
    Returns a dict mapping folder_id -> folder info (including path).
    """
    folders = {}
    
    def get_children(parent_id: Optional[str], parent_path: str = ""):
        """Recursively get all child folders."""
        if parent_id is None:
            query = """
                SELECT FOLDER_ID, NAME, PARENT_FOLDER_ID 
                FROM FOLDER 
                WHERE ACCOUNT_ID = $1 AND PARENT_FOLDER_ID IS NULL
            """
            params = [account_id]
        else:
            query = """
                SELECT FOLDER_ID, NAME, PARENT_FOLDER_ID 
                FROM FOLDER 
                WHERE ACCOUNT_ID = $1 AND PARENT_FOLDER_ID = $2
            """
            params = [account_id, parent_id]
        
        results = master_db.select(query, params)
        
        for row in results:
            fid = row.get("folder_id") or row.get("FOLDER_ID")
            fname = row.get("name") or row.get("NAME")
            
            current_path = f"{parent_path}/{fname}" if parent_path else fname
            
            folders[str(fid)] = {
                "name": fname,
                "path": current_path,
                "folder_id": str(fid)
            }
            
            # Recursively get children
            get_children(str(fid), current_path)
    
    # Get the root folder info
    root_folder = master_db.select(
        "SELECT FOLDER_ID, NAME FROM FOLDER WHERE FOLDER_ID = $1 AND ACCOUNT_ID = $2",
        [folder_id, account_id]
    )
    
    if not root_folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    
    root_name = root_folder[0].get("name") or root_folder[0].get("NAME")
    folders[folder_id] = {
        "name": root_name,
        "path": root_name,
        "folder_id": folder_id
    }
    
    # Get all subfolders
    get_children(folder_id, root_name)
    
    return folders


def get_files_in_folders(folder_ids: List[str], account_id: str, master_db: MasterNodeDB) -> List[Dict]:
    """
    Get all files in the specified folders.
    Returns list of file metadata.
    """
    if not folder_ids:
        return []
    
    # Build query with IN clause
    placeholders = ", ".join([f"${i+2}" for i in range(len(folder_ids))])
    query = f"""
        SELECT FILE_ID, FILE_NAME, FILE_SIZE, FOLDER_ID, LOGICAL_PATH
        FROM FILE_OBJECTS
        WHERE ACCOUNT_ID = $1 AND FOLDER_ID IN ({placeholders})
        ORDER BY LOGICAL_PATH
    """
    
    params = [account_id] + folder_ids
    results = master_db.select(query, params)
    
    files = []
    for row in results:
        files.append({
            "file_id": str(row.get("file_id") or row.get("FILE_ID")),
            "file_name": row.get("file_name") or row.get("FILE_NAME"),
            "file_size": row.get("file_size") or row.get("FILE_SIZE"),
            "folder_id": str(row.get("folder_id") or row.get("FOLDER_ID")),
            "logical_path": row.get("logical_path") or row.get("LOGICAL_PATH")
        })
    
    return files


async def download_single_file_via_endpoint(file_id: str, token: str) -> Dict:
    """
    Download a single file by calling the existing /files/download/{file_id} endpoint.
    This endpoint handles:
    - Getting fragments from storage nodes
    - Reed-Solomon decoding
    - Reconstructing the original file
    Returns the file data in base64.
    """
    try:
        response = requests.get(
            f"{FASTAPI_INTERNAL_URL}/files/download/{file_id}",
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=600  # 10 minute timeout for large files
        )
        
        if response.status_code == 200:
            # The download endpoint returns binary file data (already reconstructed from fragments)
            file_data = response.content
            logger.info(f"Downloaded file {file_id}: {len(file_data)} bytes")
            return {
                "success": True,
                "data": base64.b64encode(file_data).decode(),
                "size": len(file_data)
            }
        elif response.status_code == 404:
            logger.error(f"File not found: {file_id}")
            return {
                "success": False,
                "error": "File not found"
            }
        elif response.status_code == 403:
            logger.error(f"Access denied for file: {file_id}")
            return {
                "success": False,
                "error": "Access denied"
            }
        else:
            logger.error(f"Failed to download file {file_id}: {response.status_code} - {response.text}")
            return {
                "success": False,
                "error": f"Download failed with status {response.status_code}"
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"Download timeout for file {file_id}")
        return {
            "success": False,
            "error": "Download timeout - file reconstruction took too long"
        }
    except Exception as e:
        logger.error(f"Error downloading file {file_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ===== MAIN ENDPOINT =====

@router.get("/download-folder/{folder_id}")
async def download_folder_as_zip(
    folder_id: str,
    current_account = Depends(get_current_account),
    master_db: MasterNodeDB = Depends(get_master_db)
):
    """
    Download an entire folder as a ZIP file.
    Includes all subfolders and files with their hierarchy preserved.
    
    This endpoint:
    1. Gets folder hierarchy recursively from database
    2. Gets all files in those folders
    3. Downloads each file using direct function call (fast!)
    4. Packages everything into a single ZIP file
    5. Returns ZIP for user to download
    """
    try:
        account_id = current_account.get("account_id") or current_account.get("ACCOUNT_ID")
        
        logger.info(f"Downloading folder {folder_id} as ZIP for account {account_id}")
        
        # Step 1: Get folder hierarchy
        folders = get_folder_hierarchy(folder_id, account_id, master_db)
        root_folder_name = folders[folder_id]["name"]
        
        logger.info(f"Found {len(folders)} folders in hierarchy")
        
        # Step 2: Get all files in these folders
        folder_ids = list(folders.keys())
        files = get_files_in_folders(folder_ids, account_id, master_db)
        
        logger.info(f"Found {len(files)} files to download")
        
        # Debug: Log folder and file details to identify duplicates
        logger.info(f"Folder IDs: {folder_ids}")
        logger.info(f"Files: {[f['file_name'] for f in files]}")
        
        # Deduplicate files by file_id to prevent ZIP duplicates
        seen_files = set()
        unique_files = []
        for file_meta in files:
            if file_meta['file_id'] not in seen_files:
                seen_files.add(file_meta['file_id'])
                unique_files.append(file_meta)
            else:
                logger.warning(f"Duplicate file detected: {file_meta['file_name']} (ID: {file_meta['file_id']})")
        
        files = unique_files
        logger.info(f"After deduplication: {len(files)} unique files")
        
        if not files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No files found in folder"
            )
        
        # Step 3: Create ZIP file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Track paths to prevent duplicates at ZIP level too
            zip_paths_used = set()
            
            for file_meta in files:
                try:
                    # Download file data using direct function call (fast!)
                    logger.info(f"Downloading file: {file_meta['file_name']}")
                    result = await download_single_file_direct(
                        file_id=file_meta['file_id'],
                        account_id=account_id
                    )
                    
                    if result["success"]:
                        # Decode base64 data
                        file_data = base64.b64decode(result["data"])
                        
                        # Get relative path from folder structure
                        folder_path = folders[file_meta['folder_id']]["path"]
                        
                        # Remove root folder name from path to avoid nesting
                        # E.g., "My Test Folder/subfolder" -> "subfolder"
                        if folder_path == root_folder_name:
                            # File is directly in root folder
                            relative_path = file_meta['file_name']
                        elif folder_path.startswith(f"{root_folder_name}/"):
                            # Remove root folder prefix
                            relative_path = f"{folder_path[len(root_folder_name) + 1:]}/{file_meta['file_name']}"
                        else:
                            # Fallback - shouldn't happen but keep original behavior
                            relative_path = f"{folder_path}/{file_meta['file_name']}"
                        
                        # Additional check: prevent duplicate ZIP paths
                        if relative_path in zip_paths_used:
                            logger.warning(f"Duplicate ZIP path detected, skipping: {relative_path}")
                            continue
                        
                        zip_paths_used.add(relative_path)
                        
                        # Add to ZIP with proper path
                        zip_file.writestr(relative_path, file_data)
                        logger.info(f"✅ Added to ZIP: {relative_path}")
                    else:
                        logger.error(f"❌ Failed to download: {file_meta['file_name']} - {result.get('error')}")
                        
                except Exception as e:
                    logger.error(f"Error processing file {file_meta['file_name']}: {e}")
                    continue
        
        # Step 4: Return ZIP file as streaming response
        zip_buffer.seek(0)
        
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={root_folder_name}.zip"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading folder: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading folder: {str(e)}"
        )