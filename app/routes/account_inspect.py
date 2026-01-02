from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, text
from app.database import SessionLocal
from app.models import Account  

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/debug/account-columns")
def get_account_columns(db: Session = Depends(get_db)):
    result = db.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'account';
    """))
    cols = [row[0] for row in result.fetchall()]
    return {"columns": cols}