from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text 
from app.database import get_db 

router = APIRouter(
    prefix="/debug",
    tags=["debug-schema"],
)

@router.post("/add-account-status-column")
def add_account_status_column(db: Session = Depends(get_db)):
    db.execute(text("""
        ALTER TABLE account
        ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';
    """))
    db.commit()
    return {"detail": "status column ensured on account table"}
