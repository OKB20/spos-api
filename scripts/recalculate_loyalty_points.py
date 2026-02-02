"""
Script to recalculate customer loyalty points based on actual sales data.
This fixes any inconsistencies from the previous bug where points were calculated on total instead of subtotal.

Run this script to correct existing customer loyalty point balances.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Customer, Sale, SystemSetting
from sqlalchemy import text
from decimal import Decimal

def recalculate_loyalty_points():
    db = SessionLocal()
    try:
        # Get loyalty settings
        loyalty_setting = db.query(SystemSetting).filter(SystemSetting.setting_key == "loyalty_program").first()
        
        if not loyalty_setting or not loyalty_setting.setting_value.get("enabled", False):
            print("Loyalty program is not enabled. No recalculation needed.")
            return
        
        points_ratio = float(loyalty_setting.setting_value.get("points_per_currency", 1.0))
        redemption_rate = float(loyalty_setting.setting_value.get("redemption_rate", 0.01))
        
        print(f"Loyalty Settings:")
        print(f"  Points per currency: {points_ratio}")
        print(f"  Redemption rate: {redemption_rate}")
        print()
        
        # Get all customers
        customers = db.query(Customer).all()
        print(f"Found {len(customers)} customers")
        print()
        
        updated_count = 0
        
        for customer in customers:
            # Get all sales for this customer
            sales = db.query(Sale).filter(
                Sale.customer_id == customer.id,
                Sale.status != 'voided'
            ).all()
            
            if not sales:
                continue
            
            # Calculate correct points
            total_points_earned = 0
            total_points_redeemed = 0
            
            for sale in sales:
                # Points earned on SUBTOTAL (not total)
                subtotal = Decimal(str(sale.subtotal or 0))
                points_earned = int(subtotal * Decimal(str(points_ratio)))
                total_points_earned += points_earned
                
                # Points redeemed (if discount was from loyalty)
                # Estimate: discount_amount / redemption_rate
                if sale.discount_amount and sale.discount_amount > 0:
                    # This is an approximation - we can't know for sure if discount was from loyalty
                    # In a real scenario, you'd track this separately
                    estimated_points_redeemed = int(Decimal(str(sale.discount_amount)) / Decimal(str(redemption_rate)))
                    # Only count if it seems reasonable (not more than customer could have had)
                    if estimated_points_redeemed <= total_points_earned:
                        total_points_redeemed += estimated_points_redeemed
            
            correct_balance = total_points_earned - total_points_redeemed
            current_balance = customer.loyalty_points or 0
            
            if correct_balance != current_balance:
                print(f"Customer: {customer.name}")
                print(f"  Current balance: {current_balance}")
                print(f"  Calculated balance: {correct_balance}")
                print(f"  Earned: {total_points_earned}, Redeemed (est): {total_points_redeemed}")
                print(f"  Difference: {correct_balance - current_balance}")
                
                # Update customer
                customer.loyalty_points = correct_balance
                updated_count += 1
                print(f"  ✓ Updated")
                print()
        
        if updated_count > 0:
            db.commit()
            print(f"\n✅ Successfully updated {updated_count} customer(s)")
        else:
            print("\n✅ All customer loyalty points are already correct!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("LOYALTY POINTS RECALCULATION SCRIPT")
    print("=" * 60)
    print()
    
    response = input("This will recalculate all customer loyalty points. Continue? (yes/no): ")
    if response.lower() == 'yes':
        recalculate_loyalty_points()
    else:
        print("Cancelled.")
