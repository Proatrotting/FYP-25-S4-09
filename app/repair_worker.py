"""
Repair Worker Service
Processes PENDING repair jobs by reconstructing missing fragments and redistributing them.
Runs as a standalone service that can be scaled independently.
"""
import asyncio
import logging
import os
import sys
import base64
import hashlib
import uuid
from typing import List, Dict, Optional
import httpx
import requests

# Python path already configured by container

from app.core.erasure_coding import get_erasure_coder_for_profile
from app.core.shamir_secret_sharing import reconstruct_key_from_shares, create_key_shares
from app.master_node_db import MasterNodeDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MASTER_NODE_URL = os.getenv("MASTER_NODE_URL", "http://localhost:8000")
REPAIR_INTERVAL = int(os.getenv("REPAIR_INTERVAL", "60"))  # Check every 60 seconds
MAX_CONCURRENT_REPAIRS = int(os.getenv("MAX_CONCURRENT_REPAIRS", "3"))
WORKER_ID = os.getenv("WORKER_ID", f"repair-worker-{uuid.uuid4().hex[:8]}")


class RepairWorker:
    """Worker that processes repair jobs from the REPAIR_JOBS table"""
    
    def __init__(self):
        self.master_db = MasterNodeDB()
        self.master_node_url = MASTER_NODE_URL
        self.active_repairs = 0
        logger.info(f"Repair worker {WORKER_ID} initialized")
        logger.info(f"Master node URL: {self.master_node_url}")
        logger.info(f"Check interval: {REPAIR_INTERVAL}s")
        logger.info(f"Max concurrent repairs: {MAX_CONCURRENT_REPAIRS}")
    
    async def get_pending_jobs(self) -> List[Dict]:
        """Fetch PENDING repair jobs ordered by priority"""
        try:
            sql = """
                SELECT JOB_ID, VERSION_ID, REASON, PRIORITY, 
                       FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT
                FROM REPAIR_JOBS 
                WHERE STATUS = 'PENDING'
                ORDER BY PRIORITY DESC, CREATED_AT ASC
                LIMIT $1
            """
            result = self.master_db.select(sql, [MAX_CONCURRENT_REPAIRS])
            logger.info(f"Query returned {len(result)} pending jobs")
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Error fetching pending jobs: {e}", exc_info=True)
            return []
    
    async def update_job_status(self, job_id: str, status: str, error_message: Optional[str] = None):
        """Update repair job status"""
        try:
            if error_message:
                sql = """
                    UPDATE REPAIR_JOBS 
                    SET STATUS = $1, ERROR_MESSAGE = $2, UPDATED_AT = NOW()
                    WHERE JOB_ID = $3
                """
                self.master_db.execute(sql, [status, error_message, job_id])
            else:
                sql = """
                    UPDATE REPAIR_JOBS 
                    SET STATUS = $1, UPDATED_AT = NOW()
                    WHERE JOB_ID = $2
                """
                self.master_db.execute(sql, [status, job_id])
            logger.info(f"Updated job {job_id} to status {status}")
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
    
    async def get_file_info(self, version_id: str) -> Optional[Dict]:
        """Get file information including erasure profile"""
        try:
            # Query database for file version info
            sql = """
                SELECT fv.VERSION_ID, fv.FILE_ID, fv.ERASURE_ID, fv.BYTES,
                       fo.FILE_NAME, fo.FILE_SIZE
                FROM FILE_VERSIONS fv
                JOIN FILE_OBJECTS fo ON fv.FILE_ID = fo.FILE_ID
                WHERE fv.VERSION_ID = $1
            """
            result = self.master_db.select(sql, [version_id])
            
            if result and len(result) > 0:
                return result[0]
            
            logger.error(f"Could not find file info for version {version_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting file info: {e}", exc_info=True)
            return None
    
    async def get_fragments_for_version(self, version_id: str) -> List[Dict]:
        """Get all fragments and their locations for a version"""
        try:
            sql = """
                SELECT ff.FRAGMENT_ID, ff.NUM_FRAGMENT, ff.SEGMENT_ID,
                       fl.NODE_ID, n.API_ENDPOINT
                FROM FILE_FRAGMENTS ff
                LEFT JOIN FRAGMENT_LOCATION fl ON ff.FRAGMENT_ID = fl.FRAGMENT_ID
                LEFT JOIN NODE n ON fl.NODE_ID = n.NODE_ID
                JOIN FILE_SEGMENTS fs ON ff.SEGMENT_ID = fs.SEGMENT_ID
                WHERE fs.VERSION_ID = $1
                ORDER BY ff.NUM_FRAGMENT
            """
            result = self.master_db.select(sql, [version_id])
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Error getting fragments: {e}", exc_info=True)
            return []
    
    async def download_fragment(self, fragment_id: str, api_endpoint: str) -> Optional[bytes]:
        """Download a fragment from a storage node"""
        try:
            fragment_url = f"{api_endpoint}/fragments/{fragment_id}"
            async with httpx.AsyncClient() as client:
                response = await client.get(fragment_url, timeout=30)
                if response.status_code == 200:
                    fragment_data = response.json()
                    if fragment_data.get("success") and fragment_data.get("data"):
                        return base64.b64decode(fragment_data["data"])
            logger.warning(f"Failed to download fragment {fragment_id} from {api_endpoint}")
            return None
        except Exception as e:
            logger.error(f"Error downloading fragment {fragment_id}: {e}")
            return None
    
    async def reconstruct_missing_fragments(
        self,
        erasure_coder,
        available_fragments: List[bytes],
        fragment_indexes: List[int],
        total_fragments: int
    ) -> Dict[int, bytes]:
        """Reconstruct missing fragments using Reed-Solomon"""
        try:
            # Decode to get original data
            original_data = erasure_coder.decode_data(available_fragments, fragment_indexes)
            logger.info(f"Reconstructed {len(original_data)} bytes from {len(available_fragments)} fragments")
            
            # Re-encode to generate all fragments
            all_fragments = erasure_coder.encode_data(original_data)
            logger.info(f"Re-encoded into {len(all_fragments)} fragments")
            
            # Find missing fragment indexes
            available_indexes = set(fragment_indexes)
            missing_fragments = {}
            
            for i in range(total_fragments):
                if i not in available_indexes:
                    missing_fragments[i] = all_fragments[i]
                    logger.info(f"Reconstructed missing fragment {i} ({len(all_fragments[i])} bytes)")
            
            return missing_fragments
        except Exception as e:
            logger.error(f"Error reconstructing fragments: {e}")
            raise
    
    async def upload_fragment_to_node(
        self,
        fragment_id: str,
        fragment_data: bytes,
        api_endpoint: str,
        file_id: str = "repaired",
        fragment_order: int = 0
    ) -> bool:
        """Upload a reconstructed fragment to a storage node"""
        try:
            upload_url = f"{api_endpoint}/fragments"
            encoded_data = base64.b64encode(fragment_data).decode()
            payload = {
                "fragmentId": fragment_id,  # camelCase for storage node
                "data": encoded_data,
                "bytes": len(fragment_data),
                "contentHash": "repaired",
                "fileId": file_id,
                "fragmentOrder": fragment_order
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(upload_url, json=payload, timeout=60)
                if response.status_code in [200, 201]:
                    logger.info(f"Successfully uploaded fragment {fragment_id} to {api_endpoint}")
                    return True
                else:
                    logger.error(f"Failed to upload fragment {fragment_id}: HTTP {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Error uploading fragment {fragment_id}: {e}")
            return False
    
    async def get_available_nodes(self, prefer_without_fragments: List[str] = None) -> List[Dict]:
        """
        Get available storage nodes for fragment placement.
        Prefers nodes without fragments from this file, but allows nodes with fragments as fallback.
        This ensures repair can complete even if all nodes already have fragments.
        """
        try:
            sql = """
                SELECT NODE_ID, API_ENDPOINT
                FROM NODE
                WHERE IS_ACTIVE = true 
                AND NODE_ROLE = 'STORAGE'
                ORDER BY NODE_ID
            """
            result = self.master_db.select(sql)
            nodes = result if isinstance(result, list) else []
            
            # Prioritize nodes: first without fragments, then with fragments
            if prefer_without_fragments:
                nodes_without_fragments = [n for n in nodes if n.get("node_id") not in prefer_without_fragments]
                nodes_with_fragments = [n for n in nodes if n.get("node_id") in prefer_without_fragments]
                # Return nodes without fragments first, then nodes with fragments
                return nodes_without_fragments + nodes_with_fragments
            
            return nodes
        except Exception as e:
            logger.error(f"Error getting available nodes: {e}", exc_info=True)
            return []
    
    async def update_fragment_location(
        self,
        fragment_id: str,
        node_id: str,
        fragment_address: str = "repaired/fragment",
        bytes_size: int = 0
    ) -> bool:
        """Update FRAGMENT_LOCATION table after successful upload"""
        try:
            # Check if location already exists
            check_sql = """
                SELECT COUNT(*) as count FROM FRAGMENT_LOCATION
                WHERE FRAGMENT_ID = $1
            """
            result = self.master_db.select(check_sql, [fragment_id])
            count = result[0].get("count", 0) if result else 0
            exists = int(count) > 0
            
            if exists:
                # Update existing location with new node
                update_sql = """
                    UPDATE FRAGMENT_LOCATION
                    SET NODE_ID = $2, STATUS = 'ACTIVE', LAST_CHECKED_AT = NOW()
                    WHERE FRAGMENT_ID = $1
                """
                self.master_db.execute(update_sql, [fragment_id, node_id])
            else:
                # Insert new location
                insert_sql = """
                    INSERT INTO FRAGMENT_LOCATION 
                    (FRAGMENT_ID, NODE_ID, FRAGMENT_ADDRESS, BYTES, STATUS, STORED_AT, LAST_CHECKED_AT)
                    VALUES ($1, $2, $3, $4, 'ACTIVE', NOW(), NOW())
                """
                self.master_db.execute(insert_sql, [fragment_id, node_id, fragment_address, bytes_size])
            
            logger.info(f"Updated fragment location for {fragment_id} on node {node_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating fragment location: {e}")
            return False
    
    async def process_repair_job(self, job: Dict):
        """Process a single repair job"""
        job_id = job["job_id"]
        version_id = job["version_id"]
        
        logger.info(f"Processing repair job {job_id} for version {version_id}")
        
        try:
            # Mark job as IN_PROGRESS
            await self.update_job_status(job_id, "IN_PROGRESS")
            
            # Get file info to determine erasure profile
            file_info = await self.get_file_info(version_id)
            if not file_info:
                raise Exception(f"Could not find file info for version {version_id}")
            
            erasure_id = file_info.get("erasure_id", "MEDIUM")
            logger.info(f"Using erasure profile: {erasure_id}")
            
            # Initialize erasure coder
            erasure_coder = get_erasure_coder_for_profile(erasure_id)
            profile_info = erasure_coder.get_fragment_info()
            k_fragments = profile_info["k"]
            total_fragments = profile_info["n"]
            
            # Get all fragments and their locations
            fragments = await self.get_fragments_for_version(version_id)
            if not fragments:
                raise Exception(f"No fragments found for version {version_id}")
            
            logger.info(f"Found {len(fragments)} fragment records")
            
            # Download available fragments
            available_fragments = []
            fragment_indexes = []
            missing_fragment_ids = []
            existing_node_ids = []
            segment_id = None
            
            for frag in fragments:
                fragment_id = frag.get("fragment_id")
                num_fragment = frag.get("num_fragment")
                api_endpoint = frag.get("api_endpoint")
                node_id = frag.get("node_id")
                
                if not segment_id:
                    segment_id = frag.get("segment_id")
                
                # Try to download if we have an API endpoint (node exists and is accessible)
                if api_endpoint and node_id:
                    fragment_data = await self.download_fragment(fragment_id, api_endpoint)
                    if fragment_data:
                        available_fragments.append(fragment_data)
                        fragment_indexes.append(num_fragment)
                        existing_node_ids.append(node_id)
                        logger.info(f"Downloaded fragment {num_fragment} ({len(fragment_data)} bytes)")
                    else:
                        missing_fragment_ids.append((fragment_id, num_fragment))
                else:
                    missing_fragment_ids.append((fragment_id, num_fragment))
            
            logger.info(f"Downloaded {len(available_fragments)} fragments, missing {len(missing_fragment_ids)}")
            
            # Check if we can reconstruct
            if len(available_fragments) < k_fragments:
                raise Exception(
                    f"Not enough fragments for reconstruction. "
                    f"Need {k_fragments}, got {len(available_fragments)}"
                )
            
            # Reconstruct missing fragments
            missing_fragments = await self.reconstruct_missing_fragments(
                erasure_coder,
                available_fragments,
                fragment_indexes,
                total_fragments
            )
            
            if not missing_fragments:
                logger.warning(f"No missing fragments to repair for job {job_id}")
                await self.update_job_status(job_id, "COMPLETED")
                return
            
            # Get available storage nodes (prefer nodes without fragments, but allow any active node)
            available_nodes = await self.get_available_nodes(prefer_without_fragments=existing_node_ids)
            if not available_nodes:
                raise Exception("No active storage nodes available")
            
            logger.info(f"Found {len(available_nodes)} available nodes for placement")
            
            # Upload reconstructed fragments
            successful_uploads = 0
            node_index = 0
            
            for fragment_id, num_fragment in missing_fragment_ids:
                if num_fragment not in missing_fragments:
                    continue
                
                fragment_data = missing_fragments[num_fragment]
                
                # Select a node (round-robin through available nodes)
                if node_index >= len(available_nodes):
                    node_index = 0
                
                target_node = available_nodes[node_index]
                node_id = target_node["node_id"]
                api_endpoint = target_node["api_endpoint"]
                
                # Upload fragment
                upload_success = await self.upload_fragment_to_node(
                    fragment_id,
                    fragment_data,
                    api_endpoint,
                    file_id=version_id,  # Use version_id as file_id
                    fragment_order=num_fragment
                )
                
                if upload_success:
                    # Update FRAGMENT_LOCATION
                    fragment_address = f"repaired/{version_id}/{num_fragment}_{fragment_id}.bin"
                    location_updated = await self.update_fragment_location(
                        fragment_id,
                        node_id,
                        fragment_address=fragment_address,
                        bytes_size=len(fragment_data)
                    )
                    
                    if location_updated:
                        successful_uploads += 1
                        logger.info(f"Successfully repaired fragment {num_fragment}")
                
                node_index += 1
            
            # Mark job as completed
            if successful_uploads > 0:
                logger.info(f"Repair job {job_id} completed: {successful_uploads} fragments repaired")
                await self.update_job_status(job_id, "COMPLETED")
            else:
                raise Exception("No fragments were successfully uploaded")
            
            # After repairing fragments, check and repair key shares if needed
            await self.check_and_repair_key_shares(version_id)
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Repair job {job_id} failed: {error_msg}")
            await self.update_job_status(job_id, "FAILED", error_msg)
    
    async def check_and_repair_key_shares(self, version_id: str):
        """
        Check if key shares are missing and repair them if needed.
        This ensures encryption keys remain recoverable even after node failures.
        """
        try:
            logger.info(f"Checking key shares for version {version_id}")
            
            # Get key_id for this version
            sql_key = """
                SELECT KEY_ID FROM FILE_KEYS WHERE VERSION_ID = $1
            """
            key_result = self.master_db.select(sql_key, [version_id])
            
            if not key_result or len(key_result) == 0:
                logger.warning(f"No encryption key found for version {version_id}")
                return
            
            key_id = key_result[0]["key_id"]
            logger.info(f"Found key_id: {key_id}")
            
            # Get all key shares and check which nodes are still active
            sql_shares = """
                SELECT ks.KEY_ID, ks.KEY_SHARE_ID, ks.NODE_ID, ks.FRAGMENT_ID,
                       ks.SHARE_ADDRESS, ks.SHARE_BYTES, n.IS_ACTIVE, n.API_ENDPOINT
                FROM KEY_SHARE ks
                LEFT JOIN NODE n ON ks.NODE_ID = n.NODE_ID
                WHERE ks.KEY_ID = $1
                ORDER BY ks.KEY_SHARE_ID
            """
            shares = self.master_db.select(sql_shares, [key_id])
            
            if not shares:
                logger.error(f"No key shares found for key_id {key_id}!")
                return
            
            # Separate active and inactive shares
            active_shares = [s for s in shares if s.get("is_active")]
            inactive_shares = [s for s in shares if not s.get("is_active")]
            
            total_shares = len(shares)
            active_count = len(active_shares)
            inactive_count = len(inactive_shares)
            
            logger.info(f"Key shares status: {active_count} active, {inactive_count} inactive out of {total_shares} total")
            
            # Check if repair is needed (if any shares are on inactive nodes)
            if inactive_count == 0:
                logger.info("All key shares are on active nodes. No repair needed.")
                return
            
            # Check if we have enough shares to reconstruct (need 5 for 5-of-7 threshold)
            threshold = 5
            if active_count < threshold:
                logger.error(
                    f"CRITICAL: Only {active_count} key shares available, need {threshold}. "
                    f"Cannot reconstruct encryption key! File is unrecoverable!"
                )
                return
            
            logger.warning(f"Key share repair needed: {inactive_count} shares on failed nodes")
            
            # Download active shares from storage nodes
            logger.info(f"Downloading {active_count} active key shares...")
            downloaded_shares = []
            
            for share in active_shares:
                share_id = share["key_share_id"]
                fragment_id = share.get("fragment_id")
                api_endpoint = share.get("api_endpoint")
                
                if not fragment_id or not api_endpoint:
                    logger.warning(f"Share {share_id} missing fragment_id or endpoint")
                    continue
                
                try:
                    # Download share from storage node (stored as fragment)
                    async with httpx.AsyncClient() as client:
                        url = f"{api_endpoint}/fragments/{fragment_id}"
                        response = await client.get(url, timeout=30)
                        
                        if response.status_code == 200:
                            fragment_data = response.json()
                            if fragment_data.get("success") and fragment_data.get("data"):
                                share_bytes = base64.b64decode(fragment_data["data"])
                                downloaded_shares.append({
                                    "share_index": share_id,
                                    "share_data": share_bytes
                                })
                                logger.info(f"Downloaded share {share_id} ({len(share_bytes)} bytes)")
                            else:
                                logger.warning(f"Share {share_id} has no data")
                        else:
                            logger.warning(f"Failed to download share {share_id}: HTTP {response.status_code}")
                
                except Exception as e:
                    logger.error(f"Error downloading share {share_id}: {e}")
                    continue
            
            if len(downloaded_shares) < threshold:
                logger.error(f"Only downloaded {len(downloaded_shares)} shares, need {threshold}. Cannot repair.")
                return
            
            logger.info(f"Successfully downloaded {len(downloaded_shares)} shares")
            
            # Reconstruct the encryption key from available shares
            logger.info("Reconstructing encryption key from shares...")
            try:
                encryption_key = reconstruct_key_from_shares(downloaded_shares)
                logger.info(f"Successfully reconstructed encryption key ({len(encryption_key)} bytes)")
            except Exception as e:
                logger.error(f"Failed to reconstruct key: {e}")
                return
            
            # Create new 7-share set
            logger.info("Creating new key share set (7 shares)...")
            try:
                new_shares = create_key_shares(encryption_key)
                logger.info(f"Created {len(new_shares)} new key shares")
            except Exception as e:
                logger.error(f"Failed to create new shares: {e}")
                return
            
            # Get available storage nodes for new shares
            available_nodes = await self.get_available_nodes()
            if len(available_nodes) < 7:
                logger.warning(f"Only {len(available_nodes)} nodes available, need 7 for optimal distribution")
            
            # Delete old inactive shares and upload new shares
            logger.info("Redistributing key shares to active nodes...")
            successful_redistributions = 0
            
            for inactive_share in inactive_shares:
                old_share_id = inactive_share["key_share_id"]
                
                # Delete old share record
                delete_sql = "DELETE FROM KEY_SHARE WHERE KEY_ID = $1 AND KEY_SHARE_ID = $2"
                self.master_db.execute(delete_sql, [key_id, old_share_id])
                logger.info(f"Deleted inactive share {old_share_id}")
                
                # Upload new share to replacement node
                if old_share_id - 1 < len(new_shares):
                    new_share = new_shares[old_share_id - 1]
                    
                    # Select a node (prefer nodes without shares)
                    existing_node_ids = [s["node_id"] for s in active_shares]
                    preferred_nodes = [n for n in available_nodes if n["node_id"] not in existing_node_ids]
                    target_nodes = preferred_nodes if preferred_nodes else available_nodes
                    
                    if not target_nodes:
                        logger.error("No available nodes for share redistribution")
                        continue
                    
                    target_node = target_nodes[successful_redistributions % len(target_nodes)]
                    node_id = target_node["node_id"]
                    api_endpoint = target_node["api_endpoint"]
                    
                    # Upload share as fragment to storage node
                    fragment_id = str(uuid.uuid4())
                    share_data = new_share["share_data"]
                    
                    upload_success = await self.upload_fragment_to_node(
                        fragment_id=fragment_id,
                        fragment_data=share_data,
                        api_endpoint=api_endpoint,
                        file_id=f"keyshare_{key_id}",
                        fragment_order=new_share["share_index"]
                    )
                    
                    if upload_success:
                        # Insert new share record
                        insert_sql = """
                            INSERT INTO KEY_SHARE 
                            (KEY_ID, KEY_SHARE_ID, NODE_ID, SHARE_BYTES, SHARE_ADDRESS, FRAGMENT_ID)
                            VALUES ($1, $2, $3, $4, $5, $6)
                        """
                        self.master_db.execute(insert_sql, [
                            key_id,
                            old_share_id,
                            node_id,
                            len(share_data),
                            f"keyshare/{key_id}/{old_share_id}",
                            fragment_id
                        ])
                        
                        successful_redistributions += 1
                        logger.info(f"Redistributed share {old_share_id} to node {node_id}")
            
            if successful_redistributions > 0:
                logger.info(f"Key share repair completed: {successful_redistributions} shares redistributed")
            else:
                logger.warning("No key shares were successfully redistributed")
        
        except Exception as e:
            logger.error(f"Error in key share repair: {e}", exc_info=True)
    
    async def run(self):
        """Main worker loop"""
        logger.info(f"Repair worker {WORKER_ID} started")
        
        while True:
            try:
                # Get pending jobs
                logger.info("Checking for pending repair jobs...")
                pending_jobs = await self.get_pending_jobs()
                
                if pending_jobs:
                    logger.info(f"Found {len(pending_jobs)} pending repair jobs")
                    
                    # Process jobs concurrently
                    tasks = [self.process_repair_job(job) for job in pending_jobs]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    logger.info("No pending repair jobs found")
                
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
            
            # Wait before next check
            logger.info(f"Waiting {REPAIR_INTERVAL} seconds before next check...")
            await asyncio.sleep(REPAIR_INTERVAL)


async def main():
    """Entry point"""
    worker = RepairWorker()
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Repair worker shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
