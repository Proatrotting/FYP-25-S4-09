from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from typing import Optional
import traceback
import logging


from app.core.security import verify_password, get_password_hash, decode_access_token
from app.routes.login import oauth2_scheme
from app.master_node_db import MasterNodeDB, get_master_db
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user management"])


# -----------------------------
# Pydantic Schemas
# -----------------------------
class UpdateProfileRequest(BaseModel):
    """Request model for updating user profile."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None


class UpdatePasswordRequest(BaseModel):
    """Request model for updating password."""
    old_password: str
    new_password: str


class UpdateUserResponse(BaseModel):
    """Response model for updated user information."""
    account_id: str
    username: str
    email: str
    account_type: str
    created_at: str
    message: str


# -----------------------------
# Helper - get current account from database
# -----------------------------
def get_current_account_from_db(token: str, master_db: MasterNodeDB):
    """Get account info from database via master node."""
    try:
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
        account_id = payload.get("sub")
        if not account_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        
        # Query via master node
        result = master_db.select(
            "SELECT account_id, username, email, password_hash, account_type, created_at FROM account WHERE account_id = $1",
            [account_id]
        )
        
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        
        return result[0]  # Returns dict instead of SQLAlchemy object
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account from database: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database error")


def get_current_account(token=Depends(oauth2_scheme), master_db: MasterNodeDB = Depends(get_master_db)):
    token_str = token.credentials if hasattr(token, "credentials") else token
    return get_current_account_from_db(token_str, master_db)


# -----------------------------
# Update Profile
# -----------------------------
@router.put("/profile", response_model=UpdateUserResponse)
async def update_profile(
    update_data: UpdateProfileRequest,
    request: Request,
    current_account: dict = Depends(get_current_account),  # Dict from master node
    master_db: MasterNodeDB = Depends(get_master_db)  # Master node DB
):
    try:
        logger.info(f"Profile update request for account {current_account['account_id']}")
        
        if not update_data.username and not update_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one field (username or email) must be provided"
            )
        
        updates_made = []
        
        # Update username if provided
        if update_data.username:
            if update_data.username != current_account["username"]:
                # NEW: Check via master node
                existing = master_db.select(
                    "SELECT account_id FROM account WHERE username = $1 AND account_id != $2",
                    [update_data.username, current_account["account_id"]]
                )
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Username is already taken"
                    )
                
                # NEW: Update via master node
                master_db.execute(
                    "UPDATE account SET username = $1 WHERE account_id = $2",
                    [update_data.username, current_account["account_id"]]
                )
                current_account["username"] = update_data.username
                updates_made.append("username")
                logger.info(f"Username updated for account {current_account['account_id']}")
        
        # Update email if provided
        if update_data.email:
            if update_data.email != current_account["email"]:
                # NEW: Check via master node
                existing = master_db.select(
                    "SELECT account_id FROM account WHERE email = $1 AND account_id != $2",
                    [update_data.email, current_account["account_id"]]
                )
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email is already registered"
                    )
                
                # NEW: Update via master node
                master_db.execute(
                    "UPDATE account SET email = $1 WHERE account_id = $2",
                    [update_data.email, current_account["account_id"]]
                )
                current_account["email"] = update_data.email
                updates_made.append("email")
                logger.info(f"Email updated for account {current_account['account_id']}")
        
        message = f"Profile updated successfully. Updated fields: {', '.join(updates_made)}" if updates_made else "No changes were made to the profile"
        
        # Format created_at
        created_at = current_account["created_at"]
        created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
        
        return UpdateUserResponse(
            account_id=str(current_account["account_id"]),
            username=current_account["username"],
            email=current_account["email"],
            account_type=current_account["account_type"],
            created_at=created_at_str,
            message=message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

# -----------------------------
# Update Password
# -----------------------------
@router.put("/password")
async def update_password(
    password_data: UpdatePasswordRequest,
    request: Request,
    current_account: dict = Depends(get_current_account),
    master_db: MasterNodeDB = Depends(get_master_db)
):
    try:
        logger.info(f"Password update request for account {current_account['account_id']}")
        
        # Verify current password
        if not verify_password(password_data.old_password, current_account["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect current password"
            )
        
        # Validate new password
        if len(password_data.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 8 characters long"
            )
        
        if password_data.new_password == password_data.old_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password"
            )
        
        # NEW: Update password via master node
        new_hash = get_password_hash(password_data.new_password)
        master_db.execute(
            "UPDATE account SET password_hash = $1 WHERE account_id = $2",
            [new_hash, current_account["account_id"]]
        )
        
        logger.info(f"Password updated successfully for account {current_account['account_id']}")
        
        return {
            "message": "Password updated successfully",
            "account_id": str(current_account["account_id"])
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating password: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password"
        )
