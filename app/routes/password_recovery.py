import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr

from app.core.security import get_password_hash, verify_password
from app.master_node_db import MasterNodeDB, get_master_db
from app.core.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

RESET_TOKEN_EXPIRY_MINUTES = 10


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    email_verified: bool


class ResetFromTokenRequest(BaseModel):
    token: str
    new_password: str


class ResetFromTokenResponse(BaseModel):
    message: str


def get_account_by_email(master_db: MasterNodeDB, email: str):
    """
    Get account by email via master node.
    """
    result = master_db.select(
        """
        SELECT account_id, username, email, password_hash, account_type, created_at
        FROM account
        WHERE LOWER(email) = LOWER($1)
        """,
        [email],
    )
    return result[0] if result else None


def create_password_reset_token(master_db: MasterNodeDB, account_id: str) -> str:
    """
    Create and persist a password reset token.
    """
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)

    master_db.execute(
        """
        INSERT INTO password_reset_tokens (token, account_id, expires_at, used)
        VALUES ($1, $2, $3, FALSE)
        """,
        [token, account_id, expires_at.isoformat()],  
    )
    return token


def get_reset_token(master_db: MasterNodeDB, token: str):
    rows = master_db.select(
        """
        SELECT token, account_id, expires_at, used
        FROM password_reset_tokens
        WHERE token = $1
        """,
        [token],
    )
    return rows[0] if rows else None


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    master_db: MasterNodeDB = Depends(get_master_db),
):
    """
    Forgot password (Beta version).

    - Verifies the email.
    - Generates a password reset token.
    - Sends reset link to the user's email.

    Always returns a generic message to avoid leaking whether the email exists.
    """
    try:
        email_lower = body.email.lower()
        account = get_account_by_email(master_db, email_lower)

        generic_message = (
            "If this email exists in our system, a reset link has been sent."
        )

        # If account not found, still return generic response
        if not account:
            logger.info(
                f"Password reset requested for non-existent email: {email_lower}"
            )
            return ForgotPasswordResponse(
                message=generic_message,
                email_verified=False,
            )

        # Account exists: create reset token
        token = create_password_reset_token(master_db, str(account["account_id"]))

        # Build reset URL (point to your frontend route)
        base_url = str(request.base_url).rstrip("/")
        # Example frontend path, adjust as needed
        reset_link = f"{base_url}/reset-password?token={token}"

        # Send email with reset link
        email_body = (
            f"Hi {account['username']},\n\n"
            f"You requested a password reset. Click the link below to set a new password:\n\n"
            f"{reset_link}\n\n"
            f"This link will expire in {RESET_TOKEN_EXPIRY_MINUTES} minutes.\n\n"
            "If you did not request this, you can ignore this email."
        )

        try:
            send_email(
                to=email_lower,
                subject="Password Reset Request",
                body=email_body,
            )
        except Exception as email_error:
            logger.error(
                f"Failed to send password reset email to {email_lower}: {email_error}"
            )
            # Option 1: still return success message (more user-friendly)
            # Option 2: raise HTTP 500 to indicate failure. For beta, Option 1 is ok.

        logger.info(f"Password reset email sent for account: {account['account_id']}")

        return ForgotPasswordResponse(
            message=generic_message,
            email_verified=True,
        )

    except Exception as e:
        logger.error(f"Error in forgot password: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing password reset request",
        )


@router.post("/reset-password-from-token", response_model=ResetFromTokenResponse)
def reset_password_from_token(
    body: ResetFromTokenRequest,
    request: Request,
    master_db: MasterNodeDB = Depends(get_master_db),
):
    """
    Reset password using a one-time reset token.
    """
    try:
        if not body.new_password or len(body.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long",
            )

        token_row = get_reset_token(master_db, body.token)
        if not token_row or token_row["used"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or used reset token",
            )

         # Parse expires_at if it's a string
        expires_at = token_row["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        
        if expires_at < datetime.utcnow():  # ✅ FIXED
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token has expired",
            )

        account_id = token_row["account_id"]

        # Load account
        account_rows = master_db.select(
            """
            SELECT account_id, password_hash
            FROM account
            WHERE account_id = $1
            """,
            [account_id],
        )
        if not account_rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )
        account = account_rows[0]

        # Ensure new password is different
        if verify_password(body.new_password, account["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password",
            )

        # Update password
        new_password_hash = get_password_hash(body.new_password)
        master_db.execute(
            "UPDATE account SET password_hash = $1 WHERE account_id = $2",
            [new_password_hash, account_id],
        )

        # Mark token as used
        master_db.execute(
            "UPDATE password_reset_tokens SET used = TRUE WHERE token = $1",
            [body.token],
        )

        # Log password reset activity (same style as your previous alpha version)
        try:
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            master_db.execute(
                """
                INSERT INTO activity_log (
                    activity_id,
                    account_id,
                    action_type,
                    resource_type,
                    resource_id,
                    ip_address,
                    user_agent,
                    details,
                    created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                [
                    str(uuid.uuid4()),
                    str(account_id),
                    "PASSWORD_RESET",
                    "ACCOUNT",
                    str(account_id),
                    client_ip,
                    user_agent,
                    '{"method": "reset_token"}',
                ],
            )
        except Exception as log_error:
            logger.warning(
                f"Failed to log password reset activity: {str(log_error)}"
            )

        logger.info(f"Password reset successful for account: {account_id}")

        return ResetFromTokenResponse(
            message="Password has been successfully reset. You can now login with your new password.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting password from token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error resetting password",
        )
