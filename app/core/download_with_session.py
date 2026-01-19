"""
Enhanced download with session tracking and cancellation support.
"""

import asyncio
import logging
import httpx
from typing import Optional
from fastapi import HTTPException, status

from app.core.session_manager import session_manager, SessionType, SessionStatus
from app.core.config import get_settings
from app.core.erasure_coding import get_erasure_coder_for_profile
from app.core.lazy_repair import LazyRepair
# Import AES-256 decryption
from app.core.file_encryption import decrypt_file_data

logger = logging.getLogger(__name__)
settings = get_settings()
MASTER_NODE_URL = settings.master_node_url

async def process_file_download_with_session(
    file_id: str,
    account_id: str,
    session_id: Optional[str] = None
) -> tuple[bytes, str]:
    """
    Enhanced file download with session tracking and cancellation support.
    Returns reconstructed file data as bytes and session_id.
    """
    # Create or get download session
    if session_id:
        session = session_manager.get_session(session_id)
        if not session or session.account_id != account_id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        # Get file info to verify ownership and get filename
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
        
        # Create download session
        session = session_manager.create_session(
            session_type=SessionType.DOWNLOAD,
            account_id=account_id,
            file_id=file_id,
            filename=file_info["file_name"],
            total_size=file_info["file_size"]
        )
        session_id = session.session_id
    
    try:
        # Check for cancellation
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session_id)
            raise HTTPException(status_code=409, detail="Download cancelled")
        
        # Get file info if we don't have it yet
        async with httpx.AsyncClient() as client:
            file_info_response = await client.get(f"{MASTER_NODE_URL}/files/info/{file_id}")
        
        if file_info_response.status_code == 404:
            session.fail()
            raise HTTPException(status_code=404, detail="File not found")
        
        if file_info_response.status_code != 200:
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file info: {file_info_response.text}"
            )
        
        file_info = file_info_response.json()["file"]
        
        # Update session with file info if missing
        if not session.filename:
            session.filename = file_info["file_name"]
        if not session.total_size:
            session.total_size = file_info["file_size"]
        
        # Check for cancellation after file info
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session_id)
            raise HTTPException(status_code=409, detail="Download cancelled")
        
        # Get fragment information
        async with httpx.AsyncClient() as client:
            fragments_response = await client.get(f"{MASTER_NODE_URL}/fragments/{file_id}")
        
        if fragments_response.status_code != 200:
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve fragments: {fragments_response.text}"
            )
        
        fragments = fragments_response.json()
        
        if not fragments:
            session.fail()
            raise HTTPException(status_code=404, detail="File fragments not found")
        
        # Initialize erasure decoder
        try:
            erasure_coder = get_erasure_coder_for_profile(file_info["erasure_id"])
            logger.info(f"Using file's original Reed-Solomon profile {file_info['erasure_id']} for download")
        except Exception as e:
            logger.error(f"Failed to initialize erasure decoder: {e}")
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize erasure decoder: {str(e)}"
            )
        
        # Check for cancellation before fragment download
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session_id)
            raise HTTPException(status_code=409, detail="Download cancelled")
        
        # Download available fragments from storage nodes
        available_fragments = []
        fragment_indexes = []
        sorted_fragments = sorted(fragments, key=lambda x: x["num_fragment"])
        total_fragments = len(sorted_fragments)
        
        logger.info(f"Attempting to download {total_fragments} fragments for file {file_id}")
        
        async with httpx.AsyncClient() as client:
            for i, fragment in enumerate(sorted_fragments):
                # Check for cancellation during each fragment download
                if session.is_cancelled():
                    logger.info(f"Download cancelled during fragment retrieval at fragment {i}")
                    session.status = SessionStatus.CANCELLED
                    session_manager.remove_session(session_id)
                    raise HTTPException(status_code=409, detail="Download cancelled")
                
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
                            import base64
                            decoded_data = base64.b64decode(fragment_data["data"])
                            available_fragments.append(decoded_data)
                            fragment_indexes.append(fragment["num_fragment"])
                            
                            # Update progress
                            progress = int((len(available_fragments) / total_fragments) * int(session.total_size))
                            session.update_progress(progress)
                            
                            logger.info(f"Successfully retrieved fragment {fragment['num_fragment']} ({len(decoded_data)} bytes)")
                        else:
                            logger.warning(f"Storage node returned empty data for fragment {fragment['fragment_id']}")
                    else:
                        logger.warning(f"Storage node failed to retrieve fragment {fragment['fragment_id']}: {frag_response.status_code}")
                except httpx.RequestError as e:
                    logger.warning(f"Failed to fetch fragment {fragment['fragment_id']} from {fragment_url}: {e}")
                    continue
        
        # Final cancellation check
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session_id)
            raise HTTPException(status_code=409, detail="Download cancelled")
        
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
                    file_id=file_id,
                    missing_fragments=len(sorted_fragments) - len(available_fragments),
                    account_id=account_id
                )
                logger.info("Lazy repair job created successfully")
            except Exception as e:
                logger.error(f"Failed to create lazy repair job: {e}")
        
        # Try to reconstruct the file
        if not erasure_coder.can_reconstruct(len(available_fragments)):
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cannot reconstruct file: only {len(available_fragments)} fragments available, need at least {erasure_coder.get_fragment_info()['k']}"
            )
        
        # Final cancellation check before reconstruction
        if session.is_cancelled():
            session.status = SessionStatus.CANCELLED
            session_manager.remove_session(session_id)
            raise HTTPException(status_code=409, detail="Download cancelled")
        
        try:
            logger.info(f"Reconstructing file using {len(available_fragments)} fragments")
            reconstructed_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
            
            logger.info(f"Reed-Solomon reconstruction completed: {len(reconstructed_data)} bytes")
            
            # Check if file is encrypted and decrypt if necessary
            is_encrypted = file_info.get("is_encrypted", False)
            if is_encrypted:
                try:
                    logger.info(f"File is encrypted, attempting decryption for account {account_id}")
                    decrypted_data = decrypt_file_data(
                        encrypted_data=reconstructed_data,
                        account_id=account_id,
                        encryption_metadata=file_info.get("encryption_metadata")
                    )
                    
                    # Verify decrypted file size matches expected original size
                    expected_original_size = file_info.get("original_file_size")
                    if expected_original_size and len(decrypted_data) != expected_original_size:
                        logger.warning(
                            f"Decrypted file size mismatch: got {len(decrypted_data)}, "
                            f"expected {expected_original_size}"
                        )
                    
                    logger.info(f"Successfully decrypted file: {len(reconstructed_data)} bytes -> {len(decrypted_data)} bytes")
                    final_data = decrypted_data
                    
                except Exception as decrypt_error:
                    logger.error(f"File decryption failed: {decrypt_error}")
                    session.fail()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"File decryption failed: {str(decrypt_error)}"
                    )
            else:
                # File is not encrypted, return as-is
                logger.info("File is not encrypted, returning reconstructed data")
                final_data = reconstructed_data
            
            # Update final progress
            session.update_progress(session.total_size)
            session.complete()
            
            logger.info(f"File download completed: {len(final_data)} bytes")
            
            # Remove successful sessions after a delay
            import threading
            def remove_later():
                import time
                time.sleep(30)  # Keep session for 30 seconds
                session_manager.remove_session(session_id)
            threading.Thread(target=remove_later, daemon=True).start()
            
            return final_data, session_id
            
        except Exception as e:
            logger.error(f"File reconstruction failed: {e}")
            session.fail()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"File reconstruction failed: {str(e)}"
            )
    
    except HTTPException:
        # Re-raise HTTP exceptions (including cancellation)
        raise
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Unexpected error during download: {e}")
        session.fail()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}"
        )