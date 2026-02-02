import sys
import os
from sqlalchemy import func
from sqlalchemy.orm import Session

# Add the parent directory to sys.path to import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import SessionLocal
from app.models import Customer, Sale

def recalculate():
    db: Session = SessionLocal()
    try:
        customers = db.query(Customer).all()
        for customer in customers:
            # Sum up all non-voided sales for this customer
            total = db.query(func.sum(Sale.total_amount))\
                .filter(Sale.customer_id == customer.id)\
                .filter(Sale.status != 'voided')\
                .scalar() or 0
            
            # Find the date of the last non-voided sale
            last_sale_date = db.query(func.max(Sale.sale_date))\
                .filter(Sale.customer_id == customer.id)\
                .filter(Sale.status != 'voided')\
                .scalar()
            
            customer.total_purchases = total
            customer.last_purchase_date = last_sale_date
            print(f"Updated customer {customer.name}: Total = {total}, Last Sale = {last_sale_date}")
        
        db.commit()
        print("Recalculation complete.")
    finally:
        db.close()

if __name__ == "__main__":
    recalculate()
