from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_jwt_extended import jwt_required
from app import db
from app.models import Apartment, Building, Tenant, Meter, MeterReading, RevisionLog
from app.routes.main import login_required
from datetime import datetime
import uuid

apartments_bp = Blueprint('apartments', __name__)

# Web Route für die Wohnungsliste
@apartments_bp.route('/')
@login_required
def apartments_list():
    try:
        print("DEBUG: apartments_list route called")
        
        apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()
        buildings = Building.query.all()
        
        print(f"DEBUG: Found {len(apartments)} apartments")
        # Debug-Ausgabe für Status
        for apt in apartments:
            print(f"DEBUG: Apartment {apt.apartment_number} - Status: {apt.status}")
        
        return render_template('apartments/list.html', 
                             apartments=apartments, 
                             buildings=buildings)
    except Exception as e:
        print(f"❌ Error in apartments_list: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler beim Laden der Wohnungen: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

# Web Route für Wohnungserstellung
@apartments_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_apartment():
    try:
        buildings = Building.query.all()
        
        if request.method == 'POST':
            try:
                if not request.form.get('apartment_number'):
                    flash('Wohnungsnummer ist erforderlich!', 'danger')
                    return render_template('apartments/create.html', buildings=buildings)
                
                if not request.form.get('building_id'):
                    flash('Gebäudeauswahl ist erforderlich!', 'danger')
                    return render_template('apartments/create.html', buildings=buildings)
                
                apartment = Apartment(
                    id=str(uuid.uuid4()),
                    apartment_number=request.form['apartment_number'],
                    floor=request.form.get('floor', ''),
                    area_sqm=float(request.form['area_sqm']) if request.form.get('area_sqm') else None,
                    room_count=int(request.form['room_count']) if request.form.get('room_count') else None,
                    rent_net=float(request.form['rent_net']) if request.form.get('rent_net') else None,
                    rent_additional=float(request.form['rent_additional']) if request.form.get('rent_additional') else None,
                    deposit=float(request.form['deposit']) if request.form.get('deposit') else None,
                    rent_start_date=datetime.strptime(request.form['rent_start_date'], '%Y-%m-%d').date() if request.form.get('rent_start_date') else None,
                    building_id=request.form['building_id'],
                    status=request.form.get('status', 'vacant')
                )
                
                db.session.add(apartment)
                db.session.commit()
                flash('Wohnung erfolgreich angelegt!', 'success')
                return redirect(url_for('apartments.apartments_list'))
                
            except ValueError as e:
                db.session.rollback()
                flash(f'Ungültige Eingabe: {str(e)}', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Anlegen der Wohnung: {str(e)}', 'danger')
                import traceback
                traceback.print_exc()
        
        return render_template('apartments/create.html', buildings=buildings)
    
    except Exception as e:
        print(f"❌ Error in create_apartment: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

# Web Route für Wohnungsdetails
@apartments_bp.route('/<apartment_id>')
@login_required
def apartment_detail(apartment_id):
    try:
        apartment = Apartment.query.options(
            db.joinedload(Apartment.building),
            db.joinedload(Apartment.tenants)
        ).get_or_404(apartment_id)

        meters = Meter.query.filter_by(apartment_id=apartment_id).all()
        tenants = Tenant.query.filter_by(apartment_id=apartment_id).all()

        revision_logs = (
            RevisionLog.query
            .filter_by(table_name='apartments', record_id=str(apartment_id))
            .order_by(RevisionLog.created_at.desc())
            .limit(15)
            .all()
        )

        return render_template('apartments/detail.html',
                             apartment=apartment,
                             meters=meters,
                             tenants=tenants,
                             revision_logs=revision_logs)
    except Exception as e:
        print(f"❌ Error in apartment_detail: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler beim Laden der Wohnungsdetails: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

@apartments_bp.route('/<apartment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_apartment(apartment_id):
    try:
        apartment = Apartment.query.get_or_404(apartment_id)
        buildings = Building.query.all()
        
        if request.method == 'POST':
            try:
                apartment.apartment_number = request.form['apartment_number']
                apartment.floor = request.form.get('floor', '')
                apartment.area_sqm = float(request.form['area_sqm']) if request.form.get('area_sqm') else None
                apartment.room_count = int(request.form['room_count']) if request.form.get('room_count') else None
                apartment.rent_net = float(request.form['rent_net']) if request.form.get('rent_net') else None
                apartment.rent_additional = float(request.form['rent_additional']) if request.form.get('rent_additional') else None
                apartment.deposit = float(request.form['deposit']) if request.form.get('deposit') else None
                
                if request.form.get('rent_start_date'):
                    apartment.rent_start_date = datetime.strptime(request.form['rent_start_date'], '%Y-%m-%d').date()
                
                if request.form.get('rent_end_date'):
                    apartment.rent_end_date = datetime.strptime(request.form['rent_end_date'], '%Y-%m-%d').date()
                else:
                    apartment.rent_end_date = None
                    
                apartment.building_id = request.form['building_id']
                apartment.status = request.form['status']
                
                db.session.commit()
                flash('Wohnung erfolgreich aktualisiert!', 'success')
                return redirect(url_for('apartments.apartment_detail', apartment_id=apartment.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Aktualisieren der Wohnung: {str(e)}', 'danger')
                import traceback
                traceback.print_exc()
        
        return render_template('apartments/edit.html', apartment=apartment, buildings=buildings)
    
    except Exception as e:
        print(f"❌ Error in edit_apartment: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

@apartments_bp.route('/<apartment_id>/delete', methods=['POST'])
@login_required
def delete_apartment(apartment_id):
    try:
        apartment = Apartment.query.get_or_404(apartment_id)
        
        if apartment.tenants:
            flash('Kann Wohnung nicht löschen: Es existieren noch Mieter!', 'danger')
            return redirect(url_for('apartments.apartment_detail', apartment_id=apartment_id))
        
        db.session.delete(apartment)
        db.session.commit()
        flash('Wohnung erfolgreich gelöscht!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen der Wohnung: {str(e)}', 'danger')
        import traceback
        traceback.print_exc()
    
    return redirect(url_for('apartments.apartments_list'))

# API Routes - Werden separat mit /api/apartments registriert
# Diese Routes haben keine Präfixe mehr, da sie in __init__.py mit url_prefix='/api/apartments' registriert werden
@apartments_bp.route('/api', methods=['GET'])
@jwt_required()
def get_apartments_api():
    try:
        apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()
        return jsonify([{
            'id': apartment.id,
            'apartment_number': apartment.apartment_number,
            'floor': apartment.floor,
            'area_sqm': float(apartment.area_sqm) if apartment.area_sqm else None,
            'room_count': apartment.room_count,
            'rent_net': float(apartment.rent_net) if apartment.rent_net else None,
            'rent_additional': float(apartment.rent_additional) if apartment.rent_additional else None,
            'deposit': float(apartment.deposit) if apartment.deposit else None,
            'rent_start_date': apartment.rent_start_date.isoformat() if apartment.rent_start_date else None,
            'rent_end_date': apartment.rent_end_date.isoformat() if apartment.rent_end_date else None,
            'status': apartment.status,
            'building_id': apartment.building_id,
            'building_name': apartment.building.name if apartment.building else None,
            'tenant_count': len(apartment.tenants),
            'created_at': apartment.created_at.isoformat(),
            'updated_at': apartment.updated_at.isoformat()
        } for apartment in apartments])
    except Exception as e:
        print(f"❌ Error in get_apartments_api: {e}")
        return jsonify({'error': str(e)}), 500

@apartments_bp.route('/api', methods=['POST'])
@jwt_required()
def create_apartment_api():
    data = request.get_json()
    
    try:
        apartment = Apartment(
            id=str(uuid.uuid4()),
            apartment_number=data['apartment_number'],
            floor=data.get('floor', ''),
            area_sqm=data.get('area_sqm'),
            room_count=data.get('room_count'),
            rent_net=data.get('rent_net'),
            rent_additional=data.get('rent_additional'),
            deposit=data.get('deposit'),
            rent_start_date=datetime.strptime(data['rent_start_date'], '%Y-%m-%d').date() if data.get('rent_start_date') else None,
            building_id=data['building_id'],
            status=data.get('status', 'vacant')
        )
        
        db.session.add(apartment)
        db.session.commit()
        
        return jsonify({
            'message': 'Wohnung erfolgreich angelegt',
            'id': apartment.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in create_apartment_api: {e}")
        return jsonify({'error': str(e)}), 400

@apartments_bp.route('/api/<apartment_id>', methods=['GET'])
@jwt_required()
def get_apartment_api(apartment_id):
    try:
        apartment = Apartment.query.options(db.joinedload(Apartment.building)).get_or_404(apartment_id)
        
        return jsonify({
            'id': apartment.id,
            'apartment_number': apartment.apartment_number,
            'floor': apartment.floor,
            'area_sqm': float(apartment.area_sqm) if apartment.area_sqm else None,
            'room_count': apartment.room_count,
            'rent_net': float(apartment.rent_net) if apartment.rent_net else None,
            'rent_additional': float(apartment.rent_additional) if apartment.rent_additional else None,
            'deposit': float(apartment.deposit) if apartment.deposit else None,
            'rent_start_date': apartment.rent_start_date.isoformat() if apartment.rent_start_date else None,
            'rent_end_date': apartment.rent_end_date.isoformat() if apartment.rent_end_date else None,
            'status': apartment.status,
            'building_id': apartment.building_id,
            'building_name': apartment.building.name if apartment.building else None,
            'created_at': apartment.created_at.isoformat(),
            'updated_at': apartment.updated_at.isoformat()
        })
    except Exception as e:
        print(f"❌ Error in get_apartment_api: {e}")
        return jsonify({'error': str(e)}), 500

@apartments_bp.route('/api/<apartment_id>', methods=['PUT'])
@jwt_required()
def update_apartment_api(apartment_id):
    try:
        apartment = Apartment.query.get_or_404(apartment_id)
        data = request.get_json()
        
        apartment.apartment_number = data.get('apartment_number', apartment.apartment_number)
        apartment.floor = data.get('floor', apartment.floor)
        apartment.area_sqm = data.get('area_sqm', apartment.area_sqm)
        apartment.room_count = data.get('room_count', apartment.room_count)
        apartment.rent_net = data.get('rent_net', apartment.rent_net)
        apartment.rent_additional = data.get('rent_additional', apartment.rent_additional)
        apartment.deposit = data.get('deposit', apartment.deposit)
        
        if data.get('rent_start_date'):
            apartment.rent_start_date = datetime.strptime(data['rent_start_date'], '%Y-%m-%d').date()
        
        if data.get('rent_end_date'):
            apartment.rent_end_date = datetime.strptime(data['rent_end_date'], '%Y-%m-%d').date()
        else:
            apartment.rent_end_date = None
            
        apartment.building_id = data.get('building_id', apartment.building_id)
        apartment.status = data.get('status', apartment.status)
        
        db.session.commit()
        
        return jsonify({'message': 'Wohnung erfolgreich aktualisiert'})
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error in update_apartment_api: {e}")
        return jsonify({'error': str(e)}), 500