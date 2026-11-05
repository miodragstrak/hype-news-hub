"""Server-controlled, credential-free account events in the caller's transaction."""
from sqlalchemy import text
from app.models.auth import SecurityEvent

ACCOUNT_ISSUER = "urn:hype-world-news:accounts"


def record_user_event(session, actor, target, action, outcome="success", previous=None):
    previous_role, previous_active = previous if previous else (None, None)
    event = SecurityEvent(
        actor_user_id=actor.id if actor else None,
        actor_issuer=ACCOUNT_ISSUER if actor else "urn:hype-world-news:bootstrap",
        actor_subject=str(actor.id) if actor else session.scalar(text("SELECT current_user")),
        target_user_id=target.id, action=action, outcome=outcome,
        previous_role=previous_role, new_role=target.role,
        previous_active=previous_active, new_active=target.active, target_revision=target.revision,
    )
    session.add(event)
