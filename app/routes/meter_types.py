from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from app.models import MeterType
from app.routes.main import login_required
from app.extensions import db
import uuid

meter_types_bp = Blueprint('meter_types', __name__)

@meter_types_bp.route('/')
@login_required
def meter_types_list():
    meter_types = MeterType.query.order_by(MeterType.name).all()
    return render_template('meter_types/list.html', meter_types=meter_types)

@meter_types_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_meter_type():
    if request.method == 'POST':
        try:
            meter_type = MeterType(
                id=str(uuid.uuid4()),
                name=request.form['name'],
                category=request.form['category'],
                unit=request.form['unit'],
                decimal_places=int(request.form.get('decimal_places', 0)),
                is_active=bool(request.form.get('is_active', True))
            )
            
            db.session.add(meter_type)
            db.session.commit()
            flash('Zählertyp erfolgreich angelegt!', 'success')
            return redirect(url_for('meter_types.meter_types_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Anlegen des Zählertyps: {str(e)}', 'danger')
    
    # Kategorien für Dropdown
    categories = ['electricity', 'water', 'gas', 'heating', 'renewable', 'special', 'other']
    return render_template('meter_types/create.html', categories=categories)

@meter_types_bp.route('/<meter_type_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_meter_type(meter_type_id):
    meter_type = MeterType.query.get_or_404(meter_type_id)
    
    if request.method == 'POST':
        try:
            meter_type.name = request.form['name']
            meter_type.category = request.form['category']
            meter_type.unit = request.form['unit']
            meter_type.decimal_places = int(request.form.get('decimal_places', 0))
            meter_type.is_active = bool(request.form.get('is_active', True))
            
            db.session.commit()
            flash('Zählertyp erfolgreich aktualisiert!', 'success')
            return redirect(url_for('meter_types.meter_types_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren des Zählertyps: {str(e)}', 'danger')
    
    categories = ['electricity', 'water', 'gas', 'heating', 'renewable', 'special', 'other']
    return render_template('meter_types/edit.html', meter_type=meter_type, categories=categories)

@meter_types_bp.route('/<meter_type_id>/delete', methods=['POST'])
@login_required
def delete_meter_type(meter_type_id):
    meter_type = MeterType.query.get_or_404(meter_type_id)
    
    try:
        # Prüfen ob der Zählertyp verwendet wird
        from app.models import Meter
        meter_count = Meter.query.filter_by(meter_type_id=meter_type_id).count()
        if meter_count > 0:
            flash(f'Kann Zählertyp nicht löschen: Er wird noch von {meter_count} Zählern verwendet!', 'danger')
            return redirect(url_for('meter_types.meter_types_list'))
        
        db.session.delete(meter_type)
        db.session.commit()
        flash('Zählertyp erfolgreich gelöscht!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen des Zählertyps: {str(e)}', 'danger')
    
    return redirect(url_for('meter_types.meter_types_list'))

@meter_types_bp.route('/<meter_type_id>/toggle', methods=['POST'])
@login_required
def toggle_meter_type(meter_type_id):
    meter_type = MeterType.query.get_or_404(meter_type_id)
    
    try:
        meter_type.is_active = not meter_type.is_active
        db.session.commit()
        
        status = "aktiviert" if meter_type.is_active else "deaktiviert"
        flash(f'Zählertyp erfolgreich {status}!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Ändern des Zählertyps: {str(e)}', 'danger')
    
    return redirect(url_for('meter_types.meter_types_list'))