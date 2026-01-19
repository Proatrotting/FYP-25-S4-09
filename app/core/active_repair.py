"""
Active Repair - Node Failure Handler
Triggered when heartbeat monitor detects a node failure.
Creates repair jobs for all fragments that were on the failed node.
"""
import logging
import uuid
from typing import List, Dict

logger = logging.getLogger(__name__)

async def handle_node_failure_event(node_id: str) -> int:
    """
    Called when a node is marked inactive by the heartbeat monitor.
    Creates repair jobs for all file versions that had fragments on this node.
    
    Args:
        node_id: ID of the failed node
        
    Returns:
        Number of repair jobs created
    """
    from app.master_node_db import MasterNodeDB
    from app.core.erasure_coding import get_erasure_coder_for_profile
    
    master_db = MasterNodeDB()
    repair_jobs_created = 0
    
    try:
        logger.warning(f"Handling node failure event for node {node_id}")
        
        # Get all file versions that had fragments on this node
        sql = """
            SELECT DISTINCT fv.VERSION_ID, fv.ERASURE_ID, fo.FILE_NAME,
                   COUNT(DISTINCT ff.FRAGMENT_ID) as fragments_on_node
            FROM FILE_VERSIONS fv
            JOIN FILE_OBJECTS fo ON fv.FILE_ID = fo.FILE_ID
            JOIN FILE_SEGMENTS fs ON fv.VERSION_ID = fs.VERSION_ID
            JOIN FILE_FRAGMENTS ff ON fs.SEGMENT_ID = ff.SEGMENT_ID
            JOIN FRAGMENT_LOCATION fl ON ff.FRAGMENT_ID = fl.FRAGMENT_ID
            WHERE fl.NODE_ID = $1
            GROUP BY fv.VERSION_ID, fv.ERASURE_ID, fo.FILE_NAME
            ORDER BY fragments_on_node DESC
        """
        affected_versions = master_db.select(sql, [node_id])
        
        if not affected_versions:
            logger.info(f"No file versions affected by node {node_id} failure")
            return 0
        
        logger.warning(f"Node {node_id} failure affects {len(affected_versions)} file versions")
        
        for version_info in affected_versions:
            version_id = version_info.get("version_id")
            erasure_id = version_info.get("erasure_id", "MEDIUM")
            file_name = version_info.get("file_name", "unknown")
            fragments_lost = version_info.get("fragments_on_node", 0)
            
            try:
                # Get current fragment health
                health_sql = """
                    SELECT COUNT(DISTINCT ff.FRAGMENT_ID) as total_fragments,
                           COUNT(DISTINCT CASE 
                               WHEN fl.NODE_ID IS NOT NULL AND n.IS_ACTIVE = true 
                               THEN ff.FRAGMENT_ID 
                           END) as available_fragments
                    FROM FILE_FRAGMENTS ff
                    JOIN FILE_SEGMENTS fs ON ff.SEGMENT_ID = fs.SEGMENT_ID
                    LEFT JOIN FRAGMENT_LOCATION fl ON ff.FRAGMENT_ID = fl.FRAGMENT_ID
                    LEFT JOIN NODE n ON fl.NODE_ID = n.NODE_ID
                    WHERE fs.VERSION_ID = $1
                """
                health_result = master_db.select(health_sql, [version_id])
                
                if not health_result:
                    continue
                
                health = health_result[0]
                total_fragments = int(health.get("total_fragments", 0))
                available_fragments = int(health.get("available_fragments", 0))
                fragments_missing = total_fragments - available_fragments
                
                # Get erasure coding profile
                erasure_coder = get_erasure_coder_for_profile(erasure_id)
                profile_info = erasure_coder.get_fragment_info()
                k_fragments = profile_info["k"]
                
                # Only create repair job if we can still reconstruct
                if available_fragments >= k_fragments:
                    # Check if repair job already exists
                    check_sql = """
                        SELECT JOB_ID 
                        FROM REPAIR_JOBS 
                        WHERE VERSION_ID = $1 
                        AND STATUS IN ('PENDING', 'IN_PROGRESS')
                        LIMIT 1
                    """
                    existing = master_db.select(check_sql, [version_id])
                    
                    if existing and len(existing) > 0:
                        logger.debug(f"Repair job already exists for version {version_id}")
                        continue
                    
                    # Determine priority based on remaining fragments
                    if available_fragments <= k_fragments:
                        priority = 10  # CRITICAL - minimum fragments remaining
                    elif available_fragments <= k_fragments + 1:
                        priority = 8   # HIGH - very low redundancy
                    else:
                        priority = 6   # MEDIUM - still have some redundancy
                    
                    # Create repair job
                    job_id = str(uuid.uuid4())
                    insert_sql = """
                        INSERT INTO REPAIR_JOBS 
                        (JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                         FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT)
                        VALUES ($1, $2, $3, 'PENDING', $4, $5, $6, NOW(), NOW())
                    """
                    reason = f"Node failure: node {node_id} lost {fragments_lost} fragments (file: {file_name})"
                    
                    master_db.execute(insert_sql, [
                        job_id, version_id, reason, priority,
                        fragments_missing, available_fragments
                    ])
                    
                    repair_jobs_created += 1
                    logger.warning(
                        f"Created priority-{priority} repair job for {file_name}: "
                        f"{available_fragments}/{total_fragments} fragments remaining after node failure"
                    )
                else:
                    # Cannot reconstruct - critical data loss
                    logger.error(
                        f"CRITICAL DATA LOSS: File {file_name} (version {version_id}) "
                        f"only has {available_fragments}/{total_fragments} fragments after node {node_id} failure "
                        f"(need {k_fragments} minimum for reconstruction)"
                    )
                    
            except Exception as version_error:
                logger.error(f"Error processing version {version_id} after node failure: {version_error}")
                continue
        
        logger.warning(
            f"Node failure event processed: {repair_jobs_created} repair jobs created "
            f"for {len(affected_versions)} affected file versions"
        )
        
    except Exception as e:
        logger.error(f"Error handling node failure event for node {node_id}: {e}", exc_info=True)
    
    return repair_jobs_created

