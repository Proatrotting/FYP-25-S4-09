from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import sys

# Configure logging to ensure all logs appear in docker logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Ensure logs go to stdout
    ]
)

# Set the root logger level
logging.getLogger().setLevel(logging.INFO)

# Also ensure uvicorn logs are visible
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

from app.routes.login import router as auth_router
from app.routes.userprofiles import router as userprofiles_router
from app.routes.update_user import router as update_user_router
from app.routes.create_folders import router as folders_router
from app.routes.storage_limits import router as storage_router
from app.routes.move_folders_and_files import router as move_router
from app.routes.delete_folders_and_files import folders_router as delete_folders_router, files_router as delete_files_router
from app.routes.password_recovery import router as password_recovery_router
from app.routes.activity_history import router as activity_history_router
from app.routes.account_management import router as account_management_router
from app.routes.upload_files import router as upload_files_router
from app.routes.download_files import router as download_files_router
from app.routes.search_folders_and_files import router as search_router
from app.routes.file_sharing import router as file_sharing_router
from app.routes.recycle_bin import router as recycle_bin_router
from app.routes.upload_folders import router as upload_folders_router
from app.routes.download_folders import router as download_folders_router
from app.routes.sysadmin_account_management import router as sysadmin_account_management_router
from app.routes.sysadmin_view_activity import router as sysadmin_view_activity_router
from app.routes.sysadmin_node_management import router as sysadmin_node_management_router
from app.routes.account_inspect import router as account_inspect_router # Testing route
from app.routes.add_status_column import router as add_status_column_router # Testing route
from app.heartbeat_test import router as heartbeat_test_router
# from app.routes.oneTimeDebugging import router as oneTimeDebugging_router

# Get maximum request size from environment variable (default 200MB)
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE", "209715200"))  # 200MB in bytes

app = FastAPI(
    title="FYP Secure File Sharing API", 
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "https://fyp25s409-shard.vercel.app",
    "https://fyp25s409-shard-git-cloud-variant-proatrottings-projects.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https://.*\.vercel\.app"
)

# Include routers
app.include_router(auth_router)
app.include_router(userprofiles_router)
app.include_router(update_user_router)
app.include_router(folders_router)
app.include_router(storage_router)
app.include_router(move_router)
app.include_router(delete_folders_router)
app.include_router(delete_files_router)
app.include_router(password_recovery_router)
app.include_router(activity_history_router)
app.include_router(account_management_router)
app.include_router(upload_files_router)
app.include_router(download_files_router)
app.include_router(search_router)
app.include_router(file_sharing_router)
app.include_router(recycle_bin_router)
app.include_router(upload_folders_router)
app.include_router(download_folders_router)
app.include_router(sysadmin_account_management_router)
app.include_router(sysadmin_view_activity_router)
app.include_router(sysadmin_node_management_router)
app.include_router(heartbeat_test_router)
# app.include_router(oneTimeDebugging_router)
app.include_router(account_inspect_router) # Testing route
app.include_router(add_status_column_router) # Testing route


# Health check
@app.get("/healthz")
def healthz() -> dict:
	return {"status": "ok"}

# Test master node connection
@app.get("/test/master-node-connection")
async def test_master_node_connection():
    """Test connection to master node database."""
    return {"status": "endpoint_working", "message": "Basic endpoint is functional"}

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Origin: {request.headers.get('origin')}")
    response = await call_next(request)
    print(f"CORS headers: {response.headers.get('access-control-allow-origin')}")
    return response
