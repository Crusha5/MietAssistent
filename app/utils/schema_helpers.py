from sqlalchemy import inspect, text
from app.extensions import db


def ensure_archiving_columns():
    """Stellt sicher, dass Archivierungs-Spalten in zentralen Tabellen vorhanden sind."""
    inspector = inspect(db.engine)
    columns = {
        'contracts': {'is_archived': 'is_archived BOOLEAN DEFAULT 0'},
        'protocols': {'is_archived': 'is_archived BOOLEAN DEFAULT 0'},
        'meter_readings': {'is_archived': 'is_archived BOOLEAN DEFAULT 0'},
        'documents': {'is_archived': 'is_archived BOOLEAN DEFAULT 0'},
    }

    for table, defs in columns.items():
        if not inspector.has_table(table):
            continue
        existing = {col['name'] for col in inspector.get_columns(table)}
        missing = {name: ddl for name, ddl in defs.items() if name not in existing}
        if not missing:
            continue
        with db.engine.begin() as conn:
            for ddl in missing.values():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_user_landlord_flag():
    """Fügt Felder für Vermieterstatus an der Users-Tabelle hinzu."""
    inspector = inspect(db.engine)
    if not inspector.has_table('users'):
        return

    existing_columns = {col['name'] for col in inspector.get_columns('users')}

    with db.engine.begin() as conn:
        if 'is_landlord' not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_landlord BOOLEAN DEFAULT 0"))

        if 'landlord_id' not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN landlord_id VARCHAR(36)"))
