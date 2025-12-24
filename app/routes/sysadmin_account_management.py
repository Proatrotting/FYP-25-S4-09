from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional

from app.master_node_db import MasterNodeDB, get_master_db

router = APIRouter(prefix="/sysadmin/accounts", tags=["sysadmin"])


class AccountSelector(BaseModel):
    account_id: Optional[str] = None
    username: Optional[str] = None


class SysadminUser(BaseModel):
    account_id: str
    username: str
    email: str
    account_type: str
    created_at: str


@router.get("", response_model=List[SysadminUser])
def list_all_users(
    master_db: MasterNodeDB = Depends(get_master_db),
):
    rows = master_db.select(
        """
        SELECT account_id, username, email, account_type, created_at
        FROM account
        ORDER BY created_at DESC
        """,
        [],
    )

    users: List[SysadminUser] = []
    for r in rows:
        created_at = r["created_at"]
        if isinstance(created_at, str):
            created_at_str = created_at
        else:
            created_at_str = (
                created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else str(created_at)
            )

        users.append(
            SysadminUser(
                account_id=str(r["account_id"]),
                username=r["username"],
                email=r["email"],
                account_type=r.get("account_type", "FREE"),
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
):
    """
    Placeholder deactivate: currently just checks that the account exists.
    Later you can change this to UPDATE a status column.
    """
    account_id = resolve_account_id(selector, master_db)

    return {
        "message": "Account exists (no status column yet)",
        "account_id": account_id,
    }


@router.delete("", status_code=200)
def delete_account(
    selector: AccountSelector,
    master_db: MasterNodeDB = Depends(get_master_db),
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
