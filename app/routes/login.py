from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from typing import Optional
import traceback
import logging

from app.master_node_db import MasterNodeDB, get_master_db
from app.core.security import verify_password, get_password_hash, create_access_token
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = HTTPBearer()


class LoginRequest(BaseModel):
	username_or_email: str
	password: str
	selected_role: Optional[str] = None  # Optional - for UI purposes, system auto-determines account type


class RegisterRequest(BaseModel):
	username: str
	email: EmailStr
	password: str


class TokenResponse(BaseModel):
	access_token: str
	token_type: str = "bearer"
	account_id: str
	username: str
	account_type: str


class UserResponse(BaseModel):
	account_id: str
	username: str
	email: str
	account_type: str
	created_at: str


def get_account_by_username_or_email_master_node(master_db: MasterNodeDB, username_or_email: str) -> Optional[dict]:
    """Get account by username or email from master node database (PostgreSQL)."""

    # Try username first
    query_username = """
        SELECT account_id, username, email, password_hash, account_type, status, created_at
        FROM account
        WHERE username = $1
    """
    result = master_db.select(query_username, [username_or_email])
    if result:
        return result[0]

    # If no result by username, try email
    query_email = """
        SELECT account_id, username, email, password_hash, account_type, status, created_at
        FROM account
        WHERE email = $1
    """
    result = master_db.select(query_email, [username_or_email])
    if result:
        return result[0]

    return None


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    request: Request,
    master_db: MasterNodeDB = Depends(get_master_db)
):
    """
    Login endpoint using master node database (PostgreSQL). Accepts username/email and password.
    Returns JWT access token on successful authentication.
    The system automatically determines the account type (FREE, PAID, or SYSADMIN) and redirects accordingly.
    """
    try:
        # Find account by username or email from master node (PostgreSQL)
        try:
            account = get_account_by_username_or_email_master_node(
                master_db, login_data.username_or_email
            )
        except Exception as e:
            # Log the error for debugging
            logger.error(f"Error querying master node for login: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Database service unavailable. Please check if master node is running. "
                    f"Error: {str(e)}"
                ),
            )

        if not account:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username/email or password",
            )

        # Block inactive accounts
        account_status = account.get("status", "ACTIVE")
        if account_status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Please contact support or an administrator.",
            )

        # Verify password
        if not verify_password(login_data.password, account["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username/email or password",
            )

        # Get account type (default to 'FREE' if None)
        account_type = account.get("account_type", "FREE")

        # Validate account_id is a valid UUID string
        account_id = account.get("account_id")
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid account data: missing account_id",
            )

        # Convert account_id to UUID if it's a string
        try:
            if isinstance(account_id, str):
                account_id_uuid = uuid.UUID(account_id)
            else:
                account_id_uuid = account_id
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid account_id format: {account_id}, error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid account data: account_id format error",
            )

        # Create access token
        access_token = create_access_token(
            data={"sub": str(account_id_uuid), "username": account["username"]}
        )

        # Log login activity via Master Node
        try:
            login_log_sql = """
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
            """
            log_details = (
                f'{{"username": "{account["username"]}", '
                f'"account_type": "{account_type}"}}'
            )
            master_db.execute(
                login_log_sql,
                [
                    str(uuid.uuid4()),
                    str(account_id_uuid),
                    "LOGIN",
                    "ACCOUNT",
                    str(account_id_uuid),
                    request.client.host if request.client else "unknown",
                    request.headers.get("user-agent", "unknown"),
                    log_details,
                ],
            )
        except Exception as e:
            # Log activity logging errors but don't fail the login
            logger.warning(f"Failed to log login activity: {str(e)}")

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            account_id=str(account_id_uuid),
            username=account["username"],
            account_type=account_type,
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log the full error for debugging
        error_msg = str(e)
        logger.error(f"Login error: {error_msg}")
        logger.error(f"Traceback: {traceback.format_exc()}")

        # Return more detailed error in development, generic in production
        import os

        if os.getenv("DEBUG", "false").lower() == "true" or os.getenv("TESTING") == "1":
            detail = f"Internal server error during login: {error_msg}"
        else:
            detail = "Internal server error during login. Please check server logs."

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(register_data: RegisterRequest, master_db: MasterNodeDB = Depends(get_master_db)):
    """
    Registration endpoint. Creates a new account through master node (PostgreSQL).
    """
    try:
        # Check if username already exists
        username_check = master_db.select(
            "SELECT account_id FROM account WHERE username = $1",
            [register_data.username]
        )
        if username_check:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Check if email already exists
        email_check = master_db.select(
            "SELECT account_id FROM account WHERE email = $1",
            [register_data.email]
        )
        if email_check:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Create new account
        account_id = str(uuid.uuid4())
        hashed_password = get_password_hash(register_data.password)

        # Insert account into database via master node
        master_db.execute(
            """
            INSERT INTO account (account_id, username, email, password_hash, account_type, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            [account_id, register_data.username, register_data.email, hashed_password, "FREE"]
        )

        # Create account-specific records (FREE only)
        master_db.execute(
            "INSERT INTO free_account (account_id, storage_limit_gb) VALUES ($1, $2)",
            [account_id, 2]
        )

        # Retrieve the created account to return
        account_result = master_db.select(
            """
            SELECT account_id, username, email, account_type, created_at
            FROM account 
            WHERE account_id = $1
            """,
            [account_id]
        )

        if not account_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve created account",
            )

        account = account_result[0]

        # Format created_at properly
        created_at = account["created_at"]
        if isinstance(created_at, str):
            created_at_str = created_at
        else:
            created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)

        return UserResponse(
            account_id=account["account_id"],
            username=account["username"],
            email=account["email"],
            account_type=account["account_type"],
            created_at=created_at_str,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during registration: {str(e)}"
        )


@router.get("/me", response_model=UserResponse)
def get_current_user(
    token = Depends(oauth2_scheme),
    master_db: MasterNodeDB = Depends(get_master_db)
):
    """
    Get current authenticated user information from master node (PostgreSQL).
    """
    from app.core.security import decode_access_token

    try:
        # ✅ Extract the raw token string from the HTTPAuthorizationCredentials object
        token_str = token.credentials if hasattr(token, "credentials") else token

        payload = decode_access_token(token_str)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        account_id = payload.get("sub")
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        # Get account from master node (PostgreSQL)
        account_result = master_db.select(
            """
            SELECT account_id, username, email, account_type, created_at
            FROM account 
            WHERE account_id = $1
            """,
            [account_id]
        )
        
        if not account_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        account = account_result[0]
        
        # Format created_at properly
        created_at = account["created_at"]
        if isinstance(created_at, str):
            created_at_str = created_at
        else:
            created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)

        return UserResponse(
            account_id=account["account_id"],
            username=account["username"],
            email=account["email"],
            account_type=account["account_type"],
            created_at=created_at_str,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /auth/me: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )
