#!/usr/bin/env python3
import os
import sys

print("=== Starting MietAssistent App ===")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")

# Prüfe Verzeichnisse
upload_root = os.environ.get('UPLOAD_ROOT', '/uploads')
protocol_dir = os.environ.get('UPLOAD_FOLDER', os.path.join(upload_root, 'protocolls'))


def _ensure_dir(path: str):
    """Legt ein Verzeichnis an, ohne beim Start abzubrechen."""
    directory = os.path.abspath(path)
    if os.path.exists(directory):
        return
    try:
        print(f"⚠️  Creating directory: {directory}")
        os.makedirs(directory, exist_ok=True)
    except PermissionError:
        # Keine Ausnahme hochwerfen, damit die App trotzdem startet
        print(f"❌ Keine Berechtigung zum Anlegen von {directory} – bitte Mount/Owner prüfen.")
    except Exception as exc:
        print(f"❌ Konnte Verzeichnis {directory} nicht anlegen: {exc}")


for raw_dir in ['data', upload_root, protocol_dir, 'logs']:
    _ensure_dir(raw_dir)

try:
    # Füge das aktuelle Verzeichnis zum Python-Pfad hinzu
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from app import create_app, db
    from app import _ensure_contract_protocol_columns

    app = create_app()

    with app.app_context():
        # Datenbank-Tabellen erstellen
        print("📦 Creating database tables...")
        db.create_all()
        print("✅ Database tables created")

        # Laufzeitmigration für alte Datenbanken absichern (insbesondere fehlende Sperrspalten)
        try:
            _ensure_contract_protocol_columns()
        except Exception as migration_exc:
            print(f"⚠️  Konnte Laufzeitmigration nicht ausführen: {migration_exc}")

        # Prüfen ob Setup bereits durchgeführt wurde
        from app.models import User
        users_count = User.query.count()
        if users_count == 0:
            print("⚠️  No users found - please run setup at /setup")
        else:
            print(f"✅ Found {users_count} users - setup completed")

    if __name__ == '__main__':
        print("🚀 Starting Flask server on port 5000...")
        print("📊 Access the application at: http://localhost:5000")
        app.run(host='0.0.0.0', port=5000, debug=False)

except Exception as e:
    print(f"❌ Failed to start app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
