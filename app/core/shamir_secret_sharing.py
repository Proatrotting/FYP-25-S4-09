"""
Shamir's Secret Sharing implementation for distributed key management.

This module implements Shamir's Secret Sharing scheme to split encryption keys
into multiple shares distributed across storage nodes. The key can be reconstructed
from a threshold number of shares, providing fault tolerance and security.
"""

import secrets
import logging
from typing import List, Tuple
from functools import reduce

logger = logging.getLogger(__name__)


class ShamirSecretSharing:
    """
    Implementation of Shamir's (k, n) threshold secret sharing scheme.
    
    A secret is split into n shares, where any k shares can reconstruct the secret,
    but k-1 or fewer shares reveal nothing about the secret.
    """
    
    # Use a large prime number for finite field arithmetic
    # This prime is larger than 2^256 to support 256-bit AES keys
    PRIME = 2**521 - 1  # Mersenne prime (19th Mersenne prime)
    
    def __init__(self, threshold: int, num_shares: int):
        """
        Initialize Shamir's Secret Sharing.
        
        Args:
            threshold: Minimum number of shares needed to reconstruct secret (k)
            num_shares: Total number of shares to generate (n)
        """
        if threshold > num_shares:
            raise ValueError(f"Threshold ({threshold}) cannot exceed num_shares ({num_shares})")
        if threshold < 2:
            raise ValueError(f"Threshold must be at least 2, got {threshold}")
        if num_shares < 2:
            raise ValueError(f"num_shares must be at least 2, got {num_shares}")
            
        self.threshold = threshold
        self.num_shares = num_shares
        logger.info(f"Initialized Shamir Secret Sharing: {threshold}-of-{num_shares} threshold scheme")
    
    def _mod_inverse(self, a: int, m: int) -> int:
        """
        Compute modular multiplicative inverse of a modulo m using Extended Euclidean Algorithm.
        """
        if a < 0:
            a = (a % m + m) % m
            
        g, x, _ = self._extended_gcd(a, m)
        if g != 1:
            raise ValueError(f"Modular inverse does not exist for {a} mod {m}")
        return x % m
    
    def _extended_gcd(self, a: int, b: int) -> Tuple[int, int, int]:
        """
        Extended Euclidean Algorithm.
        Returns (gcd, x, y) such that a*x + b*y = gcd(a, b)
        """
        if a == 0:
            return b, 0, 1
        gcd, x1, y1 = self._extended_gcd(b % a, a)
        x = y1 - (b // a) * x1
        y = x1
        return gcd, x, y
    
    def _eval_polynomial(self, coefficients: List[int], x: int) -> int:
        """
        Evaluate polynomial at point x using Horner's method.
        P(x) = a0 + a1*x + a2*x^2 + ... + an*x^n
        """
        result = 0
        for coeff in reversed(coefficients):
            result = (result * x + coeff) % self.PRIME
        return result
    
    def _lagrange_interpolation(self, shares: List[Tuple[int, int]]) -> int:
        """
        Reconstruct secret using Lagrange interpolation at x=0.
        
        Args:
            shares: List of (x, y) coordinate pairs
            
        Returns:
            The secret value (polynomial evaluated at x=0)
        """
        if len(shares) < self.threshold:
            raise ValueError(f"Need at least {self.threshold} shares, got {len(shares)}")
        
        # Use only threshold number of shares
        shares = shares[:self.threshold]
        
        secret = 0
        x_coords = [share[0] for share in shares]
        
        for i, (x_i, y_i) in enumerate(shares):
            # Compute Lagrange basis polynomial L_i(0)
            numerator = 1
            denominator = 1
            
            for j, x_j in enumerate(x_coords):
                if i != j:
                    numerator = (numerator * (0 - x_j)) % self.PRIME
                    denominator = (denominator * (x_i - x_j)) % self.PRIME
            
            # Compute L_i(0) * y_i
            lagrange_coeff = (numerator * self._mod_inverse(denominator, self.PRIME)) % self.PRIME
            secret = (secret + y_i * lagrange_coeff) % self.PRIME
        
        return secret % self.PRIME
    
    def split_secret(self, secret: bytes) -> List[Tuple[int, bytes]]:
        """
        Split a secret into shares using Shamir's Secret Sharing.
        
        Args:
            secret: The secret data to split (e.g., encryption key)
            
        Returns:
            List of (share_index, share_data) tuples
        """
        # Convert secret bytes to integer
        secret_int = int.from_bytes(secret, byteorder='big')
        
        if secret_int >= self.PRIME:
            raise ValueError(f"Secret is too large for the finite field (max {self.PRIME.bit_length()} bits)")
        
        # Generate random polynomial coefficients
        # P(x) = secret + a1*x + a2*x^2 + ... + a(k-1)*x^(k-1)
        coefficients = [secret_int] + [
            secrets.randbelow(self.PRIME) for _ in range(self.threshold - 1)
        ]
        
        # Evaluate polynomial at different points to create shares
        shares = []
        for i in range(1, self.num_shares + 1):
            x = i
            y = self._eval_polynomial(coefficients, x)
            
            # Convert y to bytes
            y_bytes = y.to_bytes((y.bit_length() + 7) // 8, byteorder='big')
            shares.append((x, y_bytes))
        
        logger.info(f"Split {len(secret)} byte secret into {len(shares)} shares")
        return shares
    
    def reconstruct_secret(self, shares: List[Tuple[int, bytes]], secret_length: int) -> bytes:
        """
        Reconstruct secret from shares using Lagrange interpolation.
        
        Args:
            shares: List of (share_index, share_data) tuples
            secret_length: Expected length of the reconstructed secret in bytes
            
        Returns:
            The reconstructed secret
        """
        if len(shares) < self.threshold:
            raise ValueError(f"Need at least {self.threshold} shares to reconstruct, got {len(shares)}")
        
        # Convert share bytes to integers
        int_shares = []
        for x, y_bytes in shares:
            y = int.from_bytes(y_bytes, byteorder='big')
            int_shares.append((x, y))
        
        # Reconstruct secret using Lagrange interpolation
        secret_int = self._lagrange_interpolation(int_shares)
        
        # Convert back to bytes
        secret = secret_int.to_bytes(secret_length, byteorder='big')
        
        logger.info(f"Reconstructed {len(secret)} byte secret from {len(shares)} shares")
        return secret


def get_sss_config() -> Tuple[int, int]:
    """
    Get Shamir Secret Sharing configuration.
    
    Returns:
        Tuple of (threshold, num_shares)
    """
    # Configuration: 5-of-7 scheme
    # Any 5 shares out of 7 can reconstruct the key
    # Provides tolerance for 2 node failures
    threshold = 5
    num_shares = 7
    return threshold, num_shares


def create_key_shares(encryption_key: bytes) -> List[Tuple[int, bytes]]:
    """
    Split an encryption key into shares.
    
    Args:
        encryption_key: The encryption key to split
        
    Returns:
        List of (share_index, share_data) tuples
    """
    threshold, num_shares = get_sss_config()
    sss = ShamirSecretSharing(threshold, num_shares)
    return sss.split_secret(encryption_key)


def reconstruct_key_from_shares(shares: List[Tuple[int, bytes]], key_length: int = 32) -> bytes:
    """
    Reconstruct encryption key from shares.
    
    Args:
        shares: List of (share_index, share_data) tuples
        key_length: Expected key length in bytes (default 32 for AES-256)
        
    Returns:
        The reconstructed encryption key
    """
    threshold, num_shares = get_sss_config()
    sss = ShamirSecretSharing(threshold, num_shares)
    return sss.reconstruct_secret(shares, key_length)


# Singleton instance
_sss_instance = None


def get_shamir_secret_sharing() -> ShamirSecretSharing:
    """
    Get the global Shamir Secret Sharing instance.
    """
    global _sss_instance
    if _sss_instance is None:
        threshold, num_shares = get_sss_config()
        _sss_instance = ShamirSecretSharing(threshold, num_shares)
    return _sss_instance
