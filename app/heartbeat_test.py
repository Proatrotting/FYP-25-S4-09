from fastapi import APIRouter, Depends, HTTPException
from app.master_node_db import MasterNodeDB, get_master_db
from app.heartbeat_monitor import HeartbeatMonitor

router = APIRouter(prefix="/debug", tags=["debug"])

@router.post("/heartbeat-check-once")
async def heartbeat_check_once(master_db: MasterNodeDB = Depends(get_master_db)):
    try:
        monitor = HeartbeatMonitor()
        # reuse the FastAPI-injected master_db instead of creating a new one
        monitor.master_db = master_db
        await monitor.check_node_health()
        return {"message": "Heartbeat check executed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}" )
