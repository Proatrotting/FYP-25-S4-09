from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
import secrets
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.db.session import get_db
from app.models import Account, FileObject, Folder, FileShare, FolderShare, ShareAccessLog
from app.core.security import decode_access_token, verify_password
from app.core.activity_logger import get_client_ip
from app.routes.login import oauth2_scheme

router = APIRouter(prefix="/shares", tags=["File Sharing"])

# Pydantic models for request/response
class CreateFileShareRequest(BaseModel):
    file_id: str = Field(..., description="UUID of the file to share")
    shared_with_username: Optional[str] = Field(None, description="Username to share with (None for public link)")
    permissions: str = Field("VIEW", description="Share permissions: VIEW or DOWNLOAD")
    expires_hours: Optional[int] = Field(24, description="Hours until link expires (None for no expiration)")
    require_password: bool = Field(True, description="Whether to require a one-time password")

class CreateFolderShareRequest(BaseModel):
    folder_id: str = Field(..., description="UUID of the folder to share")
    shared_with_username: Optional[str] = Field(None, description="Username to share with (None for public link)")
    permissions: str = Field("VIEW", description="Share permissions: VIEW or DOWNLOAD")
    expires_hours: Optional[int] = Field(24, description="Hours until link expires (None for no expiration)")
    require_password: bool = Field(True, description="Whether to require a one-time password")

class ShareResponse(BaseModel):
    share_id: str
    share_token: str
    one_time_password: Optional[str]
    share_url: str
    expires_at: Optional[datetime]
    permissions: str

class AccessShareRequest(BaseModel):
    share_token: str = Field(..., description="Share token")
    password: Optional[str] = Field(None, description="One-time password if required")

class ShareInfo(BaseModel):
    share_id: str
    resource_type: str  # FILE or FOLDER
    resource_name: str

class ShareWithUserRequest(BaseModel):
    file_id: str = Field(..., description="UUID of the file to share")
    username: str = Field(..., description="Username to share with")
    permissions: str = Field("DOWNLOAD", description="Share permissions: VIEW or DOWNLOAD")
    expires_hours: Optional[int] = Field(None, description="Hours until share expires (None for no expiration)")

class SharedWithMeResponse(BaseModel):
    share_id: str
    file_id: str
    file_name: str
    shared_by_username: str
    permissions: str
    shared_at: datetime
    expires_at: Optional[datetime]

class UserSearchResponse(BaseModel):
    username: str
    email: str
    account_type: str
    shared_by_username: str
    permissions: str
    expires_at: Optional[datetime]
    requires_password: bool
    is_expired: bool

def get_current_user_optional(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
) -> Optional[Account]:
    """Get current user if authenticated, otherwise None"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    try:
        token = authorization.split(" ")[1]
        payload = decode_access_token(token)
        if not payload:
            return None
        
        user = db.query(Account).filter(Account.account_id == payload.get("sub")).first()
        return user
    except:
        return None

def get_current_user(
    token=Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Account:
    """Get current authenticated user (required)"""
    try:
        token_str = token.credentials if hasattr(token, "credentials") else token
        payload = decode_access_token(token_str)
        
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        user_id = payload.get("sub")  # Use "sub" which is standard JWT field for user ID
        
        user = db.query(Account).filter(Account.account_id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        return user
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

def generate_share_token() -> str:
    """Generate a secure share token"""
    return secrets.token_urlsafe(32)

def generate_one_time_password() -> str:
    """Generate a secure one-time password"""
    return secrets.token_hex(8)

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def log_share_access(
    db: Session,
    share_id: str,
    share_type: str,
    action: str,
    success: str = "SUCCESS",
    accessed_by: Optional[uuid.UUID] = None,
    request: Optional[Request] = None
):
    """Log share access attempt"""
    ip_address = None
    user_agent = None
    
    if request:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
    
    log_entry = ShareAccessLog(
        share_id=share_id,
        share_type=share_type,
        accessed_by=accessed_by,
        ip_address=ip_address,
        user_agent=user_agent,
        action=action,
        success=success
    )
    
    db.add(log_entry)
    db.commit()

@router.post("/files/create", response_model=ShareResponse)
async def create_file_share(
    request: CreateFileShareRequest,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a shareable link for a file"""
    
    # Verify file exists and belongs to user
    file_obj = db.query(FileObject).filter(
        and_(
            FileObject.file_id == request.file_id,
            FileObject.account_id == current_user.account_id
        )
    ).first()
    
    if not file_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or access denied"
        )
    
    # Resolve shared_with user if specified
    shared_with_id = None
    if request.shared_with_username:
        shared_with_user = db.query(Account).filter(
            Account.username == request.shared_with_username
        ).first()
        
        if not shared_with_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found"
            )
        
        shared_with_id = shared_with_user.account_id
    
    # Generate share token and password
    share_token = generate_share_token()
    one_time_password = None
    password_hash = None
    
    if request.require_password:
        one_time_password = generate_one_time_password()
        password_hash = hash_password(one_time_password)
    
    # Calculate expiration
    expires_at = None
    if request.expires_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=request.expires_hours)
    
    # Create share record
    file_share = FileShare(
        file_id=request.file_id,
        shared_by=current_user.account_id,
        shared_with=shared_with_id,
        share_token=share_token,
        password_hash=password_hash,
        permissions=request.permissions,
        expires_at=expires_at
    )
    
    db.add(file_share)
    db.commit()
    
    # Generate share URL
    share_url = f"/shares/files/access/{share_token}"
    
    return ShareResponse(
        share_id=str(file_share.share_id),
        share_token=share_token,
        one_time_password=one_time_password,
        share_url=share_url,
        expires_at=expires_at,
        permissions=request.permissions
    )

@router.post("/folders/create", response_model=ShareResponse)
async def create_folder_share(
    request: CreateFolderShareRequest,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a shareable link for a folder"""
    
    # Verify folder exists and belongs to user
    folder = db.query(Folder).filter(
        and_(
            Folder.folder_id == request.folder_id,
            Folder.account_id == current_user.account_id
        )
    ).first()
    
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder not found or access denied"
        )
    
    # Resolve shared_with user if specified
    shared_with_id = None
    if request.shared_with_username:
        shared_with_user = db.query(Account).filter(
            Account.username == request.shared_with_username
        ).first()
        
        if not shared_with_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target user not found"
            )
        
        shared_with_id = shared_with_user.account_id
    
    # Generate share token and password
    share_token = generate_share_token()
    one_time_password = None
    password_hash = None
    
    if request.require_password:
        one_time_password = generate_one_time_password()
        password_hash = hash_password(one_time_password)
    
    # Calculate expiration
    expires_at = None
    if request.expires_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=request.expires_hours)
    
    # Create share record
    folder_share = FolderShare(
        folder_id=request.folder_id,
        shared_by=current_user.account_id,
        shared_with=shared_with_id,
        share_token=share_token,
        password_hash=password_hash,
        permissions=request.permissions,
        expires_at=expires_at
    )
    
    db.add(folder_share)
    db.commit()
    
    # Generate share URL
    share_url = f"/shares/folders/access/{share_token}"
    
    return ShareResponse(
        share_id=str(folder_share.share_id),
        share_token=share_token,
        one_time_password=one_time_password,
        share_url=share_url,
        expires_at=expires_at,
        permissions=request.permissions
    )

@router.get("/files/info/{share_token}", response_model=ShareInfo)
async def get_file_share_info(
    share_token: str,
    request: Request,
    current_user: Optional[Account] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Get information about a file share without accessing it"""
    
    # Find the share
    file_share = db.query(FileShare).filter(
        FileShare.share_token == share_token
    ).first()
    
    if not file_share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found"
        )
    
    # Check if expired
    is_expired = False
    if file_share.expires_at and datetime.now(timezone.utc) > file_share.expires_at:
        is_expired = True
    
    if file_share.is_active != "ACTIVE":
        is_expired = True
    
    # Get file and owner info
    file_obj = db.query(FileObject).filter(
        FileObject.file_id == file_share.file_id
    ).first()
    
    shared_by_user = db.query(Account).filter(
        Account.account_id == file_share.shared_by
    ).first()
    
    # Log info access
    log_share_access(
        db=db,
        share_id=str(file_share.share_id),
        share_type="FILE",
        action="VIEW",
        success="SUCCESS",
        accessed_by=current_user.account_id if current_user else None,
        request=request
    )
    
    return ShareInfo(
        share_id=str(file_share.share_id),
        resource_type="FILE",
        resource_name=file_obj.file_name,
        shared_by_username=shared_by_user.username,
        permissions=file_share.permissions,
        expires_at=file_share.expires_at,
        requires_password=bool(file_share.password_hash),
        is_expired=is_expired
    )

@router.get("/folders/info/{share_token}", response_model=ShareInfo)
async def get_folder_share_info(
    share_token: str,
    request: Request,
    current_user: Optional[Account] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Get information about a folder share without accessing it"""
    
    # Find the share
    folder_share = db.query(FolderShare).filter(
        FolderShare.share_token == share_token
    ).first()
    
    if not folder_share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found"
        )
    
    # Check if expired
    is_expired = False
    if folder_share.expires_at and datetime.now(timezone.utc) > folder_share.expires_at:
        is_expired = True
    
    if folder_share.is_active != "ACTIVE":
        is_expired = True
    
    # Get folder and owner info
    folder = db.query(Folder).filter(
        Folder.folder_id == folder_share.folder_id
    ).first()
    
    shared_by_user = db.query(Account).filter(
        Account.account_id == folder_share.shared_by
    ).first()
    
    # Log info access
    log_share_access(
        db=db,
        share_id=str(folder_share.share_id),
        share_type="FOLDER",
        action="VIEW",
        success="SUCCESS",
        accessed_by=current_user.account_id if current_user else None,
        request=request
    )
    
    return ShareInfo(
        share_id=str(folder_share.share_id),
        resource_type="FOLDER",
        resource_name=folder.name,
        shared_by_username=shared_by_user.username,
        permissions=folder_share.permissions,
        expires_at=folder_share.expires_at,
        requires_password=bool(folder_share.password_hash),
        is_expired=is_expired
    )

@router.post("/files/access")
async def access_file_share(
    request_data: AccessShareRequest,
    request: Request,
    current_user: Optional[Account] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Access a shared file with optional password verification"""
    
    # Find the share
    file_share = db.query(FileShare).filter(
        FileShare.share_token == request_data.share_token
    ).first()
    
    if not file_share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found"
        )
    
    # Check if expired
    if file_share.expires_at and datetime.now(timezone.utc) > file_share.expires_at:
        file_share.is_active = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Share has expired"
        )
    
    if file_share.is_active != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Share is no longer active"
        )
    
    # Check password if required
    if file_share.password_hash:
        if not request_data.password:
            log_share_access(
                db=db,
                share_id=str(file_share.share_id),
                share_type="FILE",
                action="PASSWORD_ATTEMPT",
                success="FAILED",
                accessed_by=current_user.account_id if current_user else None,
                request=request
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password required"
            )
        
        if hash_password(request_data.password) != file_share.password_hash:
            log_share_access(
                db=db,
                share_id=str(file_share.share_id),
                share_type="FILE",
                action="PASSWORD_ATTEMPT",
                success="FAILED",
                accessed_by=current_user.account_id if current_user else None,
                request=request
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )
        
        # Mark password as used (one-time use)
        file_share.used_at = datetime.now(timezone.utc)
        file_share.is_active = "EXPIRED"  # Make it one-time use
        db.commit()
    
    # Log successful access
    log_share_access(
        db=db,
        share_id=str(file_share.share_id),
        share_type="FILE",
        action="DOWNLOAD" if file_share.permissions == "DOWNLOAD" else "VIEW",
        success="SUCCESS",
        accessed_by=current_user.account_id if current_user else None,
        request=request
    )
    
    # Get file info
    file_obj = db.query(FileObject).filter(
        FileObject.file_id == file_share.file_id
    ).first()
    
    if file_share.permissions == "DOWNLOAD":
        # Return download URL or file content
        return {
            "message": "Access granted",
            "permissions": file_share.permissions,
            "file_id": str(file_share.file_id),
            "file_name": file_obj.file_name,
            "download_url": f"http://localhost:8004/shares/files/shared-download/{request_data.share_token}?password={request_data.password or ''}"
        }
    else:
        # Return file metadata only
        return {
            "message": "Access granted",
            "permissions": file_share.permissions,
            "file_name": file_obj.file_name,
            "file_size": file_obj.file_size,
            "uploaded_at": file_obj.uploaded_at
        }

@router.get("/my-shares", response_model=List[ShareInfo])
async def get_my_shares(
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all shares created by the current user"""
    
    shares = []
    
    # Get file shares
    file_shares = db.query(FileShare).filter(
        FileShare.shared_by == current_user.account_id
    ).all()
    
    for share in file_shares:
        file_obj = db.query(FileObject).filter(
            FileObject.file_id == share.file_id
        ).first()
        
        is_expired = False
        if share.expires_at and datetime.now(timezone.utc) > share.expires_at:
            is_expired = True
        if share.is_active != "ACTIVE":
            is_expired = True
            
        shares.append(ShareInfo(
            share_id=str(share.share_id),
            resource_type="FILE",
            resource_name=file_obj.file_name,
            shared_by_username=current_user.username,
            permissions=share.permissions,
            expires_at=share.expires_at,
            requires_password=bool(share.password_hash),
            is_expired=is_expired
        ))
    
    # Get folder shares
    folder_shares = db.query(FolderShare).filter(
        FolderShare.shared_by == current_user.account_id
    ).all()
    
    for share in folder_shares:
        folder = db.query(Folder).filter(
            Folder.folder_id == share.folder_id
        ).first()
        
        is_expired = False
        if share.expires_at and datetime.now(timezone.utc) > share.expires_at:
            is_expired = True
        if share.is_active != "ACTIVE":
            is_expired = True
            
        shares.append(ShareInfo(
            share_id=str(share.share_id),
            resource_type="FOLDER",
            resource_name=folder.name,
            shared_by_username=current_user.username,
            permissions=share.permissions,
            expires_at=share.expires_at,
            requires_password=bool(share.password_hash),
            is_expired=is_expired
        ))
    
    return shares

@router.delete("/revoke/{share_id}")
async def revoke_share(
    share_id: str,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Revoke a share (file or folder)"""
    
    # Try to find in file shares first
    file_share = db.query(FileShare).filter(
        and_(
            FileShare.share_id == share_id,
            FileShare.shared_by == current_user.account_id
        )
    ).first()
    
    if file_share:
        file_share.is_active = "REVOKED"
        db.commit()
        return {"message": "File share revoked successfully"}
    
    # Try folder shares
    folder_share = db.query(FolderShare).filter(
        and_(
            FolderShare.share_id == share_id,
            FolderShare.shared_by == current_user.account_id
        )
    ).first()
    
    if folder_share:
        folder_share.is_active = "REVOKED"
        db.commit()
        return {"message": "Folder share revoked successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Share not found or access denied"
    )

@router.get("/files/preview/{file_id}")
async def preview_own_file(
    file_id: str,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Preview a file owned by the current user.
    """
    # Ensure ownership
    file_obj = db.query(FileObject).filter(
        FileObject.file_id == file_id,
        FileObject.account_id == current_user.account_id,
    ).first()
    if not file_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found or not owned by user",
        )

    data, file_obj = await reconstruct_file_for_owner(file_id, db)

    async def generate():
        yield data  # simple one-shot streaming

    return StreamingResponse(
        generate(),
        media_type=file_obj.content_type or "application/octet-stream",
    )

@router.get("/files/shared-download/{share_token}")
async def download_shared_file(
    share_token: str,
    password: str = None,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Download a file using share token (no authentication required)"""
    import httpx
    from fastapi.responses import StreamingResponse
    
    # Find the share
    file_share = db.query(FileShare).filter(
        FileShare.share_token == share_token,
        FileShare.is_active == "ACTIVE"
    ).first()
    
    if not file_share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share not found"
        )
    
    # Check if share is expired
    if file_share.expires_at and file_share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Share has expired"
        )
    
    # Check password if required
    if file_share.password_hash:
        if not password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password required"
            )
        
        if not verify_password(password, file_share.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )
    
    # Check permissions
    if file_share.permissions not in ["DOWNLOAD"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download permission not granted"
        )
    
    # Get file info
    file_obj = db.query(FileObject).filter(FileObject.file_id == file_share.file_id).first()
    if not file_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Log the access
    log_share_access(
        db=db,
        share_id=file_share.share_id,
        share_type="FILE",
        action="DOWNLOAD",
        request=request
    )
    
    # Update used_at timestamp
    file_share.used_at = datetime.now(timezone.utc)
    db.commit()
    
    # Get file from master node/storage system
    try:
        master_node_url = "http://master_node:3000"
        
        # Get file info to verify it exists
        async with httpx.AsyncClient() as client:
            file_info_response = await client.get(f"{master_node_url}/files/info/{file_share.file_id}")
            
            if file_info_response.status_code == 404:
                raise HTTPException(status_code=404, detail="File not found in storage")
            
            if file_info_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to retrieve file info: {file_info_response.text}"
                )
            
            file_info = file_info_response.json()["file"]
            
            # Get fragment information
            fragments_response = await client.get(f"{master_node_url}/fragments/{file_share.file_id}")
            
            if fragments_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to retrieve fragments: {fragments_response.text}"
                )
            
            fragments = fragments_response.json()
            
            if not fragments:
                raise HTTPException(status_code=404, detail="File fragments not found")
            
            # Import the necessary modules for file reconstruction
            from app.core.erasure_coding import get_erasure_coder_for_profile
            import logging
            import base64
            
            logger = logging.getLogger(__name__)
            
            # Initialize erasure decoder
            try:
                erasure_coder = get_erasure_coder_for_profile(file_info["erasure_id"])
                logger.info(f"Using Reed-Solomon profile {file_info['erasure_id']} for shared download")
            except Exception as e:
                logger.error(f"Failed to initialize erasure decoder: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to initialize erasure decoder: {str(e)}"
                )
            
            # Reconstruct the file content using Reed-Solomon decoding
            try:
                # Sort fragments by fragment number
                sorted_fragments = sorted(fragments, key=lambda x: x["num_fragment"])
                available_fragments = []
                fragment_indexes = []
                
                # Fetch fragment data from storage nodes
                for fragment in sorted_fragments:
                    fragment_url = None  # Initialize fragment_url
                    try:
                        if not fragment.get("fragment_id") or not fragment.get("api_endpoint"):
                            logger.warning(f"Fragment missing required fields: {fragment}")
                            continue
                        
                        # Use internal Docker network addresses for storage nodes
                        node_endpoint = fragment["api_endpoint"]
                        # Since we're running inside Docker, use the internal network address directly
                        storage_url = node_endpoint
                        
                        # Request fragment data from storage node (same pattern as download_files.py)
                        fragment_url = f"{storage_url}/fragments/{fragment['fragment_id']}"
                        
                        logger.info(f"Requesting fragment {fragment['num_fragment']} from {fragment_url}")
                        
                        frag_response = await client.get(fragment_url, timeout=30)
                        
                        if frag_response.status_code == 200:
                            # Parse JSON response from storage node
                            fragment_data = frag_response.json()
                            if fragment_data.get("success") and fragment_data.get("data"):
                                # Decode base64 fragment data
                                decoded_data = base64.b64decode(fragment_data["data"])
                                available_fragments.append(decoded_data)
                                fragment_indexes.append(fragment["num_fragment"])
                                logger.info(f"Successfully retrieved fragment {fragment['num_fragment']} ({len(decoded_data)} bytes)")
                            else:
                                logger.warning(f"Storage node returned empty data for fragment {fragment['fragment_id']}: {fragment_data}")
                        else:
                            logger.warning(f"Storage node failed to retrieve fragment {fragment['fragment_id']}: {frag_response.status_code} - {frag_response.text}")
                    except Exception as e:
                        if fragment_url:
                            logger.warning(f"Failed to fetch fragment {fragment['fragment_id']} from {fragment_url}: {e}")
                        else:
                            logger.warning(f"Failed to process fragment {fragment.get('fragment_id', 'unknown')}: {e}")
                        continue
                
                # Check if we have enough fragments for reconstruction
                logger.info(f"Retrieved {len(available_fragments)} fragments out of {len(sorted_fragments)} total fragments")
                logger.info(f"Fragment indexes: {fragment_indexes}")
                
                if not erasure_coder.can_reconstruct(len(available_fragments)):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Not enough fragments for reconstruction. Need {erasure_coder.k}, got {len(available_fragments)}"
                    )
                
                # Reconstruct original file using Reed-Solomon decoding
                reconstructed_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
                
                # Truncate to original file size to remove any padding artifacts
                original_file_size = int(file_info["file_size"])
                if len(reconstructed_data) > original_file_size:
                    reconstructed_data = reconstructed_data[:original_file_size]
                    logger.info(f"Truncated reconstructed data to original size: {original_file_size} bytes")
                
                logger.info(f"Successfully reconstructed file {file_obj.file_name} ({len(reconstructed_data)} bytes)")
                
            except Exception as e:
                logger.error(f"Failed to reconstruct file: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to reconstruct file: {str(e)}"
                )
            
            # Create a streaming response
            def generate():
                yield reconstructed_data
            
            return StreamingResponse(
                generate(),
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{file_obj.file_name}\"",
                    "Content-Length": str(len(reconstructed_data))
                }
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}"
        )

# Google Drive-style user sharing endpoints

@router.post("/files/share-with-user", response_model=dict)
def share_file_with_user(
    request: ShareWithUserRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """Share a file directly with a specific user (Google Drive style)"""
    
    # Verify file exists and user owns it
    file_obj = db.query(FileObject).filter(
        FileObject.file_id == uuid.UUID(request.file_id),
        FileObject.account_id == current_user.account_id
    ).first()
    
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found or not owned by user")
    
    # Find target user
    target_user = db.query(Account).filter(Account.username == request.username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if already shared with this user
    existing_share = db.query(FileShare).filter(
        FileShare.file_id == file_obj.file_id,
        FileShare.shared_by == current_user.account_id,
        FileShare.shared_with == target_user.account_id,
        FileShare.is_active == "ACTIVE"
    ).first()
    
    if existing_share:
        raise HTTPException(status_code=400, detail="File already shared with this user")
    
    # Create expiration date if specified
    expires_at = None
    if request.expires_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=request.expires_hours)
    
    # Create file share (no share_token needed for direct user shares)
    file_share = FileShare(
        file_id=file_obj.file_id,
        shared_by=current_user.account_id,
        shared_with=target_user.account_id,
        share_token=None,  # No public token for user shares
        permissions=request.permissions,
        expires_at=expires_at,
        is_active="ACTIVE"
    )
    
    db.add(file_share)
    db.commit()
    db.refresh(file_share)
    
    return {
        "message": f"File '{file_obj.file_name}' shared with {target_user.username}",
        "share_id": str(file_share.share_id),
        "permissions": file_share.permissions,
        "expires_at": file_share.expires_at
    }

@router.get("/with-me", response_model=List[SharedWithMeResponse])
def get_files_shared_with_me(
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """Get all files shared with the current user (Google Drive style)"""
    
    # Get files shared with current user
    shared_files = db.query(
        FileShare,
        FileObject,
        Account
    ).join(
        FileObject, FileShare.file_id == FileObject.file_id
    ).join(
        Account, FileShare.shared_by == Account.account_id
    ).filter(
        FileShare.shared_with == current_user.account_id,
        FileShare.is_active == "ACTIVE"
    ).all()
    
    result = []
    for share, file_obj, shared_by in shared_files:
        # Check if share is expired
        if share.expires_at and share.expires_at < datetime.now(timezone.utc):
            continue
            
        result.append(SharedWithMeResponse(
            share_id=str(share.share_id),
            file_id=str(file_obj.file_id),
            file_name=file_obj.file_name,
            shared_by_username=shared_by.username,
            permissions=share.permissions,
            shared_at=share.created_at,
            expires_at=share.expires_at
        ))
    
    return result

@router.get("/users/search", response_model=List[UserSearchResponse])
def search_users(
    q: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """Search for users to share files with"""
    
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
    
    # Search users by username or email (exclude current user)
    users = db.query(Account).filter(
        and_(
            Account.account_id != current_user.account_id,
            or_(
                Account.username.ilike(f"%{q}%"),
                Account.email.ilike(f"%{q}%")
            )
        )
    ).limit(10).all()
    
    return [
        UserSearchResponse(
            username=user.username,
            email=user.email,
            account_type=user.account_type
        ) for user in users
    ]

# This supposedly shares the same reconstruction logic as shared-download, and allows previewing the file for the owner.
async def reconstruct_file_for_owner(file_id: str, db: Session) -> tuple[bytes, FileObject]:
    """
    Reuse the same reconstruction logic as shared-download,
    but for an owned file_id (no sharing).
    Returns (bytes, FileObject).
    """
    import httpx
    import base64
    from app.core.erasure_coding import get_erasure_coder_for_profile

    masternode_url = "http://master-node:3000"

    async with httpx.AsyncClient() as client:
        # Get file info
        file_info_resp = await client.get(f"{masternode_url}/files/info/{file_id}")
        if file_info_resp.status_code == 404:
            raise HTTPException(status_code=404, detail="File not found in storage")
        if file_info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve file info: {file_info_resp.text}",
            )
        file_info = file_info_resp.json()["file"]

        # Get fragments
        fragments_resp = await client.get(f"{masternode_url}/fragments/{file_id}")
        if fragments_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve fragments: {fragments_resp.text}",
            )
        fragments = fragments_resp.json()
        if not fragments:
            raise HTTPException(status_code=404, detail="File fragments not found")

        # Erasure decoder
        try:
            erasure_id = file_info["erasure_id"]
            erasure_coder = get_erasure_coder_for_profile(erasure_id)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize erasure decoder: {str(e)}",
            )

        # Fetch fragment data
        available_fragments = []
        fragment_indexes = []

        sorted_fragments = sorted(fragments, key=lambda x: x["num_fragment"])
        for fragment in sorted_fragments:
            fragment_num = fragment["num_fragment"]
            api_endpoint = fragment.get("api_endpoint")
            fragment_id = fragment.get("fragment_id")
            if not api_endpoint or not fragment_id:
                continue

            fragment_url = f"{api_endpoint}/fragments/{fragment_id}"
            try:
                frag_resp = await client.get(fragment_url, timeout=30)
                if frag_resp.status_code == 200:
                    fragment_data = frag_resp.json()
                    if fragment_data.get("success") and fragment_data.get("data"):
                        decoded = base64.b64decode(fragment_data["data"])
                        available_fragments.append(decoded)
                        fragment_indexes.append(fragment_num)
            except Exception:
                continue

        if not erasure_coder.can_reconstruct(len(available_fragments)):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Not enough fragments for reconstruction. "
                    f"Need {erasure_coder.k}, got {len(available_fragments)}"
                ),
            )

        reconstructed = erasure_coder.decode_data(available_fragments, fragment_indexes)
        original_size = int(file_info["file_size"])
        if len(reconstructed) > original_size:
            reconstructed = reconstructed[:original_size]

    # Local DB object
    file_obj = db.query(FileObject).filter(
        FileObject.file_id == file_id
    ).first()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    return reconstructed, file_obj


@router.get("/files/shared-user-download/{share_id}")
async def download_user_shared_file(
    share_id: str,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """Download a file that was shared directly with the current user"""
    
    # Find the share
    file_share = db.query(FileShare).filter(
        FileShare.share_id == uuid.UUID(share_id),
        FileShare.shared_with == current_user.account_id,
        FileShare.is_active == "ACTIVE"
    ).first()
    
    if not file_share:
        raise HTTPException(status_code=404, detail="Share not found or not accessible")
    
    # Check if share is expired
    if file_share.expires_at and file_share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Share has expired")
    
    # Check permissions
    if file_share.permissions not in ["DOWNLOAD"]:
        raise HTTPException(status_code=403, detail="Download permission not granted")
    
    # Get file info and use the same download logic as shared-download
    file_obj = db.query(FileObject).filter(FileObject.file_id == file_share.file_id).first()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Reuse the same file reconstruction logic from shared-download
    # (This could be refactored into a shared function)
    try:
        from fastapi.responses import StreamingResponse
        import httpx
        master_node_url = "http://master_node:3000"
        
        async with httpx.AsyncClient() as client:
            # Get file info
            file_info_response = await client.get(f"{master_node_url}/files/info/{file_share.file_id}")
            if file_info_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to retrieve file info")
            
            file_info = file_info_response.json()["file"]
            
            # Get fragments
            fragments_response = await client.get(f"{master_node_url}/fragments/{file_share.file_id}")
            if fragments_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to retrieve fragments")
            
            fragments = fragments_response.json()
            if not fragments:
                raise HTTPException(status_code=404, detail="File fragments not found")
            
            # Import reconstruction modules
            from app.core.erasure_coding import get_erasure_coder_for_profile
            import base64
            
            # Initialize erasure decoder
            erasure_coder = get_erasure_coder_for_profile(file_info["erasure_id"])
            
            # Fetch and reconstruct file (same logic as shared-download)
            sorted_fragments = sorted(fragments, key=lambda x: x["num_fragment"])
            available_fragments = []
            fragment_indexes = []
            
            for fragment in sorted_fragments:
                if not fragment.get("fragment_id") or not fragment.get("api_endpoint"):
                    continue
                
                storage_url = fragment["api_endpoint"]
                fragment_url = f"{storage_url}/fragments/{fragment['fragment_id']}"
                
                try:
                    frag_response = await client.get(fragment_url, timeout=30)
                    if frag_response.status_code == 200:
                        fragment_data = frag_response.json()
                        if fragment_data.get("success") and fragment_data.get("data"):
                            decoded_data = base64.b64decode(fragment_data["data"])
                            available_fragments.append(decoded_data)
                            fragment_indexes.append(fragment["num_fragment"])
                except Exception:
                    continue
            
            if not erasure_coder.can_reconstruct(len(available_fragments)):
                raise HTTPException(status_code=500, detail="Not enough fragments for reconstruction")
            
            # Reconstruct file
            reconstructed_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
            
            # Truncate to original size
            original_file_size = int(file_info["file_size"])
            if len(reconstructed_data) > original_file_size:
                reconstructed_data = reconstructed_data[:original_file_size]
            
            def generate():
                yield reconstructed_data
            
            return StreamingResponse(
                generate(),
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{file_obj.file_name}\"",
                    "Content-Length": str(len(reconstructed_data))
                }
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
