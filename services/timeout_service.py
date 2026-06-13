from datetime import datetime
from database.session import SessionLocal
from database.models import RequestAcceptance, UserMetrics

def expire_price_deadlines():
    db = SessionLocal()
    expired = db.query(RequestAcceptance).filter(
        RequestAcceptance.price_submitted == False,
        RequestAcceptance.deadline_at < datetime.utcnow()
    ).all()

    for acc in expired:
        metrics = db.query(UserMetrics).filter(UserMetrics.user_id == acc.seller_id).first()
        if metrics:
            metrics.missed_price_deadlines += 1
            metrics.seller_score -= 5
            
        # Free up the slot for other sellers
        db.delete(acc) 
    
    db.commit()
    db.close()
    print(f"Cleared {len(expired)} expired seller slots.")