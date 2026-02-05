from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import httpx

from app.master_node_db import MasterNodeDB, get_master_db
from app.dependencies.auth import require_sysadmin

router = APIRouter(prefix="/sysadmin/nodes", tags=["sysadmin"])


class NodeStatusRequest(BaseModel):
    node_id: str


class NodeInfo(BaseModel):
    node_id: str
    node_role: str
    hostname: str
    api_endpoint: str
    is_active: bool
    heartbeat_at: str = None
    total_bytes: int = None
    used_bytes: int = None
    available_bytes: int = None


@router.get("", response_model=List[NodeInfo])
async def list_nodes(
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    """
    SysAdmin: Get all nodes with their health status and capacity.
    """
    try:
        # Call master node's /nodes endpoint to get all node data
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{master_db.master_node_url}/nodes")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve nodes from master node: {response.text}"
            )
        
        nodes_data = response.json()
        
        # Convert to NodeInfo objects
        nodes = []
        for node in nodes_data:
            nodes.append(NodeInfo(
                node_id=node.get("node_id"),
                node_role=node.get("node_role"),
                hostname=node.get("hostname"),
                api_endpoint=node.get("api_endpoint"),
                is_active=bool(node.get("is_active")),
                heartbeat_at=str(node.get("heartbeat_at")) if node.get("heartbeat_at") else None,
                total_bytes=node.get("total_bytes"),
                used_bytes=node.get("used_bytes"),
                available_bytes=node.get("available_bytes")
            ))
        
        return nodes
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving nodes: {str(e)}"
        )


@router.post("/mark-active")
async def mark_node_active(
    request: NodeStatusRequest,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    """
    SysAdmin: Mark a node as active.
    """
    try:
        # Update node status in master node database
        sql = "UPDATE node SET is_active = true WHERE node_id = $1"
        result = master_db.execute(sql, [request.node_id])
        
        if result == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node {request.node_id} not found"
            )
        
        return {"message": f"Node {request.node_id} marked as active"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking node active: {str(e)}"
        )


@router.post("/mark-inactive")
async def mark_node_inactive(
    request: NodeStatusRequest,
    master_db: MasterNodeDB = Depends(get_master_db),
    _: dict = Depends(require_sysadmin),
):
    """
    SysAdmin: Mark a node as inactive.
    """
    try:
        # Update node status in master node database
        sql = "UPDATE node SET is_active = false WHERE node_id = $1"
        result = master_db.execute(sql, [request.node_id])
        
        if result == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Node {request.node_id} not found"
            )
        
        return {"message": f"Node {request.node_id} marked as inactive"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking node inactive: {str(e)}"
        )