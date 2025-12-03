from flask import Flask, jsonify
import json
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint
from datetime import datetime
import os

# Import extensions from extensions module
from app.extensions import db, jwt
from app.utils.project_profile import load_project_profile
from app.utils.schema_helpers import ensure_user_landlord_flag
from app.utils.audit import register_audit_listeners

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
    data_dir = os.path.abspath('data')
    os.makedirs(data_dir, exist_ok=True)

    upload_root = os.path.abspath(os.environ.get('UPLOAD_ROOT') or '/uploads')
    protocol_dir = os.path.abspath(os.environ.get('UPLOAD_FOLDER') or os.path.join(upload_root, 'protocolls'))

    # Verzeichnisse vorbereiten (Warnung statt Fallback bei fehlenden Rechten)
    try:
        os.makedirs(upload_root, exist_ok=True)
        os.makedirs(protocol_dir, mode=0o755, exist_ok=True)
        for sub in ['contracts', 'documents', 'meter_photos', 'costs']:
            os.makedirs(os.path.join(upload_root, sub), mode=0o755, exist_ok=True)
    except PermissionError:
        print(f"❌ Keine Berechtigung für Upload-Verzeichnisse unter {upload_root}. Bitte Mount/Owner prüfen.")

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(data_dir, 'rental.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-me')
    app.config['UPLOAD_ROOT'] = upload_root
    app.config['UPLOAD_FOLDER'] = protocol_dir
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get('PREFERRED_URL_SCHEME', 'https')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    
    # Session Configuration
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 Stunde
    app.config['SESSION_KEY_PREFIX'] = 'mietassistent_'
    
    # Initialize extensions with app
    db.init_app(app)
    jwt.init_app(app)
    CORS(app)
    register_audit_listeners()
    
    # Swagger UI configuration
    SWAGGER_URL = '/api/docs'
    API_URL = '/static/swagger.json'
    
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={
            'app_name': "MietAssistent API"
        }
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)
    
    # Add shared helpers to Jinja2
    @app.context_processor
    def utility_processor():
        status_labels = {
            'draft': 'Entwurf',
            'active': 'Aktiv',
            'terminated': 'Beendet',
            'expired': 'Abgelaufen',
            'pending': 'Ausstehend',
            'archived': 'Archiviert'
        }

        def translate_status(value):
            return status_labels.get(value, value)

        return {
            "now": datetime.now,
            "project_profile": load_project_profile(),
            "translate_status": translate_status,
        }

    @app.context_processor
    def inject_user_preferences():
        from flask import session
        prefs = {}
        try:
            from app.models import UserPreference

            user_id = session.get('user_id')
            if user_id:
                pref_row = UserPreference.query.filter_by(user_id=user_id).first()
                if pref_row and pref_row.preferences:
                    prefs = json.loads(pref_row.preferences)
        except Exception as e:
            print(f"⚠️  Could not load user preferences: {e}")

        return dict(user_preferences=prefs)
    
    # Register blueprints first to avoid circular imports
    register_blueprints(app)

    # Then initialize database
    initialize_database(app)

    # Falls die Runtime-Migration aufgrund alter Datenbanken nicht griff, einmal pro Prozess nachziehen
    _register_runtime_migration_hook(app)

    # Add context processor for buildings after database is initialized
    @app.context_processor
    def inject_buildings():
        """INJEKTIERE GEBÄUDE IN ALLE TEMPLATES"""
        from app.models import Building
        try:
            buildings = Building.query.all()
            return dict(all_buildings=buildings)
        except Exception as e:
            print(f"⚠️  Could not load buildings for context processor: {e}")
            return dict(all_buildings=[])
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Resource not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500
    
    @app.errorhandler(413)
    def too_large(error):
        return jsonify({'error': 'File too large'}), 413

    # Health check endpoint
    @app.route('/health')
    def health_check():
        try:
            # Test database connection
            db.session.execute('SELECT 1')
            db_status = 'connected'
        except Exception as e:
            db_status = f'disconnected: {str(e)}'
        
        return jsonify({
            'status': 'healthy',
            'database': db_status,
            'timestamp': datetime.now().isoformat()
        })
    
    # Root endpoint - redirect to dashboard if logged in, otherwise to login
    @app.route('/')
    def index():
        from flask import redirect, session
        from app.models import User
        
        # If no users exist, redirect to setup
        if not User.query.first():
            return redirect('/setup')
        
        # If user is logged in, redirect to dashboard
        if 'user_id' in session:
            return redirect('/dashboard')
        
        # Otherwise redirect to login
        return redirect('/auth/login')
        

    # Debug endpoint to check database status
    @app.route('/debug/db-status')
    def debug_db_status():
        try:
            from app.models import Apartment, Building
            apartment_count = Apartment.query.count()
            building_count = Building.query.count()
            
            return jsonify({
                'database': 'connected',
                'apartments_count': apartment_count,
                'buildings_count': building_count,
                'tables_accessible': True
            })
        except Exception as e:
            return jsonify({
                'database': 'error',
                'error': str(e)
            }), 500

    # Debug Route zum Prüfen aller registrierten Routes
    @app.route('/debug/routes')
    def debug_routes():
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append({
                'endpoint': rule.endpoint,
                'methods': list(rule.methods),
                'path': rule.rule
            })
        return jsonify(routes)
    
    print("🚀 Starting Flask server on port 5000...")
    print("📊 Access the application at: http://localhost:5000")
    
    return app

def register_blueprints(app):
    """Register all blueprints to avoid circular imports"""
    print("📋 Registering blueprints...")
    
    # Setup Routes (Web only)
    try:
        from app.routes.setup import setup_bp
        app.register_blueprint(setup_bp, url_prefix='/setup')
        print("✅ Setup routes registered")
    except ImportError as e:
        print(f"❌ Failed to import setup routes: {e}")
    
    # Auth Routes (Web routes only)
    try:
        from app.routes.auth import auth_bp
        app.register_blueprint(auth_bp, url_prefix='/auth')
        # Zusätzliche API-Route für externe Clients
        try:
            app.add_url_rule('/api/auth/logout', view_func=auth_bp.view_functions['auth.api_logout'], methods=['POST'])
        except KeyError:
            pass
        print("✅ Auth routes registered")
    except ImportError as e:
        print(f"❌ Failed to import auth routes: {e}")
    
    # Main Routes (Web only)
    try:
        from app.routes.main import main_bp
        app.register_blueprint(main_bp)
        print("✅ Main routes registered")
    except ImportError as e:
        print(f"❌ Failed to import main routes: {e}")
    
    # Apartments Routes (Web routes only)
    try:
        from app.routes.apartments import apartments_bp
        app.register_blueprint(apartments_bp, url_prefix='/apartments')
        print("✅ Apartment routes registered")
    except ImportError as e:
        print(f"❌ Failed to import apartment routes: {e}")

    # Tenants Routes (Web routes only)
    try:
        from app.routes.tenants import tenants_bp
        app.register_blueprint(tenants_bp, url_prefix='/tenants')
        print("✅ Tenant routes registered")
    except ImportError as e:
        print(f"❌ Failed to import tenant routes: {e}")

    # Meter Readings Routes (Web routes only)
    try:
        from app.routes.meter_readings import meter_bp
        app.register_blueprint(meter_bp, url_prefix='/meter-readings')
        print("✅ Meter reading routes registered")
    except ImportError as e:
        print(f"❌ Failed to import meter reading routes: {e}")

    # Meter Management Routes (Web routes only)
    try:
        from app.routes.meters import meters_bp
        app.register_blueprint(meters_bp, url_prefix='/meters')
        print("✅ Meter management routes registered")
    except ImportError as e:
        print(f"❌ Failed to import meter management routes: {e}")

    # Documents Routes (Web routes only)
    try:
        from app.routes.documents import documents_bp
        app.register_blueprint(documents_bp, url_prefix='/documents')
        print("✅ Document routes registered")
    except ImportError as e:
        print(f"❌ Failed to import document routes: {e}")

    # Settlements Routes (Web routes only)
    try:
        from app.routes.settlements import settlements_bp
        app.register_blueprint(settlements_bp, url_prefix='/settlements')
        print("✅ Settlement routes registered")
    except ImportError as e:
        print(f"❌ Failed to import settlement routes: {e}")

    # Buildings Routes (Web routes only)
    try:
        from app.routes.buildings import buildings_bp
        app.register_blueprint(buildings_bp, url_prefix='/buildings')
        print("✅ Buildings routes registered")
    except ImportError as e:
        print(f"❌ Failed to import buildings routes: {e}")

    # Meter Types Routes
    try:
        from app.routes.meter_types import meter_types_bp
        app.register_blueprint(meter_types_bp, url_prefix='/meter-types')
        print("✅ Meter types routes registered")
    except ImportError as e:
        print(f"❌ Failed to import meter types routes: {e}")

    # Contract Routes
    try:
        from app.routes.contracts import contracts_bp
        app.register_blueprint(contracts_bp, url_prefix='/contracts')
        print("✅ Contract routes registered at /contracts")
    except ImportError as e:
        print(f"❌ Failed to import contract routes: {e}")

    # Contract Templates Routes
    try:
        from app.routes.contract_templates import templates_bp
        app.register_blueprint(templates_bp, url_prefix='/contract-templates')
        print("✅ Contract templates routes registered")
    except ImportError as e:
        print(f"❌ Failed to import contract templates routes: {e}")

    # Protocols Routes
    try:
        from app.routes.protocols import protocols_bp
        app.register_blueprint(protocols_bp, url_prefix='/protocols')
        print("✅ Protocol routes registered")
    except ImportError as e:
        print(f"❌ Failed to import protocol routes: {e}")

    try:
        from app.routes.costs import costs_bp
        app.register_blueprint(costs_bp)
        print("✅ Costs routes registered")
    except ImportError as e:
        print(f"⚠️  Costs routes not available: {e}")

    try:
        from app.routes.reports import reports_bp
        app.register_blueprint(reports_bp)
        print("✅ Reports routes registered")
    except ImportError as e:
        print(f"⚠️  Reports routes not available: {e}")

    try:
        from app.routes.settings import settings_bp
        app.register_blueprint(settings_bp)
        print("✅ Settings routes registered")
    except ImportError as e:
        print(f"⚠️  Settings routes not available: {e}")

        # Contract Editor Routes
    try:
        from app.routes.contract_editor import contract_editor_bp
        app.register_blueprint(contract_editor_bp)
        print("✅ Contract editor routes registered")
    except ImportError as e:
        print(f"❌ Failed to import contract editor routes: {e}")

    try:
        from app.routes.contract_editor import landlords_api_bp
        app.register_blueprint(landlords_api_bp)
        print("✅ Landlord API routes registered")
    except ImportError as e:
        print(f"⚠️  Landlord API routes not available: {e}")

    try:
        from app.routes.users import users_bp
        app.register_blueprint(users_bp)
        print("✅ User routes registered")
    except ImportError as e:
        print(f"⚠️  User routes not available: {e}")

    try:
        from app.routes.buildings import buildings_api_bp
        app.register_blueprint(buildings_api_bp, url_prefix='/api/buildings')
        print("✅ Buildings API routes registered")
    except ImportError as e:
        print(f"⚠️  Buildings API routes not available: {e}")

    # Apartments API Routes (separate registration)
    try:
        from app.routes.apartments import apartments_api_bp
        app.register_blueprint(apartments_api_bp, url_prefix='/api/apartments')
        print("✅ Apartments API routes registered")
    except ImportError as e:
        print(f"⚠️  Apartments API routes not available: {e}")

    # Tenants API Routes (separate registration)
    try:
        from app.routes.tenants import tenants_api_bp
        app.register_blueprint(tenants_api_bp, url_prefix='/api/tenants')
        print("✅ Tenants API routes registered")
    except ImportError as e:
        print(f"⚠️  Tenants API routes not available: {e}")

    # Meter Readings API Routes (separate registration)
    try:
        from app.routes.meter_readings import meter_readings_api_bp
        app.register_blueprint(meter_readings_api_bp, url_prefix='/api/meter-readings')
        print("✅ Meter readings API routes registered")
    except ImportError as e:
        print(f"⚠️  Meter readings API routes not available: {e}")

    # Documents API Routes (separate registration)
    try:
        from app.routes.documents import documents_api_bp
        app.register_blueprint(documents_api_bp, url_prefix='/api/documents')
        print("✅ Documents API routes registered")
    except ImportError as e:
        print(f"⚠️  Documents API routes not available: {e}")

    # Settlements API Routes (separate registration)
    try:
        from app.routes.settlements import settlements_api_bp
        app.register_blueprint(settlements_api_bp, url_prefix='/api/settlements')
        print("✅ Settlements API routes registered")
    except ImportError as e:
        print(f"⚠️  Settlements API routes not available: {e}")

    # Settings Routes (optional - if they exist)
    # RSS Feeds Routes
    try:
        from app.routes.rss_feeds import rss_bp
        app.register_blueprint(rss_bp, url_prefix='/rss')
        print("✅ RSS feeds routes registered")
        
        # Standard-RSS-Feeds initialisieren - NUR im App-Kontext
        def init_rss_feeds():
            try:
                from app.routes.rss_feeds import initialize_default_feeds
                initialize_default_feeds()
                print("✅ Default RSS feeds initialized")
            except Exception as e:
                print(f"⚠️  Could not initialize default RSS feeds: {e}")
        
        # Spätere Initialisierung nach Datenbank-Setup
        init_rss_feeds()
        
    except ImportError as e:
        print(f"❌ Failed to import RSS feeds routes: {e}")


    # Debug routes check
    print("🔍 DEBUG: Checking registered routes...")
    for rule in app.url_map.iter_rules():
        if 'contracts' in rule.rule or 'protocols' in rule.rule:
            print(f"  📍 {rule.rule} -> {rule.endpoint}")

    print("🔍 DEBUG: Checking template directories...")
    print(f"  Template folders: {app.jinja_loader.list_templates()[:10]}...")


def _register_runtime_migration_hook(app):
    """Simuliert das entfernte before_first_request-Hook für Flask >=3."""
    app._runtime_migration_done = False

    @app.before_request
    def _ensure_runtime_migrations_once():
        if getattr(app, "_runtime_migration_done", False):
            return
        try:
            _ensure_contract_protocol_columns()
        except Exception as exc:
            print(f"⚠️  Konnte Runtime-Migration nicht ausführen: {exc}")
        finally:
            app._runtime_migration_done = True

def initialize_database(app):
    """Initialize database after all blueprints are registered"""
    with app.app_context():
        try:
            db.create_all()
            print("📦 Creating database tables...")
            print("✅ Database tables created")

            # Sicherstellen, dass Vermieter-Flags in der Users-Tabelle vorhanden sind,
            # bevor weitere Abfragen auf die User-Tabelle erfolgen.
            ensure_user_landlord_flag()

            # Debug: Prüfen der User-Tabelle
            from app.models import User
            users = User.query.all()
            print(f"🔍 DEBUG: Found {len(users)} users in database:")
            for user in users:
                print(f"🔍 DEBUG: User {user.id}: {user.first_name} {user.last_name} ({user.email})")

            # Falls kein Admin existiert, ersten Benutzer hochstufen
            if users and not any(u.role == 'admin' for u in users):
                users[0].role = 'admin'
                db.session.commit()
                print(f"✅ Elevated user {users[0].username} to admin (fallback)")
            
            # Prüfe ob status Spalte in tenants Tabelle existiert
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('tenants')]
            
            if 'status' not in columns:
                print("🔄 Adding status column to tenants table...")
                db.session.execute(text('ALTER TABLE tenants ADD COLUMN status VARCHAR(20) DEFAULT "active"'))
                db.session.commit()
                print("✅ Status column added to tenants table")
                
            # Bestehende Mieter auf active setzen, falls nicht gesetzt
            from app.models import Tenant
            tenants_without_status = Tenant.query.filter(Tenant.status == None).all()
            for tenant in tenants_without_status:
                tenant.status = 'active'
            if tenants_without_status:
                db.session.commit()
                print(f"✅ Updated status for {len(tenants_without_status)} existing tenants")

            # Prüfe ob tenant_audit_logs Tabelle existiert
            if 'tenant_audit_logs' not in inspector.get_table_names():
                print("🔄 Creating tenant_audit_logs table...")
                # Tabelle wird automatisch durch db.create_all() erstellt
                print("✅ Tenant audit logs table created")

            # Sicherstellen, dass neue Betriebskosten-Spalten vorhanden sind
            try:
                cost_columns = [col['name'] for col in inspector.get_columns('operating_costs')]
                if 'system_invoice_number' not in cost_columns:
                    print("🔄 Adding system_invoice_number to operating_costs...")
                    db.session.execute(text('ALTER TABLE operating_costs ADD COLUMN system_invoice_number VARCHAR(120)'))
                    db.session.commit()
                    print("✅ system_invoice_number added")
                if 'allocation_percent' not in cost_columns:
                    print("🔄 Adding allocation_percent to operating_costs...")
                    db.session.execute(text('ALTER TABLE operating_costs ADD COLUMN allocation_percent FLOAT DEFAULT 0.0'))
                    db.session.commit()
                    print("✅ allocation_percent added")
                if 'vendor_invoice_number' not in cost_columns:
                    print("🔄 Adding vendor_invoice_number to operating_costs...")
                    db.session.execute(text('ALTER TABLE operating_costs ADD COLUMN vendor_invoice_number VARCHAR(120)'))
                    db.session.commit()
                    print("✅ vendor_invoice_number added")
            except Exception as mig_exc:
                print(f"⚠️ Could not migrate operating_costs columns: {mig_exc}")

            # Settlement-Felder absichern (falls alte Datenbankversion)
            try:
                settlement_columns = [col['name'] for col in inspector.get_columns('settlements')]
                if 'tenant_id' not in settlement_columns:
                    print("🔄 Adding tenant_id to settlements...")
                    db.session.execute(text('ALTER TABLE settlements ADD COLUMN tenant_id VARCHAR(36)'))
                    db.session.commit()
                    print("✅ tenant_id added")
            except Exception as mig_exc:
                print(f"⚠️ Could not migrate settlements columns: {mig_exc}")

            _ensure_contract_protocol_columns()

        except Exception as e:
            print(f"❌ Database initialization error: {e}")
            import traceback
            traceback.print_exc()


def _ensure_contract_protocol_columns():
    """Sichert neue Spalten für Vertrags-/Protokollsperren ab (idempotent)."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    try:
        contract_columns = [col['name'] for col in inspector.get_columns('contracts')]
        if 'move_out_date' not in contract_columns:
            print("🔄 Adding move_out_date to contracts...")
            db.session.execute(text('ALTER TABLE contracts ADD COLUMN move_out_date DATE'))
            db.session.commit()
            print("✅ move_out_date added")
        if 'is_locked' not in contract_columns:
            print("🔄 Adding is_locked to contracts...")
            db.session.execute(text('ALTER TABLE contracts ADD COLUMN is_locked BOOLEAN DEFAULT 0'))
            db.session.commit()
            print("✅ is_locked added")
        if 'final_document' not in contract_columns:
            print("🔄 Adding final_document to contracts...")
            db.session.execute(text('ALTER TABLE contracts ADD COLUMN final_document VARCHAR(255)'))
            db.session.commit()
            print("✅ final_document added")

        protocol_columns = [col['name'] for col in inspector.get_columns('protocols')]
        if 'is_closed' not in protocol_columns:
            print("🔄 Adding is_closed to protocols...")
            db.session.execute(text('ALTER TABLE protocols ADD COLUMN is_closed BOOLEAN DEFAULT 0'))
            db.session.commit()
            print("✅ is_closed added")
        if 'manual_pdf_path' not in protocol_columns:
            print("🔄 Adding manual_pdf_path to protocols...")
            db.session.execute(text('ALTER TABLE protocols ADD COLUMN manual_pdf_path VARCHAR(255)'))
            db.session.commit()
            print("✅ manual_pdf_path added")
    except Exception as mig_exc:
        print(f"⚠️ Could not migrate contract/protocol columns: {mig_exc}")