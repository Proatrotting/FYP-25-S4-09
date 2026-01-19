"""
AES-256 File Encryption Module

This module provides AES-256-GCM encryption/decryption functionality for the distributed file storage system.
Encryption is applied before erasure coding during upload, and decryption after reconstruction during download.

Security Features:
- AES-256-GCM encryption (Authenticated encryption with associated data)
- Randomly generated 12-byte nonces for each encryption operation
- Key derivation from account-specific master key using PBKDF2
- Integrated authentication to prevent tampering
"""

import os
import base64
import hashlib
import logging
from typing import Tuple, Optional, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

class FileEncryption:
    """
    Handles AES-256-GCM encryption and decryption for file data.
    Each account has a unique encryption key derived from a master key.
    """
    
    # Class variables to ensure consistent master key across instances
    _master_key = None
    _initialized = False
    
    # AES-256 requires 32-byte keys
    KEY_SIZE = 32
    # GCM nonce size (12 bytes is recommended for GCM)
    NONCE_SIZE = 12
    # PBKDF2 iterations (100,000 is recommended minimum)
    PBKDF2_ITERATIONS = 100000
    
    def __init__(self):
        """Initialize the encryption handler."""
        if not FileEncryption._initialized:
            FileEncryption._master_key = self._get_or_create_master_key()
            FileEncryption._initialized = True
    
    def _get_or_create_master_key(self) -> bytes:
        """
        Get master encryption key from environment or create a new one.
        In production, this should be stored securely (e.g., HSM, key vault).
        """
        # Try to get from environment first
        master_key_b64 = os.getenv("MASTER_ENCRYPTION_KEY")
        
        if master_key_b64:
            try:
                master_key = base64.b64decode(master_key_b64)
                if len(master_key) == self.KEY_SIZE:
                    logger.info("Using master encryption key from environment")
                    return master_key
                else:
                    logger.warning("Invalid master key size in environment, generating new key")
            except Exception as e:
                logger.warning(f"Failed to decode master key from environment: {e}")
        
        # Generate new master key
        master_key = os.urandom(self.KEY_SIZE)
        master_key_b64 = base64.b64encode(master_key).decode()
        
        logger.warning(
            "Generated new master encryption key. In production, set MASTER_ENCRYPTION_KEY environment variable:\n"
            f"MASTER_ENCRYPTION_KEY={master_key_b64}"
        )
        
        return master_key

    def generate_file_key(self) -> bytes:
        """
        Generate a unique 256-bit encryption key for a single file.
        Each file gets its own unique key for improved security.
        """
        return os.urandom(self.KEY_SIZE)
    
    def key_to_string(self, key: bytes) -> str:
        """
        Convert encryption key to base64 string for storage.
        """
        return base64.b64encode(key).decode('utf-8')
    
    def key_from_string(self, key_str: str) -> bytes:
        """
        Convert base64 string back to encryption key bytes.
        """
        return base64.b64decode(key_str)
    
    def _derive_account_key(self, account_id: str) -> bytes:
        """
        Derive a unique encryption key for an account using PBKDF2.
        
        Args:
            account_id: Unique account identifier
            
        Returns:
            32-byte encryption key specific to the account
        """
        # Use account ID as salt for key derivation
        salt = account_id.encode('utf-8')
        
        # Ensure salt is at least 16 bytes for security
        if len(salt) < 16:
            salt = salt + b'\x00' * (16 - len(salt))
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_SIZE,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
            backend=default_backend()
        )
        
        return kdf.derive(FileEncryption._master_key)
    
    def encrypt_file_data(self, data: bytes, account_id: str, additional_data: Optional[Dict] = None, file_key: Optional[bytes] = None) -> Tuple[bytes, str, bytes]:
        """
        Encrypt file data using AES-256-GCM with per-file key.
        
        Args:
            data: Raw file data to encrypt
            account_id: Account ID for additional authentication data
            additional_data: Optional metadata to include in authentication
            file_key: Optional pre-generated file key (if None, generates new one)
            
        Returns:
            Tuple of (encrypted_data_with_nonce, encryption_metadata_json, file_key)
            
        The encrypted data format:
        [12-byte nonce][encrypted_data][16-byte auth_tag]
        """
        try:
            # Generate or use provided file-specific key
            if file_key is None:
                file_key = self.generate_file_key()
            
            # Generate random nonce
            nonce = os.urandom(self.NONCE_SIZE)
            
            # Initialize AES-GCM
            aesgcm = AESGCM(file_key)
            
            # Prepare associated data (for authentication, not encrypted)
            aad = self._prepare_associated_data(account_id, additional_data)
            
            # Encrypt data
            encrypted_data = aesgcm.encrypt(nonce, data, aad)
            
            # Combine nonce + encrypted data + auth tag
            # (aesgcm.encrypt already includes the auth tag in the returned data)
            final_encrypted_data = nonce + encrypted_data
            
            # Create metadata
            encryption_metadata = {
                "algorithm": "AES-256-GCM",
                "nonce_size": self.NONCE_SIZE,
                "key_derivation": "PBKDF2-SHA256",
                "iterations": self.PBKDF2_ITERATIONS,
                "encrypted_size": len(final_encrypted_data),
                "original_size": len(data),
                "additional_data": additional_data  # Store AAD for decryption
            }
            
            logger.info(f"File encrypted successfully: {len(data)} -> {len(final_encrypted_data)} bytes")
            
            # Return metadata as JSON string along with the file key
            import json
            return final_encrypted_data, json.dumps(encryption_metadata), file_key
            
        except Exception as e:
            logger.error(f"Encryption failed for account {account_id}: {e}")
            raise RuntimeError(f"File encryption failed: {str(e)}")
    
    def decrypt_file_data(self, encrypted_data: bytes, account_id: str, encryption_metadata: Optional[str] = None, file_info: Optional[dict] = None, file_key: Optional[bytes] = None) -> bytes:
        """
        Decrypt file data using AES-256-GCM with provided file key.
        
        Args:
            encrypted_data: Encrypted data (nonce + ciphertext + auth_tag)
            account_id: Account ID for additional authentication data
            encryption_metadata: JSON string containing encryption metadata including additional_data
            file_info: Optional file info dictionary to reconstruct additional_data if missing
            file_key: The specific file encryption key (required for decryption)
            
        Returns:
            Decrypted original file data
        """
        try:
            if file_key is None:
                # Backwards compatibility: derive key from account for old files
                logger.info("Using backwards compatibility: deriving key from account")
                file_key = self._derive_account_key(account_id)
                
            if len(encrypted_data) < self.NONCE_SIZE + 16:  # nonce + minimum auth tag
                raise ValueError("Encrypted data too short to be valid")
            
            # Extract nonce and ciphertext
            nonce = encrypted_data[:self.NONCE_SIZE]
            ciphertext_with_tag = encrypted_data[self.NONCE_SIZE:]
            
            # Initialize AES-GCM with the provided file key
            aesgcm = AESGCM(file_key)
            
            # Prepare associated data (must match what was used during encryption)
            additional_data = None
            if encryption_metadata:
                try:
                    import json
                    metadata_dict = json.loads(encryption_metadata) if isinstance(encryption_metadata, str) else encryption_metadata
                    additional_data = metadata_dict.get("additional_data")
                except Exception as e:
                    logger.warning(f"Failed to parse encryption metadata: {e}")
            
            # If additional_data is missing from metadata but we have file_info,
            # reconstruct it as it would have been during encryption (backwards compatibility)
            if additional_data is None and file_info:
                try:
                    additional_data = {
                        "filename": file_info.get("file_name"),
                        "content_type": "application/octet-stream",  # Default content type used during upload
                        "original_hash": file_info.get("original_file_hash")
                    }
                    logger.info(f"Using backwards compatibility for decryption")
                except Exception as e:
                    logger.warning(f"Failed to reconstruct additional_data: {e}")
            
            aad = self._prepare_associated_data(account_id, additional_data)
            
            # Decrypt data
            decrypted_data = aesgcm.decrypt(nonce, ciphertext_with_tag, aad)
            
            logger.info(f"File decrypted successfully: {len(encrypted_data)} -> {len(decrypted_data)} bytes")
            
            return decrypted_data
            
        except Exception as e:
            logger.error(f"Decryption failed for account {account_id}: {e}")
            raise RuntimeError(f"File decryption failed: {str(e)}")
    
    def _prepare_associated_data(self, account_id: str, additional_data: Optional[Dict] = None) -> bytes:
        """
        Prepare associated data for GCM authentication.
        This data is authenticated but not encrypted.
        
        Args:
            account_id: Account identifier
            additional_data: Optional additional authenticated data
            
        Returns:
            AAD bytes for GCM
        """
        aad_dict = {
            "account_id": account_id,
            "version": "1.0"
        }
        
        if additional_data:
            aad_dict.update(additional_data)
        
        # Create deterministic AAD string
        aad_str = "|".join(f"{k}:{v}" for k, v in sorted(aad_dict.items()))
        return aad_str.encode('utf-8')


# Global encryption instance
_encryption_instance = None

def get_file_encryption() -> FileEncryption:
    """
    Get the global file encryption instance.
    Uses singleton pattern to ensure consistent key derivation.
    """
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = FileEncryption()
    return _encryption_instance


def encrypt_file_data(data: bytes, account_id: str, additional_data: Optional[Dict] = None, file_key: Optional[bytes] = None) -> Tuple[bytes, str, bytes]:
    """
    Convenience function to encrypt file data with per-file key.
    
    Args:
        data: Raw file data to encrypt
        account_id: Account ID for additional authentication data
        additional_data: Optional metadata to include in authentication
        file_key: Optional pre-generated file key
        
    Returns:
        Tuple of (encrypted_data_with_nonce, encryption_metadata_json, file_key)
    """
    encryption = get_file_encryption()
    return encryption.encrypt_file_data(data, account_id, additional_data, file_key)


def decrypt_file_data(encrypted_data: bytes, account_id: str, encryption_metadata: Optional[str] = None, file_info: Optional[dict] = None, file_key: Optional[bytes] = None) -> bytes:
    """
    Convenience function to decrypt file data with provided file key.
    
    Args:
        encrypted_data: Encrypted data (nonce + ciphertext + auth_tag)
        account_id: Account ID for additional authentication data
        encryption_metadata: Optional metadata from encryption
        file_info: Optional file info to reconstruct additional_data if missing
        file_key: The specific file encryption key (required)
        
    Returns:
        Decrypted original file data
    """
    encryption = get_file_encryption()
    return encryption.decrypt_file_data(encrypted_data, account_id, encryption_metadata, file_info, file_key)


def is_data_encrypted(data: bytes) -> bool:
    """
    Check if data appears to be encrypted based on basic heuristics.
    This is a simple check and not cryptographically reliable.
    
    Args:
        data: Data to check
        
    Returns:
        True if data appears encrypted, False otherwise
    """
    if len(data) < 32:  # Too small to be encrypted with our scheme
        return False
    
    # For our scheme, encrypted data should have high entropy
    # This is a basic entropy check
    byte_counts = [0] * 256
    for byte in data[:min(1024, len(data))]:  # Check first 1KB
        byte_counts[byte] += 1
    
    # Calculate Shannon entropy
    import math
    total_bytes = sum(byte_counts)
    entropy = 0
    for count in byte_counts:
        if count > 0:
            prob = count / total_bytes
            entropy -= prob * math.log2(prob)
    
    # High entropy suggests encryption (> 7.5 bits per byte)
    return entropy > 7.5
