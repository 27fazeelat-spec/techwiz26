"""Append-only audit trail (SRS Steps 48-49)."""
from database import db
from database.models import AuditLog


def record(action, entity_type, entity_id, actor=None, before=None, after=None,
           reason=None, version=None, detail=None, commit=True):
    entry = AuditLog(actor=actor or {"user_id": "system", "app_role": "system"}, action=action,
                     entity_type=entity_type, entity_id=str(entity_id), entity_version=version,
                     before=before, after=after, reason=reason, detail=detail)
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def actor_from_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return {"user_id": user.id, "email": user.email, "app_role": user.app_role}
