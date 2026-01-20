# app/master_node_db.py
import requests
import os
from typing import Any, Dict, List, Optional
from datetime import date, datetime

try:
    # If this module is used inside FastAPI, jsonable_encoder is the safest encoder.
    from fastapi.encoders import jsonable_encoder  # type: ignore
except Exception:  # pragma: no cover
    jsonable_encoder = None


def _json_safe(value: Any) -> Any:
    """
    Convert common non-JSON-serializable Python types into JSON-safe primitives.

    This prevents `requests.post(..., json=payload)` from crashing when params contain
    `datetime`, `date`, etc.
    """
    if jsonable_encoder is not None:
        return jsonable_encoder(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value

class MasterNodeDB:
    """Database interface that connects to master node instead of direct database"""
    
    def __init__(self):
        # Default to localhost:8000 for local development (master node exposed on port 8000)
        # In Docker, use MASTER_NODE_URL environment variable (http://master_node:3000)
        self.master_node_url = os.getenv("MASTER_NODE_URL", "http://localhost:8000")
        self.query_endpoint = f"{self.master_node_url}/query"
    
    def execute_query(self, sql: str, params: List[Any] = None) -> Dict[str, Any]:
        """Execute a SQL query through the master node"""
        try:
            payload = {
                "sql": sql,
                "params": _json_safe(params or [])
            }
            
            response = requests.post(self.query_endpoint, json=payload, timeout=10)
            
            # Log the response for debugging
            if response.status_code != 200:
                print(f"Master node error: Status {response.status_code}, Body: {response.text}")
            
            response.raise_for_status()
            
            return response.json()
        
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"Failed to connect to master node at {self.master_node_url}. Is the master node running? Error: {str(e)}")
        except requests.exceptions.Timeout as e:
            raise Exception(f"Timeout connecting to master node at {self.master_node_url}. Error: {str(e)}")
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    # Try to get JSON error details
                    error_json = e.response.json()
                    error_detail = error_json.get('error', error_json.get('detail', error_detail))
                    print(f"Master node JSON error: {error_json}")
                except:
                    # Fall back to text response
                    error_detail = e.response.text or error_detail
                    print(f"Master node text error: {error_detail}")
            print(f"Request exception details: {error_detail}")
            raise Exception(f"Failed to execute query on master node: {error_detail}")
    
    def select(self, sql: str, params: List[Any] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results"""
        result = self.execute_query(sql, params)
        if result.get("success"):
            return result.get("data", [])
        else:
            raise Exception(f"Query failed: {result}")
    
    def execute(self, sql: str, params: List[Any] = None) -> Dict[str, Any]:
        """Execute INSERT, UPDATE, DELETE queries"""
        result = self.execute_query(sql, params)
        if result.get("success"):
            return result.get("data", {})
        else:
            raise Exception(f"Query failed: {result}")
    
    def get_nodes(self) -> List[Dict[str, Any]]:
        """Get all storage nodes from master node"""
        try:
            response = requests.get(f"{self.master_node_url}/nodes")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get nodes: {str(e)}")
    
    def get_file_fragments(self, file_id: str) -> List[Dict[str, Any]]:
        """Get fragments for a specific file"""
        try:
            response = requests.get(f"{self.master_node_url}/fragments/{file_id}")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to get file fragments: {str(e)}")
    
    def store_fragment_info(self, file_id: str, node_id: str, fragment_order: int, 
                           fragment_size: int, fragment_hash: str) -> Dict[str, Any]:
        """Store fragment information in master node database"""
        try:
            payload = {
                "fileId": file_id,
                "nodeId": node_id,
                "fragmentOrder": fragment_order,
                "fragmentSize": fragment_size,
                "fragmentHash": fragment_hash
            }
            
            response = requests.post(f"{self.master_node_url}/fragments", json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to store fragment info: {str(e)}")

# Global instance
master_db = MasterNodeDB()

def get_master_db() -> MasterNodeDB:
    """Get master node database instance for FastAPI dependency injection"""
    return master_db

# Legacy alias for backward compatibility
def get_master_node_db() -> MasterNodeDB:
    """Get master node database instance (deprecated, use get_master_db)"""
    return master_db