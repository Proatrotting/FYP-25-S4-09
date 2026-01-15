"""
Heartbeat Monitor Service
Monitors node heartbeats and marks nodes as inactive if they miss heartbeats.
Runs as a standalone service alongside the repair worker.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# Python path already configured by container

from app.master_node_db import MasterNodeDB
from app.core.active_repair import handle_node_failure_event

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MASTER_NODE_URL = os.getenv("MASTER_NODE_URL", "http://localhost:8000")
CHECK_INTERVAL = int(os.getenv("HEARTBEAT_CHECK_INTERVAL", "30"))  # Check every 30 seconds
HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "45"))  # Mark inactive after 45 seconds
MONITOR_ID = os.getenv("MONITOR_ID", "heartbeat-monitor-1")


class HeartbeatMonitor:
    """Monitor that checks node heartbeats and updates is_active status"""
    
    def __init__(self):
        self.master_db = MasterNodeDB()
        logger.info(f"Heartbeat monitor {MONITOR_ID} initialized")
        logger.info(f"Master node URL: {MASTER_NODE_URL}")
        logger.info(f"Check interval: {CHECK_INTERVAL}s")
        logger.info(f"Heartbeat timeout: {HEARTBEAT_TIMEOUT}s")
    
    async def check_node_health(self):
        """Check all nodes and update is_active status based on heartbeat freshness"""
        try:
            # Get all nodes
            sql = """
                SELECT NODE_ID, HEARTBEAT_AT, IS_ACTIVE, NODE_ROLE
                FROM NODE
                ORDER BY NODE_ID
            """
            nodes = self.master_db.select(sql)
            
            if not nodes:
                logger.debug("No nodes found in database")
                return
            
            current_time = datetime.now(timezone.utc)
            timeout_threshold = timedelta(seconds=HEARTBEAT_TIMEOUT)
            
            nodes_checked = 0
            nodes_marked_inactive = 0
            nodes_marked_active = 0
            
            for node in nodes:
                node_id = node.get("node_id")
                heartbeat_at_str = node.get("heartbeat_at")
                is_active = node.get("is_active")
                node_role = node.get("node_role")
                
                if not heartbeat_at_str:
                    # Node never sent heartbeat, mark as inactive
                    if is_active:
                        logger.warning(f"Node {node_id} has no heartbeat record, marking inactive")
                        await self.mark_node_inactive(node_id)
                        nodes_marked_inactive += 1
                    nodes_checked += 1
                    continue
                
                # Parse heartbeat timestamp (handle both string and datetime objects)
                if isinstance(heartbeat_at_str, str):
                    # Parse ISO format timestamp: "2026-01-07 06:02:30.724+00" or "2026-01-07 06:02:30.724"
                    try:
                        # Try with timezone first
                        heartbeat_at = datetime.fromisoformat(heartbeat_at_str.replace('+00', '+00:00'))
                    except ValueError:
                        # Try without timezone
                        heartbeat_at = datetime.fromisoformat(heartbeat_at_str).replace(tzinfo=timezone.utc)
                else:
                    heartbeat_at = heartbeat_at_str
                
                # Ensure timezone-aware comparison
                if heartbeat_at.tzinfo is None:
                    heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
                
                # Calculate time since last heartbeat
                time_since_heartbeat = current_time - heartbeat_at
                
                if time_since_heartbeat > timeout_threshold:
                    # Heartbeat is stale, mark as inactive
                    if is_active:
                        logger.warning(
                            f"Node {node_id} ({node_role}) heartbeat timeout: "
                            f"{int(time_since_heartbeat.total_seconds())}s since last heartbeat, marking inactive"
                        )
                        await self.mark_node_inactive(node_id)
                        nodes_marked_inactive += 1
                else:
                    # Heartbeat is fresh, ensure node is marked active
                    if not is_active:
                        logger.info(
                            f"Node {node_id} ({node_role}) heartbeat recovered, marking active"
                        )
                        await self.mark_node_active(node_id)
                        nodes_marked_active += 1
                
                nodes_checked += 1
            
            # Log summary
            if nodes_marked_inactive > 0 or nodes_marked_active > 0:
                logger.info(
                    f"Health check complete: {nodes_checked} nodes checked, "
                    f"{nodes_marked_inactive} marked inactive, {nodes_marked_active} marked active"
                )
            else:
                logger.debug(f"Health check complete: {nodes_checked} nodes healthy")
                
        except Exception as e:
            logger.error(f"Error checking node health: {e}", exc_info=True)
    
    async def mark_node_inactive(self, node_id: str):
        """Mark a node as inactive and trigger repair jobs for affected fragments"""
        try:
            sql = """
                UPDATE NODE
                SET IS_ACTIVE = false
                WHERE NODE_ID = $1
            """
            self.master_db.execute(sql, [node_id])
            logger.info(f"Marked node {node_id} as inactive")
            
            # Trigger active repair system for failed node
            try:
                repair_jobs_created = await handle_node_failure_event(node_id)
                if repair_jobs_created > 0:
                    logger.warning(f"Created {repair_jobs_created} repair jobs for failed node {node_id}")
                else:
                    logger.info(f"No repair jobs needed for failed node {node_id}")
            except Exception as repair_error:
                logger.error(f"Error triggering repair for node {node_id}: {repair_error}")
                
        except Exception as e:
            logger.error(f"Error marking node {node_id} inactive: {e}")
    
    async def mark_node_active(self, node_id: str):
        """Mark a node as active"""
        try:
            sql = """
                UPDATE NODE
                SET IS_ACTIVE = true
                WHERE NODE_ID = $1
            """
            self.master_db.execute(sql, [node_id])
            logger.info(f"Marked node {node_id} as active")
        except Exception as e:
            logger.error(f"Error marking node {node_id} active: {e}")
    
    async def run(self):
        """Main monitoring loop"""
        logger.info(f"Heartbeat monitor {MONITOR_ID} started")
        
        while True:
            try:
                await self.check_node_health()
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            
            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)


async def main():
    """Entry point"""
    monitor = HeartbeatMonitor()
    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("Heartbeat monitor shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
