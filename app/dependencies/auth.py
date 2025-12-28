from fastapi import Depends, HTTPException, status

from app.master_node_db import MasterNodeDB, get_master_db
from app.core.security import decode_access_token
from app.routes.login import oauth2_scheme  


def get_current_account(
    token = Depends(oauth2_scheme),
    master_db: MasterNodeDB = Depends(get_master_db),
) -> dict:
    """
    Shared version of get_current_account (moved out of activity_history.py)
    """
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

    account_result = master_db.select(
        "SELECT account_id, username, email, account_type, created_at "
        "FROM account WHERE account_id = $1",
        [account_id],
    )
    if not account_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return account_result[0]


def require_sysadmin(
    current_account: dict = Depends(get_current_account),
) -> dict:
    """
    Ensure the current user is a SYSADMIN.
    """
    account_type = current_account.get("account_type", "FREE")
    if account_type.upper() != "SYSADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SysAdmin privileges required",
        )
    return current_account
