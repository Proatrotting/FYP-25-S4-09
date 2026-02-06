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
    Hard delete an account and ALL related data by account_id or username.
    This will permanently delete:
    - User files and all fragments
    - User folders  
    - User activity history
    - Share records
    - Recycle bin entries
    - Encryption key shares
    """
    account_id = resolve_account_id(selector, master_db)
    
    try:
        # Get user info for logging
        user_info = master_db.select(
            "SELECT username, email FROM account WHERE account_id = $1",
            [account_id]
        )
        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )
        
        username = user_info[0]["username"]
        
        # Step 1: Delete file fragments from storage nodes and cleanup metadata
        # Get all file IDs for this user
        user_files = master_db.select(
            "SELECT file_id FROM file_objects WHERE account_id = $1",
            [account_id]
        )
        
        deleted_files = 0
        deleted_fragments = 0
        
        for file_record in user_files:
            file_id = file_record["file_id"]
            
            # Get all fragments for this file's versions
            fragments = master_db.select("""
                SELECT DISTINCT ff.fragment_id, fl.node_id, n.api_endpoint
                FROM file_fragments ff
                JOIN file_segments fs ON ff.segment_id = fs.segment_id  
                JOIN file_versions fv ON fs.version_id = fv.version_id
                LEFT JOIN fragment_location fl ON ff.fragment_id = fl.fragment_id
                LEFT JOIN node n ON fl.node_id = n.node_id
                WHERE fv.file_id = $1
            """, [file_id])
            
            # Delete fragments from storage nodes
            for fragment in fragments:
                fragment_id = fragment.get("fragment_id")
                node_endpoint = fragment.get("api_endpoint")
                
                if fragment_id and node_endpoint:
                    try:
                        import httpx
                        import asyncio
                        
                        async def delete_fragment():
                            async with httpx.AsyncClient() as client:
                                await client.delete(f"{node_endpoint}/fragments/{fragment_id}")
                        
                        asyncio.run(delete_fragment())
                        deleted_fragments += 1
                    except Exception as e:
                        # Log but continue - fragment may already be gone
                        print(f"Warning: Could not delete fragment {fragment_id}: {e}")
            
            deleted_files += 1
        
        # Step 2: Delete database records in correct order (respecting foreign keys)
        
        # Delete key shares (SSS encryption keys)
        master_db.execute("""
            DELETE FROM key_share 
            WHERE key_id IN (
                SELECT fk.key_id FROM file_keys fk
                JOIN file_versions fv ON fk.version_id = fv.version_id  
                JOIN file_objects fo ON fv.file_id = fo.file_id
                WHERE fo.account_id = $1
            )
        """, [account_id])
        
        # Delete file keys
        master_db.execute("""
            DELETE FROM file_keys 
            WHERE version_id IN (
                SELECT fv.version_id FROM file_versions fv
                JOIN file_objects fo ON fv.file_id = fo.file_id
                WHERE fo.account_id = $1
            )
        """, [account_id])
        
        # Delete fragment locations  
        master_db.execute("""
            DELETE FROM fragment_location
            WHERE fragment_id IN (
                SELECT ff.fragment_id FROM file_fragments ff
                JOIN file_segments fs ON ff.segment_id = fs.segment_id
                JOIN file_versions fv ON fs.version_id = fv.version_id
                JOIN file_objects fo ON fv.file_id = fo.file_id  
                WHERE fo.account_id = $1
            )
        """, [account_id])
        
        # Delete file fragments
        master_db.execute("""
            DELETE FROM file_fragments
            WHERE segment_id IN (
                SELECT fs.segment_id FROM file_segments fs
                JOIN file_versions fv ON fs.version_id = fv.version_id
                JOIN file_objects fo ON fv.file_id = fo.file_id
                WHERE fo.account_id = $1
            )
        """, [account_id])
        
        # Delete file segments
        master_db.execute("""
            DELETE FROM file_segments 
            WHERE version_id IN (
                SELECT fv.version_id FROM file_versions fv
                JOIN file_objects fo ON fv.file_id = fo.file_id
                WHERE fo.account_id = $1
            )
        """, [account_id])
        
        # Delete file versions
        master_db.execute("""
            DELETE FROM file_versions
            WHERE file_id IN (
                SELECT file_id FROM file_objects WHERE account_id = $1
            )
        """, [account_id])
        
        # Step 3: Delete shares (both given and received)
        master_db.execute("""
            DELETE FROM share_access_log 
            WHERE accessed_by = $1 OR share_id IN (
                SELECT share_id FROM file_shares WHERE shared_by = $1 OR shared_with = $1
            )
        """, [account_id])
        
        master_db.execute("""
            DELETE FROM file_shares 
            WHERE shared_by = $1 OR shared_with = $1
        """, [account_id])
        
        master_db.execute("""
            DELETE FROM folder_shares 
            WHERE shared_by = $1 OR shared_with = $1  
        """, [account_id])
        
        # Step 4: Delete recycle bin entries
        master_db.execute("""
            DELETE FROM recycle_bin 
            WHERE account_id = $1 OR deleted_by = $1 OR recovered_by = $1
        """, [account_id])
        
        # Step 5: Delete files and folders (CASCADE will handle remaining references)
        master_db.execute("DELETE FROM file_objects WHERE account_id = $1", [account_id])
        master_db.execute("DELETE FROM folder WHERE account_id = $1", [account_id])
        
        # Step 6: Delete activity history
        master_db.execute("DELETE FROM activity_log WHERE account_id = $1", [account_id])
        
        # Step 7: Finally delete the account
        result = master_db.execute(
            "DELETE FROM account WHERE account_id = $1",
            [account_id]
        )
        
        if result == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found or already deleted"
            )
        
        return {
            "message": f"Account '{username}' completely deleted",
            "account_id": account_id,
            "cleanup_summary": {
                "files_deleted": deleted_files,
                "fragments_deleted": deleted_fragments,
                "database_cleanup": "completed"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during complete account deletion: {str(e)}"
        )

@router.post("/_seed_first_sysadmin", status_code=200)
def seed_first_sysadmin(
    username: str,
    master_db: MasterNodeDB = Depends(get_master_db),
):
    """
    One-time: if no SYSADMIN exists, promote `username` to SYSADMIN.
    After at least one SYSADMIN exists, this endpoint is disabled.
    """
    # Check if any sysadmin already exists
    rows = master_db.select(
        "SELECT 1 FROM account WHERE account_type = 'SYSADMIN' LIMIT 1",
        [],
    )
    if rows:
        # Once a sysadmin exists, this endpoint is disabled
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sysadmin already seeded. Use authenticated sysadmin to promote others.",
        )

    # Ensure target user exists
    user_rows = master_db.select(
        "SELECT account_id FROM account WHERE username = $1",
        [username],
    )
    if not user_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found.",
        )

    master_db.execute(
        "UPDATE account SET account_type = $1 WHERE username = $2",
        ["SYSADMIN", username],
    )

    return {"message": "Initial sysadmin seeded", "username": username}


@router.post("/promote-to-sysadmin", status_code=200)
def promote_to_sysadmin(
    selector: AccountSelector,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    account_id = resolve_account_id(selector, master_db)
    master_db.execute(
        "UPDATE account SET account_type = $1 WHERE account_id = $2",
        ["SYSADMIN", account_id],
    )
    return {
        "message": "Account promoted to sysadmin",
        "account_id": account_id,
    }


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
