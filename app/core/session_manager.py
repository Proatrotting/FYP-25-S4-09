"""
Session tracking for upload/download operations with cancellation support.
"""

import asyncio
import uuid
import time
import threading
from typing import Dict, Optional, Set, Literal
from dataclasses import dataclass, field
from enum import Enum

class SessionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

class SessionType(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"

@dataclass
class OperationSession:
    session_id: str
    session_type: SessionType
    account_id: str
    file_id: Optional[str] = None
    filename: Optional[str] = None
    total_size: Optional[int] = None
    processed_size: int = 0
    status: SessionStatus = SessionStatus.ACTIVE
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_flag: asyncio.Event = field(default_factory=asyncio.Event)
    
    # Track uploaded fragments for cleanup
    uploaded_fragments: Set[str] = field(default_factory=set)
    fragment_nodes: Dict[str, str] = field(default_factory=dict)  # fragment_id -> node_endpoint
    
    def mark_fragment_uploaded(self, fragment_id: str, node_endpoint: str):
        """Track a successfully uploaded fragment."""
        self.uploaded_fragments.add(fragment_id)
        self.fragment_nodes[fragment_id] = node_endpoint
        self.updated_at = time.time()
    
    def update_progress(self, processed_bytes: int):
        """Update progress information."""
        self.processed_size = processed_bytes
        self.updated_at = time.time()
    
    def cancel(self):
        """Mark session as cancelling and set cancel flag."""
        self.status = SessionStatus.CANCELLING
        self.updated_at = time.time()
        self.cancel_flag.set()
    
    def complete(self):
        """Mark session as completed."""
        self.status = SessionStatus.COMPLETED
        self.updated_at = time.time()
    
    def fail(self):
        """Mark session as failed."""
        self.status = SessionStatus.FAILED
        self.updated_at = time.time()
    
    def is_cancelled(self) -> bool:
        """Check if session is cancelled or cancelling."""
        return self.status in [SessionStatus.CANCELLED, SessionStatus.CANCELLING]

class SessionManager:
    """Manages upload/download sessions with cancellation support."""
    
    def __init__(self):
        self._sessions: Dict[str, OperationSession] = {}
        self._lock = threading.RLock()
        self._cleanup_interval = 3600  # 1 hour
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to clean up old sessions."""
        def cleanup_old_sessions():
            while True:
                try:
                    current_time = time.time()
                    with self._lock:
                        expired_sessions = [
                            session_id for session_id, session in self._sessions.items()
                            if current_time - session.updated_at > self._cleanup_interval
                            and session.status in [SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED]
                        ]
                        for session_id in expired_sessions:
                            del self._sessions[session_id]
                    
                    time.sleep(300)  # Check every 5 minutes
                except Exception:
                    time.sleep(300)
        
        cleanup_thread = threading.Thread(target=cleanup_old_sessions, daemon=True)
        cleanup_thread.start()
    
    def create_session(
        self, 
        session_type: SessionType, 
        account_id: str, 
        filename: Optional[str] = None,
        file_id: Optional[str] = None,
        total_size: Optional[int] = None
    ) -> OperationSession:
        """Create a new operation session."""
        session_id = str(uuid.uuid4())
        session = OperationSession(
            session_id=session_id,
            session_type=session_type,
            account_id=account_id,
            file_id=file_id,
            filename=filename,
            total_size=total_size
        )
        
        with self._lock:
            self._sessions[session_id] = session
        
        return session
    
    def get_session(self, session_id: str) -> Optional[OperationSession]:
        """Get session by ID."""
        with self._lock:
            return self._sessions.get(session_id)
    
    def get_account_sessions(self, account_id: str, session_type: Optional[SessionType] = None) -> Dict[str, OperationSession]:
        """Get all sessions for an account, optionally filtered by type."""
        with self._lock:
            return {
                session_id: session for session_id, session in self._sessions.items()
                if session.account_id == account_id and (
                    session_type is None or session.session_type == session_type
                )
            }
    
    def cancel_session(self, session_id: str, account_id: str) -> bool:
        """Cancel a session if it belongs to the account."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            if session.account_id != account_id:
                return False
            
            if session.status != SessionStatus.ACTIVE:
                return False
            
            session.cancel()
            return True
    
    def remove_session(self, session_id: str):
        """Remove a session from tracking."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

# Global session manager instance
session_manager = SessionManager()