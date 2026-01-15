"""
Erasure Coding utilities for distributed file storage.
Uses Reed-Solomon encoding with the reedsolo library for fault tolerance and data redundancy.
"""

import reedsolo
from typing import List, Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

MASTER_NODE_URL = os.getenv("MASTER_NODE_URL", "http://localhost:8000")

class ErasureCoder:
    """Handles erasure coding operations using Reed-Solomon encoding."""
    
    def __init__(self, k: int, m: int):
        """
        Initialize erasure coder with Reed-Solomon parameters.
        
        Args:
            k: Number of data fragments
            m: Number of parity fragments
        """
        self.k = k
        self.m = m
        self.n = k + m
        
        # Initialize reedsolo Reed-Solomon encoder with m parity symbols
        self.rs = reedsolo.RSCodec(m)
        
        logger.info(f"Initialized Reed-Solomon encoder: {k} data + {m} parity = {self.n} fragments")
    
    def encode_data(self, data: bytes) -> List[bytes]:
        """
        Encode data into k+m fragments using Reed-Solomon erasure coding.
        
        Args:
            data: Input data to encode
            
        Returns:
            List of n fragments where first k are data and last m are parity
        """
        try:
            if len(data) == 0:
                raise ValueError("Cannot encode empty data")
            
            # Calculate chunk size and pad data to be divisible by k
            data_size = len(data)
            chunk_size = (data_size + self.k - 1) // self.k
            padded_size = chunk_size * self.k
            padded_data = data + b'\x00' * (padded_size - data_size)
            
            # Split into k data chunks
            data_chunks = [padded_data[i*chunk_size:(i+1)*chunk_size] for i in range(self.k)]
            
            # Create n fragments (k data + m parity)
            fragments = [bytearray(chunk_size) for _ in range(self.n)]
            
            # Encode each byte position using Reed-Solomon
            for byte_pos in range(chunk_size):
                # Collect this byte from each k data chunks
                data_bytes = bytes([data_chunks[i][byte_pos] for i in range(self.k)])
                
                # Encode with reedsolo (adds m parity bytes)
                encoded_bytes = self.rs.encode(data_bytes)
                
                # Distribute across fragments
                for i in range(self.n):
                    fragments[i][byte_pos] = encoded_bytes[i]
            
            all_fragments = [bytes(frag) for frag in fragments]
            logger.info(f"Encoded {data_size} bytes into {self.n} fragments of {chunk_size} bytes each")
            
            return all_fragments
            
        except Exception as e:
            logger.error(f"Reed-Solomon encoding failed: {e}")
            raise
    
    def decode_data(self, available_fragments: List[bytes], fragment_indexes: List[int]) -> bytes:
        """
        Decode data from available Reed-Solomon encoded fragments.
        
        Args:
            available_fragments: List of available fragment data
            fragment_indexes: Corresponding fragment indexes (0-based)
            
        Returns:
            Reconstructed original data
        """
        try:
            if len(available_fragments) < self.k:
                raise ValueError(f"Need at least {self.k} fragments to decode, got {len(available_fragments)}")
            
            # Sort fragments by index
            indexed_fragments = list(zip(fragment_indexes, available_fragments))
            indexed_fragments.sort(key=lambda x: x[0])
            
            # Create full fragment array with None for missing fragments
            all_fragments = [None] * self.n
            for idx, frag in indexed_fragments:
                all_fragments[idx] = frag
            
            # Determine which fragments are missing
            missing_indexes = [i for i in range(self.n) if all_fragments[i] is None]
            
            # Get chunk size
            chunk_size = len(available_fragments[0])
            
            # Reconstruct data chunk-by-chunk using Reed-Solomon
            # Create k bytearrays to hold each data chunk
            reconstructed_chunks = [bytearray(chunk_size) for _ in range(self.k)]
            
            for byte_pos in range(chunk_size):
                # Extract this byte from all fragments
                encoded_bytes = bytearray(self.n)
                for i in range(self.n):
                    if all_fragments[i] is not None:
                        encoded_bytes[i] = all_fragments[i][byte_pos]
                    else:
                        encoded_bytes[i] = 0
                
                # Decode with erasure positions
                decoded_result = self.rs.decode(bytes(encoded_bytes), erase_pos=missing_indexes)
                
                # Handle tuple return value from reedsolo
                decoded_bytes = decoded_result[0] if isinstance(decoded_result, tuple) else decoded_result
                
                # Distribute each decoded byte to its corresponding chunk at this position
                for chunk_idx in range(self.k):
                    reconstructed_chunks[chunk_idx][byte_pos] = decoded_bytes[chunk_idx]
            
            # Concatenate all chunks and convert to bytes
            reconstructed_data = b''.join(bytes(chunk) for chunk in reconstructed_chunks)
            logger.debug(f"Decoded {len(reconstructed_data)} bytes from {len(available_fragments)} fragments")
            
            return reconstructed_data
            
        except Exception as e:
            logger.error(f"Reed-Solomon decoding failed: {e}")
            raise
    
    def can_reconstruct(self, num_available_fragments: int) -> bool:
        """
        Check if data can be reconstructed from available fragments.
        
        Args:
            num_available_fragments: Number of available fragments
            
        Returns:
            True if reconstruction is possible
        """
        return num_available_fragments >= self.k
    
    def get_fragment_info(self) -> Dict[str, Any]:
        """Get information about the erasure coding configuration."""
        return {
            "k": self.k,
            "m": self.m, 
            "n": self.n,
            "min_fragments_needed": self.k,
            "fault_tolerance": self.m,
            "redundancy_ratio": self.m / self.k,
            "storage_overhead": (self.n / self.k) - 1,
            "encoding_type": "Reed-Solomon (reedsolo)"
        }

def get_erasure_profile_from_master(profile_id: str) -> Dict[str, Any]:
    """
    Get erasure profile configuration from master node.
    
    Args:
        profile_id: Erasure profile identifier (LOW, MEDIUM, HIGH)
        
    Returns:
        Profile configuration dictionary
    """
    try:
        response = requests.get(f"{MASTER_NODE_URL}/erasure-profiles/{profile_id}")
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Failed to get erasure profile {profile_id} from master node: {response.status_code}")
            # Fallback to hardcoded values
            return get_fallback_profile(profile_id)
    except Exception as e:
        logger.warning(f"Error connecting to master node for profile {profile_id}: {e}")
        return get_fallback_profile(profile_id)

def get_fallback_profile(profile_id: str) -> Dict[str, Any]:
    """Fallback hardcoded profiles if master node is unavailable."""
    # These values should match what the master node returns from database
    profiles = {
        'LOW': {'k': 6, 'm': 1, 'erasure_id': 'LOW'},      # Database: k=6, m=1
        'MEDIUM': {'k': 5, 'm': 2, 'erasure_id': 'MEDIUM'},  # Database: k=5, m=2
        'HIGH': {'k': 4, 'm': 3, 'erasure_id': 'HIGH'}       # Database: k=3, m=3
    }
    
    if profile_id not in profiles:
        raise ValueError(f"Unknown erasure profile: {profile_id}")
    
    return profiles[profile_id]

def get_account_erasure_preference_from_master(account_id: str) -> str:
    """
    Get account's erasure preference from master node.
    
    Args:
        account_id: Account UUID
        
    Returns:
        Erasure profile ID (defaults to MEDIUM if not found)
    """
    try:
        # Query master node for account erasure preference
        response = requests.post(f"{MASTER_NODE_URL}/query", json={
            "sql": "SELECT erasure_id FROM account_erasure WHERE account_id = $1",
            "params": [account_id]
        })
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success") and result.get("data") and len(result.get("data")) > 0:
                return result["data"][0]["erasure_id"]
        
        # Default to MEDIUM if no preference found
        logger.info(f"No erasure preference found for account {account_id}, defaulting to MEDIUM")
        return 'MEDIUM'
        
    except Exception as e:
        logger.warning(f"Error getting account erasure preference: {e}, defaulting to MEDIUM")
        return 'MEDIUM'

def get_erasure_coder_for_account(account_id: str) -> ErasureCoder:
    """
    Factory function to create erasure coder based on account's preferred profile from master node.
    
    Args:
        account_id: Account UUID
        
    Returns:
        Configured ErasureCoder instance
    """
    try:
        # Get account's erasure preference from master node
        profile_id = get_account_erasure_preference_from_master(account_id)
        
        # Get the profile configuration from master node
        profile_config = get_erasure_profile_from_master(profile_id)
        
        logger.info(f"Using erasure profile {profile_id} (k={profile_config['k']}, m={profile_config['m']}) for account {account_id}")
        return ErasureCoder(k=profile_config['k'], m=profile_config['m'])
        
    except Exception as e:
        logger.error(f"Failed to get erasure profile for account {account_id}: {e}")
        # Fallback to MEDIUM profile
        logger.info("Falling back to MEDIUM profile")
        fallback_config = get_fallback_profile('MEDIUM')
        return ErasureCoder(k=fallback_config['k'], m=fallback_config['m'])

def get_erasure_coder_for_profile(profile_id: str) -> ErasureCoder:
    """
    Factory function to create erasure coder based on profile ID from master node.
    
    Args:
        profile_id: Erasure profile identifier (LOW, MEDIUM, HIGH)
        
    Returns:
        Configured ErasureCoder instance
    """
    try:
        # Get the profile configuration from master node
        profile_config = get_erasure_profile_from_master(profile_id)
        
        logger.info(f"Using erasure profile {profile_id} (k={profile_config['k']}, m={profile_config['m']})")
        return ErasureCoder(k=profile_config['k'], m=profile_config['m'])
        
    except Exception as e:
        logger.error(f"Failed to get erasure profile {profile_id}: {e}")
        # Fallback to hardcoded values
        fallback_config = get_fallback_profile(profile_id)
        logger.info(f"Using fallback profile {profile_id} (k={fallback_config['k']}, m={fallback_config['m']})")
        return ErasureCoder(k=fallback_config['k'], m=fallback_config['m'])