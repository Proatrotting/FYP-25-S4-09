"""
Active Repair Service
Proactively monitors fragment health and creates repair jobs BEFORE downloads trigger them.
Runs as a standalone service that periodically checks all fragments in the system.

Key differences from Lazy Repair:
- Lazy Repair: Reactive - triggered during file downloads when missing fragments detected
- Active Repair: Proactive - periodically scans all fragments and creates jobs for any issues
"""
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# Python path already configured by container

from app.master_node_db import MasterNodeDB
from app.core.erasure_coding import get_erasure_coder_for_profile

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MASTER_NODE_URL = os.getenv("MASTER_NODE_URL", "http://localhost:8000")
SCAN_INTERVAL = int(os.getenv("ACTIVE_REPAIR_INTERVAL", "300"))  # Scan every 5 minutes
MAX_REPAIR_JOBS_PER_SCAN = int(os.getenv("MAX_REPAIR_JOBS_PER_SCAN", "50"))
SERVICE_ID = os.getenv("ACTIVE_REPAIR_SERVICE_ID", f"active-repair-{uuid.uuid4().hex[:8]}")


class ActiveRepairService:
    """Proactive repair service that monitors fragment health system-wide"""
    
    def __init__(self):
        self.master_db = MasterNodeDB()
        self.master_node_url = MASTER_NODE_URL
        logger.info(f"Active repair service {SERVICE_ID} initialized")
        logger.info(f"Master node URL: {self.master_node_url}")
        logger.info(f"Scan interval: {SCAN_INTERVAL}s")
        logger.info(f"Max repair jobs per scan: {MAX_REPAIR_JOBS_PER_SCAN}")
    
    async def get_all_versions_with_fragments(self) -> List[Dict]:
        """Get all file versions that have fragments in the system"""
        try:
            sql = """
                SELECT DISTINCT fv.VERSION_ID, fv.FILE_ID, fv.ERASURE_ID, 
                       fo.FILE_NAME, fv.BYTES
                FROM FILE_VERSIONS fv
                JOIN FILE_OBJECTS fo ON fv.FILE_ID = fo.FILE_ID
                JOIN FILE_SEGMENTS fs ON fv.VERSION_ID = fs.VERSION_ID
                JOIN FILE_FRAGMENTS ff ON fs.SEGMENT_ID = ff.SEGMENT_ID
                ORDER BY fv.CREATED_AT DESC
            """
            result = self.master_db.select(sql)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Error getting file versions: {e}", exc_info=True)
            return []
    
    async def get_fragment_health(self, version_id: str) -> Dict:
        """
        Check fragment health for a specific version.
        Returns total expected fragments, available fragments, and missing fragment IDs.
        """
        try:
            # Get all fragments for this version with their locations
            sql = """
                SELECT ff.FRAGMENT_ID, ff.NUM_FRAGMENT,
                       fl.NODE_ID, n.IS_ACTIVE
                FROM FILE_FRAGMENTS ff
                JOIN FILE_SEGMENTS fs ON ff.SEGMENT_ID = fs.SEGMENT_ID
                LEFT JOIN FRAGMENT_LOCATION fl ON ff.FRAGMENT_ID = fl.FRAGMENT_ID
                LEFT JOIN NODE n ON fl.NODE_ID = n.NODE_ID
                WHERE fs.VERSION_ID = $1
                ORDER BY ff.NUM_FRAGMENT
            """
            fragments = self.master_db.select(sql, [version_id])
            
            if not fragments:
                return {
                    "version_id": version_id,
                    "total_expected": 0,
                    "available": 0,
                    "missing": 0,
                    "status": "NO_FRAGMENTS"
                }
            
            total_expected = len(fragments)
            available_count = 0
            missing_fragment_ids = []
            inactive_node_fragments = []
            
            for fragment in fragments:
                fragment_id = fragment.get("fragment_id")
                node_id = fragment.get("node_id")
                is_active = fragment.get("is_active")
                
                # Fragment is available if it has a location on an active node
                if node_id and is_active:
                    available_count += 1
                elif node_id and not is_active:
                    # Fragment exists but node is inactive
                    inactive_node_fragments.append(fragment_id)
                else:
                    # No location recorded
                    missing_fragment_ids.append(fragment_id)
            
            missing_count = total_expected - available_count
            
            return {
                "version_id": version_id,
                "total_expected": total_expected,
                "available": available_count,
                "missing": missing_count,
                "missing_fragment_ids": missing_fragment_ids,
                "inactive_node_fragments": inactive_node_fragments,
                "status": "HEALTHY" if missing_count == 0 else "DEGRADED"
            }
            
        except Exception as e:
            logger.error(f"Error checking fragment health for {version_id}: {e}", exc_info=True)
            return {
                "version_id": version_id,
                "status": "ERROR",
                "error": str(e)
            }
    
    async def create_repair_job(
        self,
        version_id: str,
        reason: str,
        fragments_needed: int,
        fragments_available: int,
        priority: int = 3
    ) -> Optional[str]:
        """Create a repair job if one doesn't already exist for this version"""
        try:
            # Check if there's already a pending or in-progress repair job for this version
            check_sql = """
                SELECT JOB_ID 
                FROM REPAIR_JOBS 
                WHERE VERSION_ID = $1 
                AND STATUS IN ('PENDING', 'IN_PROGRESS')
                LIMIT 1
            """
            existing = self.master_db.select(check_sql, [version_id])
            
            if existing and len(existing) > 0:
                logger.debug(f"Repair job already exists for version {version_id}")
                return None
            
            # Create new repair job
            job_id = str(uuid.uuid4())
            insert_sql = """
                INSERT INTO REPAIR_JOBS 
                (JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
                 FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT)
                VALUES ($1, $2, $3, 'PENDING', $4, $5, $6, NOW(), NOW())
            """
            self.master_db.execute(insert_sql, [
                job_id, version_id, reason, priority,
                fragments_needed, fragments_available
            ])
            
            logger.info(f"Created repair job {job_id} for version {version_id}: {reason}")
            return job_id
            
        except Exception as e:
            logger.error(f"Error creating repair job for {version_id}: {e}")
            return None
    
    async def scan_and_repair(self) -> Dict:
        """
        Scan all file versions and create repair jobs for any with missing fragments.
        Returns statistics about the scan.
        """
        stats = {
            "versions_scanned": 0,
            "healthy_versions": 0,
            "degraded_versions": 0,
            "repair_jobs_created": 0,
            "errors": 0,
            "scan_time": None
        }
        
        start_time = datetime.now(timezone.utc)
        
        try:
            logger.info("Starting active repair scan...")
            
            # Get all file versions
            versions = await self.get_all_versions_with_fragments()
            stats["versions_scanned"] = len(versions)
            
            if not versions:
                logger.info("No file versions found to scan")
                return stats
            
            repair_jobs_created = 0
            
            for version in versions:
                version_id = version.get("version_id")
                erasure_id = version.get("erasure_id", "MEDIUM")
                file_name = version.get("file_name", "unknown")
                
                try:
                    # Check fragment health
                    health = await self.get_fragment_health(version_id)
                    
                    if health["status"] == "ERROR":
                        stats["errors"] += 1
                        continue
                    
                    if health["status"] == "HEALTHY":
                        stats["healthy_versions"] += 1
                        continue
                    
                    # Version is degraded
                    stats["degraded_versions"] += 1
                    
                    # Get erasure coding profile to determine if reconstruction is possible
                    erasure_coder = get_erasure_coder_for_profile(erasure_id)
                    profile_info = erasure_coder.get_fragment_info()
                    k_fragments = profile_info["k"]
                    
                    available = health["available"]
                    missing = health["missing"]
                    
                    # Only create repair job if we can still reconstruct
                    # (have enough fragments) but some are missing
                    if available >= k_fragments and missing > 0:
                        # Determine priority based on how many fragments are available
                        # High priority: barely enough to reconstruct
                        # Medium priority: some redundancy remaining
                        # Low priority: most fragments available
                        if available <= k_fragments:
                            priority = 10  # CRITICAL - minimum fragments
                        elif available <= k_fragments + 1:
                            priority = 7   # HIGH - one redundant fragment
                        elif missing >= 2:
                            priority = 5   # MEDIUM - multiple missing
                        else:
                            priority = 3   # LOW - single missing fragment
                        
                        reason = f"Active scan: {missing} fragments missing on inactive nodes (file: {file_name})"
                        
                        job_id = await self.create_repair_job(
                            version_id=version_id,
                            reason=reason,
                            fragments_needed=missing,
                            fragments_available=available,
                            priority=priority
                        )
                        
                        if job_id:
                            repair_jobs_created += 1
                            logger.warning(
                                f"Created priority-{priority} repair job for {file_name}: "
                                f"{available}/{health['total_expected']} fragments available"
                            )
                            
                            # Stop if we've created too many jobs in one scan
                            if repair_jobs_created >= MAX_REPAIR_JOBS_PER_SCAN:
                                logger.warning(
                                    f"Reached max repair jobs per scan ({MAX_REPAIR_JOBS_PER_SCAN}), "
                                    "will continue next scan"
                                )
                                break
                    elif available < k_fragments:
                        # Cannot reconstruct - too many fragments lost
                        logger.error(
                            f"UNRECOVERABLE: File {file_name} (version {version_id}) "
                            f"only has {available}/{health['total_expected']} fragments "
                            f"(need {k_fragments} minimum)"
                        )
                        stats["errors"] += 1
                    
                except Exception as version_error:
                    logger.error(f"Error processing version {version_id}: {version_error}")
                    stats["errors"] += 1
                    continue
            
            stats["repair_jobs_created"] = repair_jobs_created
            
        except Exception as e:
            logger.error(f"Error during active repair scan: {e}", exc_info=True)
            stats["errors"] += 1
        
        finally:
            end_time = datetime.now(timezone.utc)
            scan_duration = (end_time - start_time).total_seconds()
            stats["scan_time"] = scan_duration
            
            # Log summary
            logger.info(
                f"Active repair scan complete in {scan_duration:.1f}s: "
                f"{stats['versions_scanned']} versions scanned, "
                f"{stats['healthy_versions']} healthy, "
                f"{stats['degraded_versions']} degraded, "
                f"{stats['repair_jobs_created']} repair jobs created, "
                f"{stats['errors']} errors"
            )
        
        return stats
    
    async def run(self):
        """Main service loop"""
        logger.info(f"Active repair service {SERVICE_ID} started")
        
        while True:
            try:
                await self.scan_and_repair()
            except Exception as e:
                logger.error(f"Error in service loop: {e}", exc_info=True)
            
            # Wait before next scan
            logger.info(f"Next scan in {SCAN_INTERVAL} seconds")
            await asyncio.sleep(SCAN_INTERVAL)


async def main():
    """Entry point"""
    service = ActiveRepairService()
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Active repair service shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
