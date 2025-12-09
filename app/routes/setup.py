from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from app.extensions import db
from app.models import User, Building, Apartment, MeterType
import os
import uuid
from datetime import datetime

setup_bp = Blueprint('setup', __name__)

@setup_bp.route('/')
def setup_index():
    print("🔍 DEBUG: Setup index called")
    # Prüfe ob bereits Benutzer existieren
    if User.query.first():
        return render_template('setup/already_complete.html')
    return render_template('setup/welcome.html')

@setup_bp.route('/admin', methods=['GET', 'POST'])
def setup_admin():
    print("🔍 DEBUG: Setup admin called")
    print(f"🔍 DEBUG: Session at admin: {dict(session)}")
    
    if request.method == 'POST':
        data = request.get_json()
        print(f"🔍 DEBUG: Admin form data: {data}")
        
        try:
            # Create admin user
            admin_user = User(
                id=str(uuid.uuid4()),
                username=data['username'],
                email=data.get('email', ''),
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                role='admin',
                is_active=True
            )
            admin_user.set_password(data['password'])
            
            db.session.add(admin_user)
            db.session.commit()
            
            # Session setzen
            session['user_id'] = str(admin_user.id)
            session['username'] = admin_user.username
            session['setup_step'] = 'building'
            session.modified = True
            
            print(f"🔍 DEBUG: Admin created, session: {dict(session)}")
            
            return jsonify({'success': True, 'message': 'Admin-Benutzer erstellt'})
            
        except Exception as e:
            db.session.rollback()
            print(f"🔍 DEBUG: Admin creation error: {str(e)}")
            return jsonify({'success': False, 'message': f'Fehler: {str(e)}'}), 400
    
    return render_template('setup/admin.html')

@setup_bp.route('/building', methods=['GET', 'POST'])
def setup_building():
    print("🔍 DEBUG: Setup building called")
    print(f"🔍 DEBUG: Session at building: {dict(session)}")
    
    if request.method == 'POST':
        data = request.get_json()
        print(f"🔍 DEBUG: Building form data: {data}")
        
        try:
            # Create first building
            building = Building(
                id=str(uuid.uuid4()),
                name=data['name'],
                street=data['street'],
                street_number=data['street_number'],
                zip_code=data['zip_code'],
                city=data['city'],
                country=data.get('country', 'Deutschland'),
                year_built=int(data['year_built']) if data.get('year_built') else None,
                total_area_sqm=float(data['total_area_sqm']) if data.get('total_area_sqm') else None,
                energy_efficiency_class=data.get('energy_efficiency_class', '')
            )
            
            db.session.add(building)
            db.session.commit()
            
            # Session explizit speichern
            session['building_id'] = str(building.id)
            session['setup_step'] = 'apartment'
            session.modified = True
            
            print(f"🔍 DEBUG: Building created with ID: {building.id}")
            print(f"🔍 DEBUG: Session after building: {dict(session)}")
            
            # Überprüfe ob Gebäude wirklich in DB
            buildings_in_db = Building.query.all()
            print(f"🔍 DEBUG: Buildings in database: {[b.id for b in buildings_in_db]}")
            
            return jsonify({
                'success': True, 
                'message': 'Gebäude angelegt', 
                'building_id': str(building.id)
            })
            
        except Exception as e:
            db.session.rollback()
            print(f"🔍 DEBUG: Building creation error: {str(e)}")
            return jsonify({'success': False, 'message': f'Fehler: {str(e)}'}), 400
    
    return render_template('setup/building.html')

@setup_bp.route('/apartment', methods=['GET', 'POST'])
def setup_apartment():
    print("🔍 DEBUG: Setup apartment called")
    print(f"🔍 DEBUG: Full session: {dict(session)}")
    print(f"🔍 DEBUG: Building ID in session: {session.get('building_id')}")
    
    # Gebäude aus Session oder DB holen
    building_id = session.get('building_id')
    building = None
    
    if building_id:
        building = Building.query.get(building_id)
        print(f"🔍 DEBUG: Building from session ID: {building}")
    else:
        # Fallback: Erstes Gebäude aus DB nehmen
        building = Building.query.first()
        if building:
            building_id = str(building.id)
            session['building_id'] = building_id
            session.modified = True
            print(f"🔍 DEBUG: Using first building from DB: {building_id}")
        else:
            print("🔍 DEBUG: No building found in session or database!")
    
    if request.method == 'POST':
        data = request.get_json()
        print(f"🔍 DEBUG: Apartment form data: {data}")
        print(f"🔍 DEBUG: Using building_id: {building_id}")
        
        try:
            # Validierung
            if not building_id:
                print("🔍 DEBUG: No building_id available")
                return jsonify({
                    'success': False, 
                    'message': 'Kein Gebäude ausgewählt. Bitte starten Sie das Setup neu.'
                }), 400
            
            # Überprüfe ob Gebäude existiert
            building = Building.query.get(building_id)
            if not building:
                print(f"🔍 DEBUG: Building with ID {building_id} not found in DB")
                return jsonify({
                    'success': False, 
                    'message': 'Gebäude nicht gefunden. Bitte starten Sie das Setup neu.'
                }), 400
            
            # Create first apartment
            apartment = Apartment(
                id=str(uuid.uuid4()),
                building_id=building_id,
                apartment_number=data['apartment_number'],
                floor=data.get('floor', ''),
                area_sqm=float(data['area_sqm']),
                room_count=int(data.get('room_count', 1)),
                unit_type=data.get('unit_type', 'wohnung'),
                rent_net=float(data.get('rent_net', 0)),
                rent_additional=float(data.get('rent_additional', 0)),
                has_balcony=bool(data.get('has_balcony', False)),
                has_terrace=bool(data.get('has_terrace', False)),
                has_garage=bool(data.get('has_garage', False)),
                status='vacant'
            )
            
            db.session.add(apartment)
            db.session.commit()
            
            session['apartment_id'] = str(apartment.id)
            session['setup_step'] = 'meter_types'
            session.modified = True
            
            print(f"🔍 DEBUG: Apartment created successfully")
            print(f"🔍 DEBUG: Session after apartment: {dict(session)}")
            
            return jsonify({'success': True, 'message': 'Einheit angelegt'})
            
        except Exception as e:
            db.session.rollback()
            print(f"🔍 DEBUG: Apartment creation error: {str(e)}")
            return jsonify({'success': False, 'message': f'Fehler beim Anlegen der Einheit: {str(e)}'}), 400
    
    # GET Request: Zeige das Formular mit Gebäude-Information
    return render_template('setup/apartment.html', building=building)

@setup_bp.route('/meter-types', methods=['GET', 'POST'])
def setup_meter_types():
    print("🔍 DEBUG: Setup meter-types called")
    print(f"🔍 DEBUG: Session at meter-types: {dict(session)}")

    if request.method == 'POST':
        try:
            payload = request.get_json(silent=True) or {}

            # Erlaube mehrere Zählertypen in einem Rutsch, fallback auf Standardliste
            incoming_meter_types = payload.get('meter_types') if isinstance(payload, dict) else None

            if incoming_meter_types and isinstance(incoming_meter_types, list):
                meter_types_data = []
                for raw_mt in incoming_meter_types:
                    name = (raw_mt.get('name') or '').strip()
                    unit = (raw_mt.get('unit') or '').strip()

                    if not name or not unit:
                        continue  # Leere Zeilen überspringen, damit der POST nicht fehlschlägt

                    meter_types_data.append({
                        'name': name,
                        'category': (raw_mt.get('category') or 'other').strip() or 'other',
                        'unit': unit,
                        'decimal_places': int(raw_mt.get('decimal_places') or 2)
                    })

                if not meter_types_data:
                    return jsonify({'success': False, 'message': 'Bitte mindestens einen gültigen Zählertyp angeben.'}), 400
            else:
                # Standardliste beibehalten, falls kein Array gesendet wird
                meter_types_data = [
                    {'name': 'Strom', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
                    {'name': 'Strom Allgemeinstrom', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
                    {'name': 'Wasser', 'category': 'water', 'unit': 'm³', 'decimal_places': 3},
                    {'name': 'Heizung', 'category': 'heating', 'unit': 'kWh', 'decimal_places': 2},
                    {'name': 'Gas', 'category': 'gas', 'unit': 'm³', 'decimal_places': 3},
                    {'name': 'Wärmepumpe', 'category': 'renewable', 'unit': 'kWh', 'decimal_places': 2},
                    {'name': 'Strom Wallbox', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
                    {'name': 'Strom PV-Einspeisung', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
                ]

            for mt_data in meter_types_data:
                # Kein serverseitiges Caching: Alle Zählertypen werden frisch gespeichert
                meter_type = MeterType(
                    id=str(uuid.uuid4()),
                    name=mt_data['name'],
                    category=mt_data['category'],
                    unit=mt_data['unit'],
                    decimal_places=mt_data['decimal_places']
                )
                db.session.add(meter_type)
            
            db.session.commit()
            
            session['setup_step'] = 'complete'
            session['setup_complete'] = True
            session.modified = True
            
            print(f"🔍 DEBUG: Meter types created successfully")
            
            return jsonify({'success': True, 'message': 'Standard-Zählertypen angelegt'})
            
        except Exception as e:
            db.session.rollback()
            print(f"🔍 DEBUG: Meter types creation error: {str(e)}")
            return jsonify({'success': False, 'message': f'Fehler: {str(e)}'}), 400
    
    return render_template('setup/meter_types.html')

@setup_bp.route('/complete')
def setup_complete():
    print("🔍 DEBUG: Setup complete called")
    return render_template('setup/complete.html')

@setup_bp.route('/status')
def setup_status():
    # Check if setup is already complete
    users = User.query.first()
    if users:
        return jsonify({'setup_complete': True})
    return jsonify({'setup_complete': False})

@setup_bp.route('/debug-fix', methods=['GET'])
def setup_debug_fix():
    """Notfall-Route um Setup-Probleme zu beheben"""
    print("🔧 DEBUG: Running setup debug fix")
    
    # Lösche alle Session-Daten
    session.clear()
    
    # Finde das erste Gebäude in der DB
    building = Building.query.first()
    if building:
        session['building_id'] = str(building.id)
        session.modified = True
        print(f"🔧 DEBUG: Set building_id to {building.id}")
        return jsonify({
            'success': True, 
            'message': f'Gebäude {building.name} wurde als aktuelles Gebäude gesetzt',
            'building_id': str(building.id)
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Kein Gebäude in der Datenbank gefunden'
        })