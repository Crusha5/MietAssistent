from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_jwt_extended import jwt_required
from app.models import Building, Apartment, Meter, MeterType, Tenant, Settlement, RevisionLog
from app.routes.main import login_required
from datetime import datetime
import uuid

# Database import from Flask current_app context
from flask import current_app
from app import db

buildings_bp = Blueprint('buildings', __name__)

@buildings_bp.route('/')  # ✅ Korrekter Pfad (wird zu /buildings)
@login_required
def buildings_list():
    try:
        buildings = Building.query.all()
        return render_template('buildings/list.html', buildings=buildings)
    except Exception as e:
        print(f"Error in buildings_list: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@buildings_bp.route('/create', methods=['GET', 'POST'])  # ✅ Korrekter Pfad (wird zu /buildings/create)
@login_required
def create_building():
    if request.method == 'POST':
        try:
            building = Building(
                id=str(uuid.uuid4()),
                name=request.form['name'],
                street=request.form.get('street', ''),
                street_number=request.form.get('street_number', ''),
                zip_code=request.form.get('zip_code', ''),
                city=request.form.get('city', ''),
                country=request.form.get('country', 'Deutschland'),
                year_built=int(request.form['year_built']) if request.form.get('year_built') else None,
                total_area_sqm=float(request.form['total_area_sqm']) if request.form.get('total_area_sqm') else None,
                energy_efficiency_class=request.form.get('energy_efficiency_class', ''),
                notes=request.form.get('notes', '')
            )
            
            db.session.add(building)
            db.session.commit()
            flash('Gebäude erfolgreich angelegt!', 'success')
            return redirect(url_for('buildings.buildings_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Anlegen des Gebäudes: {str(e)}', 'danger')
    
    return render_template('buildings/create.html')

@buildings_bp.route('/<building_id>')  # ✅ Korrekter Pfad (wird zu /buildings/<building_id>)
@login_required
def building_detail(building_id):
    try:
        building = Building.query.get_or_404(building_id)
        apartments = Apartment.query.filter_by(building_id=building_id).all()
        meters = Meter.query.filter_by(building_id=building_id).all()

        # Statistiken
        apartment_count = len(apartments)
        occupied_count = len([apt for apt in apartments if apt.status == 'occupied'])
        total_area = sum([apt.area_sqm or 0 for apt in apartments])
        meter_count = len(meters)

        revision_logs = (
            RevisionLog.query
            .filter_by(table_name='buildings', record_id=str(building_id))
            .order_by(RevisionLog.created_at.desc())
            .limit(15)
            .all()
        )

        return render_template('buildings/detail.html',
                             building=building,
                             apartments=apartments,
                             meters=meters,
                             apartment_count=apartment_count,
                             occupied_count=occupied_count,
                             total_area=total_area,
                             meter_count=meter_count,
                             revision_logs=revision_logs)
    except Exception as e:
        print(f"Error in building_detail: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@buildings_bp.route('/<building_id>/edit', methods=['GET', 'POST'])  # ✅ Korrekter Pfad
@login_required
def edit_building(building_id):
    building = Building.query.get_or_404(building_id)
    
    if request.method == 'POST':
        try:
            building.name = request.form['name']
            building.street = request.form.get('street', '')
            building.street_number = request.form.get('street_number', '')
            building.zip_code = request.form.get('zip_code', '')
            building.city = request.form.get('city', '')
            building.country = request.form.get('country', 'Deutschland')
            building.year_built = int(request.form['year_built']) if request.form.get('year_built') else None
            building.total_area_sqm = float(request.form['total_area_sqm']) if request.form.get('total_area_sqm') else None
            building.energy_efficiency_class = request.form.get('energy_efficiency_class', '')
            building.notes = request.form.get('notes', '')
            
            db.session.commit()
            flash('Gebäude erfolgreich aktualisiert!', 'success')
            return redirect(url_for('buildings.building_detail', building_id=building.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren des Gebäudes: {str(e)}', 'danger')
    
    return render_template('buildings/edit.html', building=building)

@buildings_bp.route('/<building_id>/delete', methods=['POST'])  # ✅ Korrekter Pfad
@login_required
def delete_building(building_id):
    building = Building.query.get_or_404(building_id)
    
    try:
        # Prüfen ob Wohnungen existieren
        apartments_count = Apartment.query.filter_by(building_id=building_id).count()
        if apartments_count > 0:
            flash('Kann Gebäude nicht löschen: Es existieren noch Wohnungen!', 'danger')
            return redirect(url_for('buildings.building_detail', building_id=building_id))
        
        # Prüfen ob Zähler existieren
        meters_count = Meter.query.filter_by(building_id=building_id).count()
        if meters_count > 0:
            flash('Kann Gebäude nicht löschen: Es existieren noch Zähler!', 'danger')
            return redirect(url_for('buildings.building_detail', building_id=building_id))
        
        db.session.delete(building)
        db.session.commit()
        flash('Gebäude erfolgreich gelöscht!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen des Gebäudes: {str(e)}', 'danger')
    
    return redirect(url_for('buildings.buildings_list'))

@buildings_bp.route('/<building_id>/apartments')  # ✅ Korrekter Pfad
@login_required
def building_apartments(building_id):
    try:
        building = Building.query.get_or_404(building_id)
        apartments = Apartment.query.filter_by(building_id=building_id).all()
        return render_template('buildings/apartments.html', 
                             building=building, 
                             apartments=apartments)
    except Exception as e:
        print(f"Error in building_apartments: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@buildings_bp.route('/<building_id>/meters')  # ✅ Korrekter Pfad
@login_required
def building_meters(building_id):
    try:
        building = Building.query.get_or_404(building_id)
        meters = Meter.query.filter_by(building_id=building_id).all()
        meter_types = MeterType.query.all()
        
        # Hauptzähler und Unterzähler gruppieren
        main_meters = [m for m in meters if m.is_main_meter]
        sub_meters = [m for m in meters if not m.is_main_meter and m.parent_meter_id]
        unassigned_meters = [m for m in meters if not m.is_main_meter and not m.parent_meter_id]
        
        return render_template('buildings/meters.html', 
                             building=building, 
                             main_meters=main_meters,
                             sub_meters=sub_meters,
                             unassigned_meters=unassigned_meters,
                             meter_types=meter_types)
    except Exception as e:
        print(f"Error in building_meters: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@buildings_bp.route('/<building_id>/hierarchy')  # ✅ Korrekter Pfad
@login_required
def building_hierarchy(building_id):
    try:
        building = Building.query.get_or_404(building_id)
        apartments = Apartment.query.filter_by(building_id=building_id).all()
        meters = Meter.query.filter_by(building_id=building_id).all()
        
        # Hierarchie aufbauen
        hierarchy = {
            'building': building,
            'apartments': []
        }
        
        for apartment in apartments:
            apartment_data = {
                'apartment': apartment,
                'tenants': Tenant.query.filter_by(apartment_id=apartment.id).all(),
                'meters': [m for m in meters if m.apartment_id == apartment.id]
            }
            hierarchy['apartments'].append(apartment_data)
        
        # Nicht zugeordnete Zähler (Hauptzähler)
        main_meters = [m for m in meters if not m.apartment_id]
        hierarchy['main_meters'] = main_meters
        
        return render_template('buildings/hierarchy.html', hierarchy=hierarchy)
    except Exception as e:
        print(f"Error in building_hierarchy: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@buildings_bp.route('/<building_id>/statistics')  # ✅ Korrekter Pfad
@login_required
def building_statistics(building_id):
    try:
        building = Building.query.get_or_404(building_id)
        apartments = Apartment.query.filter_by(building_id=building_id).all()
        meters = Meter.query.filter_by(building_id=building_id).all()
        settlements = Settlement.query.join(Apartment).filter(Apartment.building_id == building_id).all()
        
        # Statistiken berechnen
        stats = {
            'apartment_count': len(apartments),
            'occupied_count': len([apt for apt in apartments if apt.status == 'occupied']),
            'vacant_count': len([apt for apt in apartments if apt.status == 'vacant']),
            'total_area': sum([apt.area_sqm or 0 for apt in apartments]),
            'meter_count': len(meters),
            'main_meter_count': len([m for m in meters if m.is_main_meter]),
            'sub_meter_count': len([m for m in meters if not m.is_main_meter]),
            'settlement_count': len(settlements),
            'total_rent': sum([apt.rent_net or 0 for apt in apartments]),
            'occupancy_rate': (len([apt for apt in apartments if apt.status == 'occupied']) / len(apartments) * 100) if apartments else 0
        }
        
        return render_template('buildings/statistics.html', 
                             building=building, 
                             stats=stats,
                             apartments=apartments)
    except Exception as e:
        print(f"Error in building_statistics: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

# API Routes - Diese müssen ebenfalls angepasst werden
@buildings_bp.route('/api/buildings', methods=['GET'])  # ❌ Doppelter Präfix für API
@jwt_required()
def get_buildings_api():
    buildings = Building.query.all()
    return jsonify([{
        'id': building.id,
        'name': building.name,
        'street': building.street,
        'street_number': building.street_number,
        'zip_code': building.zip_code,
        'city': building.city,
        'country': building.country,
        'year_built': building.year_built,
        'total_area_sqm': float(building.total_area_sqm) if building.total_area_sqm else None,
        'energy_efficiency_class': building.energy_efficiency_class,
        'apartment_count': len(building.apartments),
        'meter_count': len(building.meters),
        'created_at': building.created_at.isoformat(),
        'updated_at': building.updated_at.isoformat()
    } for building in buildings])

@buildings_bp.route('/api/buildings/<building_id>/apartments', methods=['GET'])
@jwt_required()
def get_building_apartments_api(building_id):
    try:
        apartments = Apartment.query.filter_by(building_id=building_id).all()
        
        return jsonify([{
            'id': apartment.id,
            'apartment_number': apartment.apartment_number,
            'building_name': apartment.building.name if apartment.building else 'Unbekannt'
        } for apartment in apartments])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Korrektur für API Routes - diese werden separat mit /api/buildings registriert
# Die API Routes sollten eigentlich in einem separaten Blueprint sein, 
# aber für jetzt lassen wir sie wie sie sind, da sie in __init__.py separat registriert werden