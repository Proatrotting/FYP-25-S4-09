import logging

logger = logging.getLogger(__name__)

async def handle_node_failure_event(node_id: str) -> int:
    """
    Stub: called when a node is marked inactive.
    Should create repair jobs and return how many were created.
    """
    logger.warning(f"[STUB] handle_node_failure_event called for node {node_id}")
    return 0
