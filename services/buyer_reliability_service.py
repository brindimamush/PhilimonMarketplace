from database.session import SessionLocal
from database.models import UserMetrics, PurchaseRequest

def can_create_request(user_id: int) -> tuple[bool, str]:
    db = SessionLocal()
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    
    if not metrics:
        metrics = UserMetrics(user_id=user_id)
        db.add(metrics)
        db.commit()

    if metrics.suspended:
        db.close()
        return False, "⛔ Account suspended. Contact support."

    active_count = db.query(PurchaseRequest).filter(
        PurchaseRequest.buyer_id == user_id,
        PurchaseRequest.status.in_(["REQUEST_OPEN", "DEAL_PENDING_ADMIN"])
    ).count()

    score = metrics.buyer_score
    limit = 3 # Normal Buyer
    
    if score > 120:
        limit = 5 # Good Buyer
    elif score < 40:
        limit = 0 # Suspicious Buyer
    elif score < 70:
        limit = 1 # Risk Buyer

    if limit == 0:
        db.close()
        return False, "⚠️ Score too low. New requests blocked. Admin review required."
    
    if active_count >= limit:
        db.close()
        return False, f"⚠️ Limit reached ({active_count}/{limit} active requests allowed based on your score)."

    db.close()
    return True, ""

def record_request_completed(user_id: int):
    db = SessionLocal()
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    if metrics:
        metrics.completed_purchases += 1
        metrics.buyer_score += 2
        db.commit()
    db.close()