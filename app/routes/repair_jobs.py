from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Optional
from app.master_node_db import MasterNodeDB, get_master_db
from app.dependencies.auth import get_current_account
import logging
import asyncio
import os
import sys

# Add repair_worker to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repair", tags=["repair"])


@router.get("/jobs")
def get_repair_jobs(
    version_id: Optional[str] = None,
    status: Optional[str] = None,
    master_db: MasterNodeDB = Depends(get_master_db),
    current_user: dict = Depends(get_current_account)
):
    """
    Get repair jobs from the database.
    Optionally filter by version_id or status.
    """
    try:
        if version_id:
            sql = """
                SELECT JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                       FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT
                FROM REPAIR_JOBS 
                WHERE VERSION_ID = $1 
                ORDER BY CREATED_AT DESC
            """
            result = master_db.execute_query(sql, [version_id])
        elif status:
            sql = """
                SELECT JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                       FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT
                FROM REPAIR_JOBS 
                WHERE STATUS = $1 
                ORDER BY CREATED_AT DESC
            """
            result = master_db.execute_query(sql, [status])
        else:
            sql = """
                SELECT JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                       FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT
                FROM REPAIR_JOBS 
                ORDER BY CREATED_AT DESC
                LIMIT 100
            """
            result = master_db.execute_query(sql)
        
        return {"jobs": result, "count": len(result)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying repair jobs: {str(e)}")


@router.get("/jobs/{version_id}")
def get_repair_job_by_version(
    version_id: str,
    master_db: MasterNodeDB = Depends(get_master_db),
    current_user: dict = Depends(get_current_account)
):
    """
    Get repair job for a specific version.
    """
    try:
        sql = """
            SELECT JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                   FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT
            FROM REPAIR_JOBS 
            WHERE VERSION_ID = $1 
            ORDER BY CREATED_AT DESC
        """
        result = master_db.execute_query(sql, [version_id])
        
        if not result:
            return {"message": "No repair jobs found for this version", "jobs": []}
        
        return {"jobs": result, "count": len(result)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying repair job: {str(e)}")


@router.post("/jobs/{job_id}/retry")
def retry_repair_job(
    job_id: str,
    master_db: MasterNodeDB = Depends(get_master_db),
    current_user: dict = Depends(get_current_account)
):
    """
    Retry a failed repair job by resetting it to PENDING status.
    """
    try:
        # Check if job exists and is FAILED
        check_sql = """
            SELECT JOB_ID, STATUS FROM REPAIR_JOBS WHERE JOB_ID = $1
        """
        result = master_db.execute_query(check_sql, [job_id])
        
        if not result:
            raise HTTPException(status_code=404, detail="Repair job not found")
        
        current_status = result[0].get("status")
        if current_status not in ["FAILED", "COMPLETED"]:
            return {
                "message": f"Job is already {current_status}, cannot retry",
                "job_id": job_id
            }
        
        # Reset to PENDING
        update_sql = """
            UPDATE REPAIR_JOBS 
            SET STATUS = 'PENDING', ERROR_MESSAGE = NULL, UPDATED_AT = NOW()
            WHERE JOB_ID = $1
        """
        master_db.execute_query(update_sql, [job_id])
        
        logger.info(f"Reset repair job {job_id} to PENDING")
        
        return {
            "message": "Repair job reset to PENDING",
            "job_id": job_id,
            "previous_status": current_status
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrying repair job: {str(e)}")


@router.delete("/jobs/{job_id}")
def cancel_repair_job(
    job_id: str,
    master_db: MasterNodeDB = Depends(get_master_db),
    current_user: dict = Depends(get_current_account)
):
    """
    Cancel a repair job (mark as CANCELLED).
    Only PENDING jobs can be cancelled.
    """
    try:
        # Check if job exists and is PENDING
        check_sql = """
            SELECT JOB_ID, STATUS FROM REPAIR_JOBS WHERE JOB_ID = $1
        """
        result = master_db.execute_query(check_sql, [job_id])
        
        if not result:
            raise HTTPException(status_code=404, detail="Repair job not found")
        
        current_status = result[0].get("status")
        if current_status != "PENDING":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status {current_status}. Only PENDING jobs can be cancelled."
            )
        
        # Mark as CANCELLED
        update_sql = """
            UPDATE REPAIR_JOBS 
            SET STATUS = 'CANCELLED', UPDATED_AT = NOW()
            WHERE JOB_ID = $1
        """
        master_db.execute_query(update_sql, [job_id])
        
        logger.info(f"Cancelled repair job {job_id}")
        
        return {
            "message": "Repair job cancelled",
            "job_id": job_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling repair job: {str(e)}")


@router.get("/stats")
def get_repair_stats(
    master_db: MasterNodeDB = Depends(get_master_db),
    current_user: dict = Depends(get_current_account)
):
    """
    Get repair job statistics.
    """
    try:
        stats_sql = """
            SELECT 
                STATUS,
                COUNT(*) as count,
                AVG(EXTRACT(EPOCH FROM (UPDATED_AT - CREATED_AT))) as avg_duration_seconds
            FROM REPAIR_JOBS
            GROUP BY STATUS
        """
        result = master_db.execute_query(stats_sql)
        
        # Format stats
        stats = {}
        total_jobs = 0
        
        for row in result:
            status = row.get("status")
            count = row.get("count", 0)
            avg_duration = row.get("avg_duration_seconds")
            
            stats[status] = {
                "count": count,
                "avg_duration_seconds": round(avg_duration, 2) if avg_duration else None
            }
            total_jobs += count
        
        return {
            "total_jobs": total_jobs,
            "by_status": stats
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting repair stats: {str(e)}")


@router.post("/trigger-worker")
async def trigger_repair_worker(
    background_tasks: BackgroundTasks,
    max_jobs: Optional[int] = 5,
    current_user: dict = Depends(get_current_account)
):
    """
    Manually trigger the repair worker to process pending jobs.
    This runs the worker once in the background.
    Use this for testing or when repair_worker.py is not running.
    """
    try:
        # Import here to avoid circular dependencies
        from repair_worker import RepairWorker
        
        async def run_worker_once():
            """Run repair worker once"""
            try:
                logger.info(f"Manually triggered repair worker (max {max_jobs} jobs)")
                worker = RepairWorker()
                pending_jobs = await worker.get_pending_jobs()
                
                if pending_jobs:
                    # Limit to max_jobs
                    jobs_to_process = pending_jobs[:max_jobs]
                    logger.info(f"Processing {len(jobs_to_process)} repair jobs")
                    
                    tasks = [worker.process_repair_job(job) for job in jobs_to_process]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Count successes and failures
                    successes = sum(1 for r in results if not isinstance(r, Exception))
                    failures = len(results) - successes
                    
                    logger.info(f"Repair worker completed: {successes} succeeded, {failures} failed")
                else:
                    logger.info("No pending repair jobs to process")
            except Exception as e:
                logger.error(f"Error in manual repair worker: {e}")
        
        background_tasks.add_task(run_worker_once)
        
        return {
            "message": "Repair worker triggered",
            "max_jobs": max_jobs,
            "note": "Worker is running in background. Check logs for progress."
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error triggering repair worker: {str(e)}")
