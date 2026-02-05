from typing import List, Optional, Union
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, validator

from app.master_node_db import MasterNodeDB, get_master_db
from app.dependencies.auth import require_sysadmin

router = APIRouter(prefix="/sysadmin/activity", tags=["sysadmin"])


class SysadminActivityDetail(BaseModel):
    activity_id: str
    account_id: str
    action_type: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[dict] = None
    created_at: Union[str, datetime]

    @validator("created_at", pre=True)
    def serialize_datetime(cls, v):
        # Same style as activity_history.py
        from app.core.timezone_utils import to_local_timezone

        if isinstance(v, datetime):
            local_dt = to_local_timezone(v)
            return local_dt.isoformat()
        elif hasattr(v, "isoformat"):
            if hasattr(v, "astimezone"):
                local_dt = to_local_timezone(v)
                return local_dt.isoformat()
            else:
                return v.isoformat()
        return str(v)


class SysadminActivityResponse(BaseModel):
    activities: List[SysadminActivityDetail]
    total: int
    limit: int
    offset: int
    account_id: Optional[str] = None
    username: Optional[str] = None


def resolve_account_id(
    master_db: MasterNodeDB,
    account_id: Optional[str],
    username: Optional[str],
) -> str:
    """
    Resolve account_id from either account_id or username.
    """
    if account_id:
        return account_id

    if username:
        rows = master_db.select(
            "SELECT account_id FROM account WHERE username = $1",
            [username],
        )
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account with given username not found",
            )
        return str(rows[0]["account_id"])

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Provide either account_id or username",
    )


@router.get("", response_model=SysadminActivityResponse)
def get_user_activity_as_sysadmin(
    account_id: Optional[str] = Query(
        None,
        description="Target account_id. If provided, username is ignored.",
    ),
    username: Optional[str] = Query(
        None,
        description="Target username (used only if account_id is not provided).",
    ),
    action_type: Optional[str] = Query(
        None, description="Filter by action type (e.g., LOGIN, FILE_UPLOAD)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Number of activities to return"),
    offset: int = Query(0, ge=0, description="Number of activities to skip"),
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),  # <--- protect
):
    """
    SysAdmin: View activity history for a specific user, similar to /activity/history
    but selecting the target by account_id or username instead of JWT.
    """

    # 1) Resolve target account_id
    resolved_account_id = resolve_account_id(master_db, account_id, username)

    try:
        # 2) Build WHERE conditions (copy pattern from activity_history.py)
        sql_conditions = ["account_id = $1"]
        params: List[object] = [resolved_account_id]
        param_index = 2

        if action_type:
            sql_conditions.append(f"action_type = ${param_index}")
            params.append(action_type.upper())
            param_index += 1

        where_clause = " AND ".join(sql_conditions)

        # 3) Total count
        count_sql = (
            f"SELECT COUNT(*) as total FROM activity_log WHERE {where_clause}"
        )
        count_result = master_db.select(count_sql, params)
        total = int(count_result[0]["total"]) if count_result else 0

        # 4) Paged activities (same columns and ORDER as activity_history.py)
        activities_sql = f"""
            SELECT activity_id, account_id, action_type, resource_type, resource_id,
                   ip_address, user_agent, details, created_at
            FROM activity_log
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """
        params.extend([limit, offset])

        activities = master_db.select(activities_sql, params)

        # 5) Transform rows to response
        activity_list: List[SysadminActivityDetail] = []
        for activity in activities:
            details_value = activity.get("details")
            if isinstance(details_value, str):
                import json

                try:
                    details_value = json.loads(details_value)
                except Exception:
                    details_value = None

            activity_list.append(
                SysadminActivityDetail(
                    activity_id=str(activity["activity_id"]),
                    account_id=str(activity["account_id"]),
                    action_type=activity["action_type"],
                    resource_type=activity.get("resource_type"),
                    resource_id=str(activity["resource_id"])
                    if activity.get("resource_id")
                    else None,
                    ip_address=activity.get("ip_address"),
                    user_agent=activity.get("user_agent"),
                    details=details_value,
                    created_at=activity["created_at"],
                )
            )

        return SysadminActivityResponse(
            activities=activity_list,
            total=total,
            limit=limit,
            offset=offset,
            account_id=resolved_account_id,
            username=username,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Same error style as activity_history.py
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving activity history for sysadmin: {str(e)}",
        )
