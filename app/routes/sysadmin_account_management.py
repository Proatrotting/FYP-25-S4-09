from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import List, Optional

from app.master_node_db import MasterNodeDB, get_master_db
from app.dependencies.auth import require_sysadmin

router = APIRouter(prefix="/sysadmin/accounts", tags=["sysadmin"])


class AccountSelector(BaseModel):
    account_id: Optional[str] = None
    username: Optional[str] = None


class SysadminUser(BaseModel):
    account_id: str
    username: str
    email: str
    account_type: str
    status: str
    created_at: str


@router.get("", response_model=List[SysadminUser])
def list_all_users(
    username: Optional[str] = Query(
        None, description="Filter by username (contains, case-insensitive)"
    ),
    email: Optional[str] = Query(
        None, description="Filter by email (contains, case-insensitive)"
    ),
    account_type: Optional[str] = Query(
        None, description="Filter by account type (e.g. FREE, SYSADMIN)"
    ),
    account_status: Optional[str] = Query(
        None, description="Filter by account status (e.g. ACTIVE, INACTIVE)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Number of users to return"),
    offset: int = Query(0, ge=0, description="Number of users to skip"),
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    sql = """
        SELECT account_id, username, email, account_type, status, created_at
        FROM account
    """
    conditions = []
    params: List[object] = []
    idx = 1

    # Optional filters
    if username:
        conditions.append(f"LOWER(username) LIKE ${idx}")
        params.append(f"%{username.lower()}%")
        idx += 1

    if email:
        conditions.append(f"LOWER(email) LIKE ${idx}")
        params.append(f"%{email.lower()}%")
        idx += 1

    if account_type:
        conditions.append(f"account_type = ${idx}")
        params.append(account_type.upper())
        idx += 1

    if account_status:
         conditions.append(f"status = ${idx}")
         params.append(account_status.upper())
         idx += 1

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += f" ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    params.extend([limit, offset])

    rows = master_db.select(sql, params)

    users: List[SysadminUser] = []
    for r in rows:
        created_at = r["created_at"]
        if isinstance(created_at, str):
            created_at_str = created_at
        else:
            created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)

        users.append(
            SysadminUser(
                account_id=str(r["account_id"]),
                username=r["username"],
                email=r["email"],
                account_type=r.get("account_type", "FREE"),
                status=r.get("status", "ACTIVE"),
                created_at=created_at_str,
            )
        )

    return users


def resolve_account_id(selector: AccountSelector, master_db: MasterNodeDB) -> str:
    """
    Resolve an account_id from either account_id or username.
    At least one must be provided.
    """
    if not selector.account_id and not selector.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either account_id or username.",
        )

    if selector.account_id:
        rows = master_db.select(
            "SELECT account_id FROM account WHERE account_id = $1",
            [selector.account_id],
        )
    else:
        rows = master_db.select(
            "SELECT account_id FROM account WHERE username = $1",
            [selector.username],
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    return str(rows[0]["account_id"])


@router.post("/deactivate", status_code=200)
def deactivate_account(
    selector: AccountSelector,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    account_id = resolve_account_id(selector, master_db)

    # Set status to INACTIVE
    master_db.execute(
        "UPDATE account SET status = $1 WHERE account_id = $2",
        ["INACTIVE", account_id],
    )

    return {
        "message": "Account deactivated",
        "account_id": account_id,
    }



@router.delete("", status_code=200)
def delete_account(
    selector: AccountSelector,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    """
    Hard delete an account by account_id or username.
    """
    account_id = resolve_account_id(selector, master_db)

    master_db.execute(
        "DELETE FROM account WHERE account_id = $1",
        [account_id],
    )

    return {"message": "Account deleted", "account_id": account_id}

@router.post("/_seed_sysadmin", status_code=200)
def seed_sysadmin(
    username: str,
    master_db: MasterNodeDB = Depends(get_master_db),
):
    """
    TEMP: Promote a user to SYSADMIN. Remove after use.
    """
    master_db.execute(
        "UPDATE account SET account_type = $1 WHERE username = $2",
        ["SYSADMIN", username],
    )
    return {"message": "Sysadmin updated", "username": username}


@router.post("/activate", status_code=200)
def activate_account(
    selector: AccountSelector,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    # Reuse your resolver to get the account_id
    account_id = resolve_account_id(selector, master_db)

    # Set status back to ACTIVE
    master_db.execute(
        "UPDATE account SET status = $1 WHERE account_id = $2",
        ["ACTIVE", account_id],
    )

    return {
        "message": "Account activated",
        "account_id": account_id,
    }
