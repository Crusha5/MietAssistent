import json
from datetime import date, datetime

from flask import has_request_context, request, session as flask_session
from sqlalchemy import event, inspect as sa_inspect

from app.extensions import db
from app.models import RevisionLog


def _current_user_context():
    if not has_request_context():
        return None, None, None
    return (
        flask_session.get('user_id'),
        request.remote_addr,
        request.headers.get('User-Agent'),
    )


def _serialize_value(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _build_snapshot(obj):
    data = {}
    mapper = obj.__mapper__
    for column in mapper.columns:
        if column.key in ['updated_at']:
            continue
        try:
            data[column.key] = _serialize_value(getattr(obj, column.key))
        except Exception:
            data[column.key] = None
    return data


def register_audit_listeners():
    """Registriert einfache Revisions-Logs für Einfügen/Ändern/Löschen."""

    @event.listens_for(db.session, 'after_flush')
    def receive_after_flush(session, flush_context):
        user_id, ip_address, user_agent = _current_user_context()

        # Inserts
        for obj in session.new:
            if isinstance(obj, RevisionLog):
                continue
            log = RevisionLog(
                table_name=getattr(obj, '__tablename__', obj.__class__.__name__),
                record_id=str(getattr(obj, 'id', None)),
                action='insert',
                user_id=user_id,
                changes=json.dumps({'data': _build_snapshot(obj)}, ensure_ascii=False),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            session.add(log)

        # Updates
        for obj in session.dirty:
            if isinstance(obj, RevisionLog):
                continue
            state = sa_inspect(obj)
            if not state.attrs:
                continue
            changes = {}
            for attr in state.attrs:
                if attr.key in ['updated_at']:
                    continue
                hist = attr.history
                if hist.has_changes():
                    old_val = hist.deleted[0] if hist.deleted else None
                    new_val = hist.added[0] if hist.added else getattr(obj, attr.key)
                    changes[attr.key] = {
                        'old': _serialize_value(old_val),
                        'new': _serialize_value(new_val)
                    }
            if changes:
                log = RevisionLog(
                    table_name=getattr(obj, '__tablename__', obj.__class__.__name__),
                    record_id=str(getattr(obj, 'id', None)),
                    action='update',
                    user_id=user_id,
                    changes=json.dumps(changes, ensure_ascii=False),
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                session.add(log)

        # Deletes
        for obj in session.deleted:
            if isinstance(obj, RevisionLog):
                continue
            log = RevisionLog(
                table_name=getattr(obj, '__tablename__', obj.__class__.__name__),
                record_id=str(getattr(obj, 'id', None)),
                action='delete',
                user_id=user_id,
                changes=json.dumps({'before': _build_snapshot(obj)}, ensure_ascii=False),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            session.add(log)

