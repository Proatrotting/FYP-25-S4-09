"""
Key Storage Module for Secret Sharing Scheme (SSS)

This module handles storing and retrieving encryption keys as text files
in storage nodes, distributed like file fragments for security.
"""
import os
import logging
import httpx
import random
from typing import Optional, List, Tuple
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class KeyStorageManager:
    """Manages encryption key storage across storage nodes."""
    
    def __init__(self):
        """Initialize the key storage manager."""
        self.settings = get_settings()
        self.timeout = httpx.Timeout(30.0)
    
    def get_available_storage_nodes(self) -> List[str]:
        """
        Get list of available storage nodes for key storage.
        Returns URLs of storage nodes.
        """
        storage_nodes = []
        base_port = 8005
        
        # Check storage nodes 1-12 (matching your current setup)
        for i in range(1, 13):
            node_url = f"http://storage_node_{i}:3000"
            storage_nodes.append(node_url)
        
        return storage_nodes
    
    async def store_key(self, file_id: str, encryption_key: bytes) -> Tuple[str, str]:
        """
        Store an encryption key as a text file in a random storage node.
        
        Args:
            file_id: The file ID this key belongs to
            encryption_key: The encryption key bytes
            
        Returns:
            Tuple of (storage_node_url, key_fragment_id)
        """
        try:
            # Convert key to base64 text format
            from app.core.file_encryption import get_file_encryption
            encryption = get_file_encryption()
            key_text = encryption.key_to_string(encryption_key)
            
            # Generate a proper UUID for key fragment ID
            import uuid
            key_fragment_id = str(uuid.uuid4())
            
            # Select random storage node for key storage
            storage_nodes = self.get_available_storage_nodes()
            selected_node = random.choice(storage_nodes)
            
            # Prepare key data as a "fragment" for storage
            key_data = key_text.encode('utf-8')
            
            # Store the key as a fragment
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                store_url = f"{selected_node}/fragments"
                
                # Prepare fragment data for storage node
                import base64
                key_data_b64 = base64.b64encode(key_data).decode('utf-8')
                
                fragment_payload = {
                    "fragmentId": key_fragment_id,
                    "data": key_data_b64,
                    "bytes": len(key_data),
                    "contentHash": f"key_{file_id}_hash",
                    "fileId": f"key_{file_id}",
                    "fragmentOrder": 0  # Keys are single fragments
                }
                
                # Use POST to store the key fragment
                response = await client.post(
                    store_url,
                    json=fragment_payload,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code not in [200, 201]:
                    raise Exception(f"Failed to store key: HTTP {response.status_code}")
                
                logger.info(f"Encryption key stored in {selected_node} as {key_fragment_id}")
                return selected_node, key_fragment_id
                
        except Exception as e:
            logger.error(f"Failed to store encryption key for file {file_id}: {e}")
            raise RuntimeError(f"Key storage failed: {str(e)}")
    
    async def retrieve_key(self, storage_node_url: str, key_fragment_id: str) -> bytes:
        """
        Retrieve an encryption key from a storage node.
        
        Args:
            storage_node_url: URL of the storage node containing the key
            key_fragment_id: ID of the key fragment
            
        Returns:
            The encryption key bytes
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                retrieve_url = f"{storage_node_url}/fragments/{key_fragment_id}"
                
                response = await client.get(retrieve_url)
                
                if response.status_code == 404:
                    raise Exception(f"Encryption key not found: {key_fragment_id}")
                elif response.status_code != 200:
                    raise Exception(f"Failed to retrieve key: HTTP {response.status_code}")
                
                # Parse the JSON response and decode the key
                response_data = response.json()
                if not response_data.get("success"):
                    raise Exception(f"Storage node returned error")
                
                # Get base64 data from response
                key_data_b64 = response_data.get("data")
                if not key_data_b64:
                    raise Exception(f"No key data in response")
                
                # Decode from base64 to get the original key text
                import base64
                key_data = base64.b64decode(key_data_b64)
                key_text = key_data.decode('utf-8')
                
                # Convert key text back to encryption key bytes
                from app.core.file_encryption import get_file_encryption
                encryption = get_file_encryption()
                encryption_key = encryption.key_from_string(key_text)
                
                logger.info(f"Encryption key retrieved from {storage_node_url}")
                return encryption_key
                
        except Exception as e:
            logger.error(f"Failed to retrieve encryption key {key_fragment_id}: {e}")
            raise RuntimeError(f"Key retrieval failed: {str(e)}")
    
    async def delete_key(self, storage_node_url: str, key_fragment_id: str) -> bool:
        """
        Delete an encryption key from a storage node.
        
        Args:
            storage_node_url: URL of the storage node containing the key
            key_fragment_id: ID of the key fragment
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                delete_url = f"{storage_node_url}/fragments/{key_fragment_id}"
                
                response = await client.delete(delete_url)
                
                if response.status_code in [200, 204, 404]:  # 404 means already deleted
                    logger.info(f"Encryption key deleted from {storage_node_url}")
                    return True
                else:
                    logger.warning(f"Failed to delete key: HTTP {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to delete encryption key {key_fragment_id}: {e}")
            return False


# Global key storage manager instance
_key_storage_instance = None

def get_key_storage_manager() -> KeyStorageManager:
    """
    Get the global key storage manager instance.
    Uses singleton pattern for consistent access.
    """
    global _key_storage_instance
    if _key_storage_instance is None:
        _key_storage_instance = KeyStorageManager()
    return _key_storage_instance