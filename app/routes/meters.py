from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_jwt_extended import jwt_required
from app.models import Meter, MeterType, Building, Apartment, MeterReading
from app.routes.main import login_required
from datetime import datetime
import uuid

from flask import current_app
from app.extensions import db
from sqlalchemy import or_

meters_bp = Blueprint('meters', __name__)

@meters_bp.route('/')
@login_required
def meters_list():
    """Zeigt alle Zähler an"""
    meters = Meter.query.filter(
        or_(Meter.is_archived == False, Meter.is_archived.is_(None))
    ).options(
        db.joinedload(Meter.building),
        db.joinedload(Meter.meter_type),
        db.joinedload(Meter.apartment),
        db.joinedload(Meter.sub_meters)
    ).all()

    return render_template('meters/list.html', meters=meters)

@meters_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_meter():
    """Legt einen neuen Zähler an - KORRIGIERT OHNE initial_reading"""
    try:
        # Nur Zählertypen aus der Datenbank holen
        meter_types = MeterType.query.filter_by(is_active=True).order_by(MeterType.name).all()
        
        current_app.logger.info(f"CREATE_METER - Starte Zählererstellung")
        
        if request.method == 'POST':
            try:
                building_id = request.form.get('building_id')
                current_app.logger.info(f"📝 FORM DATA - building_id: {building_id}")
                
                if not building_id:
                    flash('❌ Bitte wählen Sie ein gültiges Gebäude aus!', 'danger')
                    return render_template('meters/create.html', meter_types=meter_types)

                # Validiere dass Gebäude existiert
                building = Building.query.get(building_id)
                if not building:
                    flash('❌ Ausgewähltes Gebäude existiert nicht!', 'danger')
                    return render_template('meters/create.html', meter_types=meter_types)

                # ✅ KORREKTUR: Entferne initial_reading - das gibt es nicht im Meter Model
                price_per_unit = request.form.get('price_per_unit')
                price_per_unit = float(price_per_unit) if price_per_unit not in (None, '',) else None
                meter = Meter(
                    id=str(uuid.uuid4()),
                    meter_number=request.form['meter_number'].strip(),
                    description=request.form.get('description', '').strip(),
                    building_id=building_id,
                    apartment_id=request.form.get('apartment_id') or None,
                    parent_meter_id=None,
                    meter_type_id=request.form['meter_type_id'],
                    manufacturer=request.form.get('manufacturer', '').strip(),
                    model=request.form.get('model', '').strip(),
                    installation_date=datetime.strptime(request.form['installation_date'], '%Y-%m-%d').date() if request.form.get('installation_date') else datetime.now().date(),
                    is_main_meter=True,
                    is_virtual_meter=bool(request.form.get('is_virtual_meter')),
                    multiplier=float(request.form.get('multiplier', 1.0)),
                    location_description=request.form.get('location_description', '').strip(),
                    notes=request.form.get('notes', '').strip(),
                    price_per_unit=price_per_unit,
                )
                
                db.session.add(meter)
                db.session.commit()
                
                flash('✅ Hauptzähler erfolgreich angelegt!', 'success')
                return redirect(url_for('meters.meters_list'))
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"❌ Fehler beim Anlegen des Zählers: {str(e)}", exc_info=True)
                flash(f'❌ Fehler beim Anlegen des Zählers: {str(e)}', 'danger')
        
        return render_template('meters/create.html', meter_types=meter_types)
    
    except Exception as e:
        current_app.logger.error(f"💥 KRITISCHER FEHLER in create_meter: {str(e)}", exc_info=True)
        flash(f'💥 Kritischer Fehler: {str(e)}', 'danger')
        return redirect(url_for('meters.meters_list'))
    
# Temporäre Debug-Route in meters.py hinzufügen:
@meters_bp.route('/test-global-buildings')
@login_required
def test_global_buildings():
    """Testet die globale buildings Variable"""
    return render_template('meters/debug_template.html')

@meters_bp.route('/debug/direct-buildings')
@login_required
def debug_direct_buildings():
    """Direkte Debug-Route für Gebäude"""
    try:
        from app.models import Building
        buildings = Building.query.order_by(Building.name).all()
        
        result = {
            'total_buildings': len(buildings),
            'buildings': []
        }
        
        for building in buildings:
            result['buildings'].append({
                'id': building.id,
                'name': building.name,
                'street': building.street,
                'apartment_count': len(building.apartments) if building.apartments else 0
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@meters_bp.route('/debug-template')
@login_required
def debug_template():
    """Debug-Route um Template-Variablen zu testen"""
    buildings = Building.query.order_by(Building.name).all()
    
    # Teste verschiedene Variablennamen
    return render_template('meters/debug_template.html', 
                         buildings=buildings,
                         available_buildings=buildings,
                         test_buildings=buildings)

# Debug Route zum Prüfen der Gebäude
@meters_bp.route('/debug/buildings')
@login_required
def debug_buildings():
    """Debug-Route um Gebäude-Daten zu prüfen"""
    try:
        buildings = Building.query.order_by(Building.name).all()
        
        building_data = []
        for building in buildings:
            building_data.append({
                'id': building.id,
                'name': building.name,
                'street': building.street,
                'apartment_count': len(building.apartments) if building.apartments else 0
            })
        
        return jsonify({
            'total_buildings': len(buildings),
            'buildings': building_data
        })
    except Exception as e:
        current_app.logger.error(f"Fehler in debug_buildings: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Der Rest der Routes bleibt unverändert...
@meters_bp.route('/<meter_id>')
@login_required
def meter_detail(meter_id):
    """Zeigt Zählerdetails an"""
    meter = Meter.query.options(
        db.joinedload(Meter.building),
        db.joinedload(Meter.meter_type),
        db.joinedload(Meter.apartment),
        db.joinedload(Meter.parent_meter),
        db.joinedload(Meter.sub_meters)
    ).get_or_404(meter_id)
    
    readings = MeterReading.query.filter(
        MeterReading.meter_id == meter_id,
        (MeterReading.is_archived.is_(False)) | (MeterReading.is_archived.is_(None)),
    ).order_by(MeterReading.reading_date.desc()).all()
    
    return render_template('meters/detail.html', 
                         meter=meter, 
                         readings=readings)

@meters_bp.route('/<meter_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_meter(meter_id):
    """Bearbeitet einen Zähler - KORRIGIERT OHNE initial_reading"""
    meter = Meter.query.get_or_404(meter_id)
    buildings = Building.query.order_by(Building.name).all()
    meter_types = MeterType.query.filter_by(is_active=True).order_by(MeterType.name).all()
    
    # Alle Hauptzähler als mögliche Parent-Zähler
    parent_meters = Meter.query.filter(
        Meter.id != meter_id,
        Meter.is_main_meter == True,
        or_(Meter.is_archived == False, Meter.is_archived.is_(None))
    ).options(
        db.joinedload(Meter.building)
    ).all()

    next_url = request.args.get('next') or request.form.get('next')

    if request.method == 'POST':
        try:
            parent_meter_id = request.form.get('parent_meter_id') or None
            is_main_meter = parent_meter_id is None

            meter.meter_number = request.form['meter_number'].strip()
            meter.description = request.form.get('description', '').strip()
            meter.building_id = request.form['building_id']
            meter.apartment_id = request.form.get('apartment_id') or None
            meter.parent_meter_id = parent_meter_id
            meter.meter_type_id = request.form['meter_type_id']
            meter.manufacturer = request.form.get('manufacturer', '').strip()
            meter.model = request.form.get('model', '').strip()
            price_per_unit = request.form.get('price_per_unit')
            meter.price_per_unit = float(price_per_unit) if price_per_unit not in (None, '',) else None

            if request.form.get('installation_date'):
                meter.installation_date = datetime.strptime(request.form['installation_date'], '%Y-%m-%d').date()
            
            meter.is_main_meter = is_main_meter
            meter.is_virtual_meter = bool(request.form.get('is_virtual_meter'))
            meter.multiplier = float(request.form.get('multiplier', 1.0))
            meter.location_description = request.form.get('location_description', '').strip()
            meter.notes = request.form.get('notes', '').strip()
            
            db.session.commit()
            flash('✅ Zähler erfolgreich aktualisiert!', 'success')
            if next_url:
                return redirect(next_url)
            return redirect(url_for('meters.meter_detail', meter_id=meter.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Aktualisieren des Zählers: {str(e)}", exc_info=True)
            flash(f'❌ Fehler beim Aktualisieren des Zählers: {str(e)}', 'danger')
    
    return render_template('meters/edit.html',
                         meter=meter,
                         buildings=buildings,
                         meter_types=meter_types,
                         parent_meters=parent_meters,
                         next_url=next_url)


@meters_bp.route('/<meter_id>/archive', methods=['POST'])
@login_required
def archive_meter(meter_id):
    """Archiviert oder reaktiviert einen Zähler."""
    meter = Meter.query.get_or_404(meter_id)
    action = request.form.get('action', 'archive')
    next_url = request.form.get('next')

    try:
        meter.is_archived = action == 'archive'
        db.session.commit()
        flash('✅ Zähler archiviert.' if meter.is_archived else '♻️ Zähler reaktiviert.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Fehler beim (Re-)Aktivieren des Zählers: %s', exc, exc_info=True)
        flash(f'❌ Zähler konnte nicht aktualisiert werden: {exc}', 'danger')

    if next_url:
        return redirect(next_url)
    return redirect(url_for('meters.edit_meter', meter_id=meter_id))

@meters_bp.route('/<meter_id>/delete', methods=['POST'])
@login_required
def delete_meter(meter_id):
    """Löscht einen Zähler"""
    meter = Meter.query.get_or_404(meter_id)
    
    try:
        # Prüfe ob Unterzähler existieren
        sub_meters_count = Meter.query.filter_by(parent_meter_id=meter_id).count()
        if sub_meters_count > 0:
            flash('❌ Kann Zähler nicht löschen: Es existieren noch Unterzähler!', 'danger')
            return redirect(url_for('meters.meter_detail', meter_id=meter_id))
        
        # Prüfe ob Zählerstände existieren
        readings_count = MeterReading.query.filter_by(meter_id=meter_id).count()
        if readings_count > 0:
            flash('❌ Kann Zähler nicht löschen: Es existieren noch Zählerstände!', 'danger')
            return redirect(url_for('meters.meter_detail', meter_id=meter_id))
        
        db.session.delete(meter)
        db.session.commit()
        flash('✅ Zähler erfolgreich gelöscht!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Löschen des Zählers: {str(e)}", exc_info=True)
        flash(f'❌ Fehler beim Löschen des Zählers: {str(e)}', 'danger')
    
    return redirect(url_for('meters.meters_list'))

@meters_bp.route('/<meter_id>/add-submeter', methods=['GET', 'POST'])
@login_required
def add_submeter(meter_id):
    """Fügt einen Unterzähler hinzu - KORRIGIERT OHNE initial_reading"""
    parent_meter = Meter.query.get_or_404(meter_id)
    
    # Zählertypen für das Formular
    meter_types = MeterType.query.filter_by(is_active=True).order_by(MeterType.name).all()
    
    # Wohnungen im gleichen Gebäude
    apartments = Apartment.query.filter_by(building_id=parent_meter.building_id).all()

    if request.method == 'POST':
        try:
            # ✅ KORREKTUR: Entferne initial_reading
            price_per_unit = request.form.get('price_per_unit')
            price_per_unit = float(price_per_unit) if price_per_unit not in (None, '',) else None

            submeter = Meter(
                id=str(uuid.uuid4()),
                meter_number=request.form['meter_number'].strip(),
                description=request.form.get('description', '').strip(),
                building_id=parent_meter.building_id,  # Gleiches Gebäude wie Parent
                apartment_id=request.form.get('apartment_id') or None,
                parent_meter_id=parent_meter.id,  # Wichtig: Parent setzen
                meter_type_id=request.form['meter_type_id'],
                manufacturer=request.form.get('manufacturer', '').strip(),
                model=request.form.get('model', '').strip(),
                installation_date=datetime.strptime(request.form['installation_date'], '%Y-%m-%d').date() if request.form.get('installation_date') else datetime.now().date(),
                is_main_meter=False,  # Unterzähler sind nie Hauptzähler
                is_virtual_meter=bool(request.form.get('is_virtual_meter')),
                multiplier=float(request.form.get('multiplier', 1.0)),
                location_description=request.form.get('location_description', '').strip(),
                notes=request.form.get('notes', '').strip(),
                price_per_unit=price_per_unit,
            )
            
            db.session.add(submeter)
            db.session.commit()
            flash('✅ Unterzähler erfolgreich angelegt!', 'success')
            return redirect(url_for('meters.meter_detail', meter_id=parent_meter.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Anlegen des Unterzählers: {str(e)}", exc_info=True)
            flash(f'❌ Fehler beim Anlegen des Unterzählers: {str(e)}', 'danger')
    
    return render_template('meters/add_submeter.html', 
                         parent_meter=parent_meter,
                         apartments=apartments, 
                         meter_types=meter_types)

@meters_bp.route('/<meter_id>/edit-submeter', methods=['GET', 'POST'])
@login_required
def edit_submeter(meter_id):
    """Bearbeitet einen Unterzähler"""
    meter = Meter.query.get_or_404(meter_id)
    
    # Sicherstellen, dass es sich um einen Unterzähler handelt
    if meter.is_main_meter:
        flash('❌ Diese Funktion ist nur für Unterzähler verfügbar!', 'danger')
        return redirect(url_for('meters.meter_detail', meter_id=meter.id))
    
    meter_types = MeterType.query.filter_by(is_active=True).order_by(MeterType.name).all()
    
    # Wohnungen im gleichen Gebäude wie der Parent
    apartments = Apartment.query.filter_by(building_id=meter.building_id).all()

    if request.method == 'POST':
        try:
            # Grundinformationen
            meter.meter_number = request.form['meter_number'].strip()
            meter.description = request.form.get('description', '').strip()
            meter.meter_type_id = request.form['meter_type_id']
            meter.multiplier = float(request.form.get('multiplier', 1.0))
            
            # Wohnung zuweisen (kann None sein)
            apartment_id = request.form.get('apartment_id')
            meter.apartment_id = apartment_id if apartment_id else None
            
            # Technische Daten
            meter.manufacturer = request.form.get('manufacturer', '').strip()
            meter.model = request.form.get('model', '').strip()
            meter.location_description = request.form.get('location_description', '').strip()
            meter.notes = request.form.get('notes', '').strip()
            price_per_unit = request.form.get('price_per_unit')
            meter.price_per_unit = float(price_per_unit) if price_per_unit not in (None, '',) else None
            
            # Installationsdatum
            if request.form.get('installation_date'):
                meter.installation_date = datetime.strptime(request.form['installation_date'], '%Y-%m-%d').date()
            
            # Virtueller Zähler
            meter.is_virtual_meter = bool(request.form.get('is_virtual_meter'))
            
            db.session.commit()
            flash('✅ Unterzähler erfolgreich aktualisiert!', 'success')
            return redirect(url_for('meters.meter_detail', meter_id=meter.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Aktualisieren des Unterzählers: {str(e)}", exc_info=True)
            flash(f'❌ Fehler beim Aktualisieren des Unterzählers: {str(e)}', 'danger')
    
    return render_template('meters/edit_submeter.html', 
                         meter=meter,
                         meter_types=meter_types,
                         apartments=apartments)

@meters_bp.route('/<meter_id>/hierarchy')
@login_required
def meter_hierarchy(meter_id):
    """Zeigt die Zähler-Hierarchie an"""
    meter = Meter.query.get_or_404(meter_id)
    
    def build_hierarchy(current_meter):
        hierarchy = {
            'meter': current_meter,
            'sub_meters': []
        }
        
        sub_meters = Meter.query.filter_by(parent_meter_id=current_meter.id).options(
            db.joinedload(Meter.meter_type),
            db.joinedload(Meter.apartment)
        ).all()
        
        for sub_meter in sub_meters:
            hierarchy['sub_meters'].append(build_hierarchy(sub_meter))
            
        return hierarchy
    
    hierarchy = build_hierarchy(meter)
    return render_template('meters/hierarchy.html', hierarchy=hierarchy)

# 🔥 API ENDPOINTS FÜR DROPDOWN-FILTERUNG

@meters_bp.route('/api/buildings/<building_id>/apartments')
@login_required
def get_building_apartments(building_id):
    """API für Wohnungen eines Gebäudes"""
    try:
        apartments = Apartment.query.filter_by(building_id=building_id).options(
            db.joinedload(Apartment.building)
        ).all()
        
        return jsonify([{
            'id': str(apartment.id),
            'apartment_number': apartment.apartment_number,
            'building_name': apartment.building.name if apartment.building else 'Unbekannt'
        } for apartment in apartments])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@meters_bp.route('/api/buildings/<building_id>/meters')
@login_required
def get_building_meters(building_id):
    """API für Zähler eines Gebäudes"""
    try:
        meters = Meter.query.filter_by(building_id=building_id).options(
            db.joinedload(Meter.meter_type)
        ).all()
        
        return jsonify([{
            'id': str(meter.id),
            'meter_number': meter.meter_number,
            'description': meter.description or '',
            'meter_type': meter.meter_type.name if meter.meter_type else 'Unbekannt'
        } for meter in meters])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 🔥 API ROUTES FÜR MOBILE APP/EXTERNE SYSTEME

@meters_bp.route('/api/meters', methods=['GET'])
@jwt_required()
def get_meters_api():
    """API: Alle Zähler abrufen"""
    meters = Meter.query.options(
        db.joinedload(Meter.building),
        db.joinedload(Meter.meter_type),
        db.joinedload(Meter.apartment)
    ).all()
    
    return jsonify([{
        'id': meter.id,
        'meter_number': meter.meter_number,
        'description': meter.description,
        'building_id': meter.building_id,
        'building_name': meter.building.name if meter.building else None,
        'apartment_id': meter.apartment_id,
        'apartment_number': meter.apartment.apartment_number if meter.apartment else None,
        'parent_meter_id': meter.parent_meter_id,
        'meter_type': meter.meter_type.name,
        'meter_type_category': meter.meter_type.category,
        'unit': meter.meter_type.unit,
        'is_main_meter': meter.is_main_meter,
        'is_virtual_meter': meter.is_virtual_meter,
        'multiplier': float(meter.multiplier) if meter.multiplier else 1.0,
        'installation_date': meter.installation_date.isoformat() if meter.installation_date else None,
        'location_description': meter.location_description,
        'price_per_unit': meter.price_per_unit
    } for meter in meters])

@meters_bp.route('/api/meters', methods=['POST'])
@jwt_required()
def create_meter_api():
    """API: Zähler anlegen"""
    data = request.get_json()
    
    try:
        parent_meter_id = data.get('parent_meter_id')
        is_main_meter = parent_meter_id is None

        price_per_unit = data.get('price_per_unit')
        price_per_unit = float(price_per_unit) if price_per_unit not in (None, '',) else None

        meter = Meter(
            id=str(uuid.uuid4()),
            meter_number=data['meter_number'],
            description=data.get('description', ''),
            building_id=data['building_id'],
            apartment_id=data.get('apartment_id'),
            parent_meter_id=parent_meter_id,
            meter_type_id=data['meter_type_id'],
            manufacturer=data.get('manufacturer', ''),
            model=data.get('model', ''),
            installation_date=datetime.fromisoformat(data['installation_date']).date() if data.get('installation_date') else None,
            is_main_meter=is_main_meter,
            is_virtual_meter=data.get('is_virtual_meter', False),
            multiplier=data.get('multiplier', 1.0),
            location_description=data.get('location_description', ''),
            notes=data.get('notes', ''),
            price_per_unit=price_per_unit,
        )
        
        db.session.add(meter)
        db.session.commit()
        
        return jsonify({
            'message': 'Zähler erfolgreich angelegt',
            'id': meter.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Anlegen des Zählers (API): {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

@meters_bp.route('/api/meters/<meter_id>', methods=['GET'])
@jwt_required()
def get_meter_api(meter_id):
    """API: Einzelnen Zähler abrufen"""
    meter = Meter.query.get_or_404(meter_id)
    
    return jsonify({
        'id': meter.id,
        'meter_number': meter.meter_number,
        'description': meter.description,
        'building_id': meter.building_id,
        'apartment_id': meter.apartment_id,
        'parent_meter_id': meter.parent_meter_id,
        'meter_type_id': meter.meter_type_id,
        'manufacturer': meter.manufacturer,
        'model': meter.model,
        'installation_date': meter.installation_date.isoformat() if meter.installation_date else None,
        'is_main_meter': meter.is_main_meter,
        'is_virtual_meter': meter.is_virtual_meter,
        'multiplier': float(meter.multiplier) if meter.multiplier else 1.0,
        'location_description': meter.location_description,
        'price_per_unit': meter.price_per_unit,
        'notes': meter.notes,
        'created_at': meter.created_at.isoformat(),
        'updated_at': meter.updated_at.isoformat()
    })

@meters_bp.route('/api/meters/<meter_id>/readings', methods=['GET'])
@jwt_required()
def get_meter_readings_api(meter_id):
    """API: Zählerstände abrufen"""
    readings = MeterReading.query.filter_by(meter_id=meter_id).order_by(MeterReading.reading_date.desc()).all()
    
    return jsonify([{
        'id': reading.id,
        'reading_value': float(reading.reading_value),
        'reading_date': reading.reading_date.isoformat(),
        'reading_type': reading.reading_type,
        'photo_path': reading.photo_path,
        'notes': reading.notes,
        'created_at': reading.created_at.isoformat()
    } for reading in readings])

@meters_bp.route('/api/meters/types', methods=['GET'])
@jwt_required()
def get_meter_types_api():
    """API: Zählertypen abrufen"""
    meter_types = MeterType.query.filter_by(is_active=True).all()
    
    return jsonify([{
        'id': mt.id,
        'name': mt.name,
        'category': mt.category,
        'unit': mt.unit,
        'decimal_places': mt.decimal_places
    } for mt in meter_types])