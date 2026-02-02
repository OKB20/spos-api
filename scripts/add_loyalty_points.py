from sqlalchemy import text
from app.db import SessionLocal

def migrate():
    db = SessionLocal()
    try:
        # Check if column exists
        check_sql = "SELECT column_name FROM information_schema.columns WHERE table_name='customers' AND column_name='loyalty_points';"
        result = db.execute(text(check_sql)).fetchone()
        
        if not result:
            print("Adding loyalty_points column to customers table...")
            db.execute(text("ALTER TABLE customers ADD COLUMN loyalty_points INTEGER DEFAULT 0;"))
            db.commit()
            print("Migration successful: Added loyalty_points column.")
        else:
            print("Column loyalty_points already exists. Skipping.")
    except Exception as e:
        print(f"Migration failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
