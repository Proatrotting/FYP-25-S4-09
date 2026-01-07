"""
Lazy Repair System
Detects missing fragments during file downloads and creates repair jobs via master-node API.
"""
import logging
import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class LazyRepair:
    """Creates repair jobs when fragments are missing but reconstruction is still possible."""
    
    def __init__(self):
        """Initialize with master-node URL from settings."""
        self.master_node_url = settings.master_node_url
    
    async def check_and_create_repair_job(
        self,
        version_id: str,
        total_fragments_expected: int,
        fragments_available: int
    ) -> bool:
        """
        Check if repair is needed and create a job if necessary.
        
        Args:
            version_id: File version ID
            total_fragments_expected: Total fragments that should exist
            fragments_available: How many fragments we currently have
            
        Returns:
            True if repair job was created, False otherwise
        """
        try:
            # Check if we're missing fragments
            if fragments_available >= total_fragments_expected:
                logger.debug(f"All {total_fragments_expected} fragments available for {version_id}")
                return False
            
            fragments_missing = total_fragments_expected - fragments_available
            logger.warning(f"Missing {fragments_missing} fragments for version {version_id}")
            
            # Create repair job via master-node API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.master_node_url}/repair-jobs",
                    json={
                        "version_id": version_id,
                        "reason": f"Lazy repair: missing {fragments_missing} fragments detected during download",
                        "priority": 5,  # Medium priority
                        "fragments_needed": fragments_missing,
                        "fragments_available": fragments_available
                    },
                    timeout=10.0
                )
                
                if response.status_code in [200, 201]:
                    result = response.json()
                    if result.get("created"):
                        logger.info(f"Created lazy repair job {result.get('job_id')} for version {version_id}")
                        return True
                    else:
                        logger.info(f"Repair job already exists for version {version_id}")
                        return False
                else:
                    logger.error(f"Failed to create repair job: HTTP {response.status_code} - {response.text}")
                    return False
            
        except Exception as e:
            logger.error(f"Error creating lazy repair job for {version_id}: {e}")
            return False
