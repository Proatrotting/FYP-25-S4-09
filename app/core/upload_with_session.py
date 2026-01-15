"""
Enhanced upload with session tracking and cancellation support.
"""

import base64
import hashlib
import logging
import requests
import uuid
from typing import Optional
from fastapi import HTTPException, status

from app.core.session_manager import session_manager, SessionType, SessionStatus
from app.core.config import get_settings
from app.core.erasure_coding import get_erasure_coder_for_profile

logger = logging.getLogger(__name__)
settings = get_settings()
MASTER_NODE_URL = settings.master_node_url

def process_file_upload_with_session(
    filename: str,
    file_data_base64: str,
    content_type: str,
    folder_id: Optional[str],
    erasure_id: str,
    account_id: str
) -> dict:
    """
    Enhanced file upload with session tracking and cancellation support.
    Returns a dict with upload results including session_id.
    """
    # Decode the base64 file data
    file_data = base64.b64decode(file_data_base64)
    file_size = len(file_data)
    
    # Create upload session
    session = session_manager.create_session(
        session_type=SessionType.UPLOAD,
        account_id=account_id,
        filename=filename,
        total_size=file_size
    )
    
    try:
        # Generate file hash
        file_hash = hashlib.sha256(file_data).hexdigest()
        
        # Check for cancellation
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session.session_id)
            raise HTTPException(status_code=409, detail="Upload cancelled")
        
        # Create file metadata in master node
        logical_path = f"/{filename}"
        if folder_id:
            logical_path = f"/folders/{folder_id}/{filename}"
        
        create_file_payload = {
            "account_id": account_id,
            "file_name": filename,
            "file_size": file_size,
            "logical_path": logical_path,
            "folder_id": folder_id,
            "erasure_id": erasure_id
        }
        
        # Create file metadata
        response = requests.post(f"{MASTER_NODE_URL}/files", json=create_file_payload)
        if response.status_code not in [200, 201]:
            logger.error(f"Failed to create file metadata: Status {response.status_code}, Response: {response.text}")
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create file metadata: {response.text}"
            )
        
        file_metadata = response.json()
        file_id = file_metadata["fileId"]
        version_id = file_metadata["versionId"]
        
        # Update session with file_id
        session.file_id = file_id
        
        # Check for cancellation after metadata creation
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            # Clean up file metadata
            try:
                requests.delete(f"{MASTER_NODE_URL}/files/{file_id}")
            except:
                pass
            session_manager.remove_session(session.session_id)
            raise HTTPException(status_code=409, detail="Upload cancelled")
        
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
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erasure coding failed: {str(e)}"
            )
        
        # Check for cancellation after encoding
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            try:
                requests.delete(f"{MASTER_NODE_URL}/files/{file_id}")
            except:
                pass
            session_manager.remove_session(session.session_id)
            raise HTTPException(status_code=409, detail="Upload cancelled")
        
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
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get fragment distribution plan: {distribute_response.text}"
            )
        
        distribution_result = distribute_response.json()
        
        if not distribution_result.get("success", False):
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Master node failed to create distribution plan"
            )
        
        distributed_fragments = distribution_result.get("fragments", [])
        
        # Store fragments on storage nodes with cancellation checks
        fragments_stored = 0
        total_fragments_expected = len(fragment_data_list)
        
        for i, fragment_plan in enumerate(distributed_fragments):
            # Check for cancellation before each fragment
            if session.is_cancelled():
                logger.info(f"Upload cancelled during fragment storage at fragment {i}")
                session.status = SessionStatus.CANCELLED
                # Don't clean up here - let the cancel endpoint handle it
                raise HTTPException(status_code=409, detail="Upload cancelled")
            
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
                    # Track successful fragment storage
                    session.mark_fragment_uploaded(fragment_id, node_endpoint)
                    
                    # Update progress
                    progress = int((fragments_stored / total_fragments_expected) * file_size)
                    session.update_progress(progress)
                    
                    logger.info(f"✅ Fragment {fragment_id} stored successfully ({fragments_stored}/{total_fragments_expected})")
                else:
                    logger.error(f"❌ Failed to store fragment {fragment_id}: {store_response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Exception storing fragment {i}: {e}")
                continue
        
        # Final cancellation check
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            raise HTTPException(status_code=409, detail="Upload cancelled")
        
        upload_status = "complete" if fragments_stored == total_fragments_expected else "partial"
        if fragments_stored == 0:
            upload_status = "failed"
            session.fail()
        else:
            session.complete()
        
        logger.info(f"File upload completed: {filename}, fragments: {fragments_stored}/{total_fragments_expected}")
        
        # Remove successful sessions after a delay to allow progress queries
        if upload_status == "complete":
            import threading
            def remove_later():
                import time
                time.sleep(30)  # Keep session for 30 seconds
                session_manager.remove_session(session.session_id)
            threading.Thread(target=remove_later, daemon=True).start()
        
        return {
            "session_id": session.session_id,
            "file_id": file_id,
            "version_id": version_id,
            "filename": filename,
            "file_size": file_size,
            "content_type": content_type,
            "upload_status": upload_status,
            "fragments_stored": fragments_stored,
            "erasure_profile": erasure_id
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions (including cancellation)
        raise
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error during upload: {e}")
        session.fail()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )