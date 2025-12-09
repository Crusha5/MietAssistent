from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session
from flask_jwt_extended import jwt_required
from app.extensions import db
from app.models import Tenant, Apartment, Building, TenantAuditLog, User, Contract
from datetime import datetime
from app.routes.main import login_required
import uuid

tenants_bp = Blueprint('tenants', __name__)

@tenants_bp.route('/')
@login_required
def tenants_list():
    try:
        # Immer frische Daten laden, um Browser-Cache-Effekte zu umgehen
        db.session.expire_all()
        q = request.args.get('q', '').strip().lower()
        building_id = request.args.get('building_id')
        apartment_id = request.args.get('apartment_id')

        query = Tenant.query.options(
            db.joinedload(Tenant.apartment).joinedload(Apartment.building)
        )

        if building_id:
            query = query.join(Apartment).filter(Apartment.building_id == building_id)
        if apartment_id:
            query = query.filter(Tenant.apartment_id == apartment_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                db.or_(Tenant.first_name.ilike(like), Tenant.last_name.ilike(like), Tenant.email.ilike(like))
            )

        tenants = query.all()
        buildings = Building.query.all()
        apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()

        return render_template('tenants/list.html', tenants=tenants, buildings=buildings, apartments=apartments)
    except Exception as e:
        print(f"❌ Error in tenants_list: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500

@tenants_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_tenant():
    apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()
    
    if request.method == 'POST':
        try:
            tenant = Tenant(
                id=str(uuid.uuid4()),
                first_name=request.form['first_name'],
                last_name=request.form['last_name'],
                email=request.form.get('email'),
                phone=request.form.get('phone'),
                move_in_date=datetime.strptime(request.form['move_in_date'], '%Y-%m-%d').date(),
                apartment_id=request.form['apartment_id'],
                status='active',
                is_primary_tenant='is_primary_tenant' in request.form
            )
            
            # Handle optional fields
            if request.form.get('date_of_birth'):
                tenant.date_of_birth = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
            
            tenant.emergency_contact_name = request.form.get('emergency_contact_name')
            tenant.emergency_contact_phone = request.form.get('emergency_contact_phone')
            
            db.session.add(tenant)
            db.session.commit()
            
            # Audit-Log für Erstellung - mit User-Prüfung
            user_id = session.get('user_id')
            if user_id:
                tenant.log_creation(user_id=user_id, request=request)
                db.session.commit()
            else:
                print("⚠️ WARNING: Could not create audit log - no user_id in session")
            
            # Wohnungsstatus aktualisieren
            apartment = Apartment.query.get(tenant.apartment_id)
            if apartment:
                apartment.update_occupancy_status()
            
            flash('✅ Mieter erfolgreich angelegt!', 'success')
            return redirect(url_for('tenants.tenants_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Anlegen des Mieters: {str(e)}', 'danger')
    
    return render_template('tenants/create.html', apartments=apartments)

@tenants_bp.route('/<tenant_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    old_apartment_id = tenant.apartment_id
    user_id = session.get('user_id')
    
    # Alte Werte für Vergleich speichern
    old_values = {
        'first_name': tenant.first_name,
        'last_name': tenant.last_name,
        'email': tenant.email,
        'phone': tenant.phone,
        'date_of_birth': tenant.date_of_birth,
        'move_in_date': tenant.move_in_date,
        'move_out_date': tenant.move_out_date,
        'apartment_id': tenant.apartment_id,
        'is_primary_tenant': tenant.is_primary_tenant,
        'emergency_contact_name': tenant.emergency_contact_name,
        'emergency_contact_phone': tenant.emergency_contact_phone,
        'status': tenant.status
    }
    
    if request.method == 'POST':
        try:
            # Felder aktualisieren und Änderungen protokollieren
            fields_to_check = [
                'first_name', 'last_name', 'email', 'phone', 'date_of_birth',
                'move_in_date', 'move_out_date', 'apartment_id', 'is_primary_tenant',
                'emergency_contact_name', 'emergency_contact_phone', 'status'
            ]
            
            for field in fields_to_check:
                old_value = old_values.get(field)
                
                if field == 'date_of_birth':
                    new_value = datetime.strptime(request.form[field], '%Y-%m-%d').date() if request.form.get(field) else None
                elif field == 'move_in_date':
                    new_value = datetime.strptime(request.form[field], '%Y-%m-%d').date()
                elif field == 'move_out_date':
                    new_value = datetime.strptime(request.form[field], '%Y-%m-%d').date() if request.form.get(field) else None
                elif field == 'is_primary_tenant':
                    new_value = field in request.form
                elif field == 'apartment_id':
                    new_value = request.form[field]
                elif field == 'status':
                    # Status wird basierend auf move_out_date gesetzt
                    new_value = 'moved_out' if request.form.get('move_out_date') else 'active'
                else:
                    new_value = request.form.get(field)
                
                # Aktuellen Wert setzen
                if field == 'status':
                    setattr(tenant, field, new_value)
                elif field in ['first_name', 'last_name', 'email', 'phone', 'emergency_contact_name', 'emergency_contact_phone']:
                    setattr(tenant, field, new_value)
                elif field in ['date_of_birth', 'move_in_date', 'move_out_date', 'apartment_id', 'is_primary_tenant']:
                    setattr(tenant, field, new_value)
                
                # Änderung protokollieren wenn nötig
                if str(old_value) != str(new_value):
                    # Spezielle Behandlung für Wohnungswechsel
                    if field == 'apartment_id' and old_value != new_value:
                        old_apartment = Apartment.query.get(old_value)
                        new_apartment = Apartment.query.get(new_value)
                        old_apt_name = f"{old_apartment.building.name} - {old_apartment.apartment_number}" if old_apartment and old_apartment.building else old_value
                        new_apt_name = f"{new_apartment.building.name} - {new_apartment.apartment_number}" if new_apartment and new_apartment.building else new_value
                        tenant.log_field_change(user_id, field, old_apt_name, new_apt_name, request)
                    else:
                        tenant.log_field_change(user_id, field, old_value, new_value, request)
            
            db.session.commit()
            
            # Wohnungsstatus für alte und neue Wohnung aktualisieren
            if old_apartment_id != tenant.apartment_id:
                old_apartment = Apartment.query.get(old_apartment_id)
                if old_apartment:
                    old_apartment.update_occupancy_status()
            
            new_apartment = Apartment.query.get(tenant.apartment_id)
            if new_apartment:
                new_apartment.update_occupancy_status()
            
            flash('Mieter erfolgreich aktualisiert!', 'success')
            return redirect(url_for('tenants.tenant_detail', tenant_id=tenant.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren des Mieters: {str(e)}', 'danger')
    
    apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()
    return render_template('tenants/edit.html', tenant=tenant, apartments=apartments)

@tenants_bp.route('/<tenant_id>/move-out', methods=['POST'])
@login_required
def move_out_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    user_id = session.get('user_id')
    
    # Debug-Ausgabe
    print(f"🔍 DEBUG: move_out_tenant - User ID from session: {user_id}")
    
    try:
        tenant.move_out_date = datetime.utcnow().date()
        tenant.status = 'moved_out'
        
        # Sicherstellen, dass user_id gesetzt ist
        if not user_id:
            # Fallback: Ersten Admin-User finden
            admin_user = User.query.filter_by(role='admin').first()
            if admin_user:
                user_id = admin_user.id
                print(f"⚠️ Using fallback user_id: {user_id}")
        
        # Audit-Log für Auszug
        if user_id:
            tenant.log_move_out(user_id, request)
        else:
            print("❌ ERROR: Cannot create audit log - no user_id available")
        
        db.session.commit()
        
        # Wohnungsstatus aktualisieren
        if tenant.apartment:
            tenant.apartment.update_occupancy_status()
            
        flash('Auszug erfolgreich erfasst!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Erfassen des Auszugs: {str(e)}', 'danger')
    
    return redirect(url_for('tenants.tenant_detail', tenant_id=tenant.id))

@tenants_bp.route('/<tenant_id>')
@login_required
def tenant_detail(tenant_id):
    try:
        tenant = Tenant.query.options(
            db.joinedload(Tenant.apartment).joinedload(Apartment.building)
        ).get_or_404(tenant_id)

        # Load documents for this tenant
        from app.models import Document
        documents = Document.query.filter_by(documentable_type='tenant', documentable_id=tenant_id).all()
        
        # Audit-Logs für diesen Mieter laden
        audit_logs = TenantAuditLog.query.filter_by(tenant_id=tenant_id)\
            .options(db.joinedload(TenantAuditLog.user))\
            .order_by(TenantAuditLog.created_at.desc())\
            .all()
        
        latest_contract = Contract.query.filter_by(tenant_id=tenant_id).order_by(Contract.start_date.desc()).first()

        return render_template('tenants/detail.html',
                             tenant=tenant,
                             documents=documents,
                             audit_logs=audit_logs,
                             latest_contract=latest_contract,
                             now=datetime.utcnow())
    except Exception as e:
        print(f"❌ Error in tenant_detail: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler beim Laden der Mieterdetails: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

@tenants_bp.route('/<tenant_id>/reactivate', methods=['POST'])
@login_required
def reactivate_tenant(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    user_id = session.get('user_id')
    
    try:
        tenant.move_out_date = None
        tenant.status = 'active'
        
        # Audit-Log für Reaktivierung
        tenant.log_reactivation(user_id, request)
        
        db.session.commit()
        
        # Wohnungsstatus aktualisieren
        if tenant.apartment:
            tenant.apartment.update_occupancy_status()
            
        flash('Mieter erfolgreich reaktiviert!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Reaktivieren: {str(e)}', 'danger')
    
    return redirect(url_for('tenants.tenant_detail', tenant_id=tenant.id))


# API Routes
@tenants_bp.route('/api', methods=['GET'])
@jwt_required()
def get_tenants_api():
    tenants = Tenant.query.all()
    return jsonify([{
        'id': tenant.id,
        'first_name': tenant.first_name,
        'last_name': tenant.last_name,
        'email': tenant.email,
        'phone': tenant.phone,
        'move_in_date': tenant.move_in_date.isoformat() if tenant.move_in_date else None,
        'move_out_date': tenant.move_out_date.isoformat() if tenant.move_out_date else None,
        'apartment_number': tenant.apartment.apartment_number if tenant.apartment else None,
        'apartment_id': tenant.apartment_id
    } for tenant in tenants])

@tenants_bp.route('/api/<tenant_id>', methods=['GET'])
@jwt_required()
def get_tenant_api(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    return jsonify({
        'id': tenant.id,
        'first_name': tenant.first_name,
        'last_name': tenant.last_name,
        'email': tenant.email,
        'phone': tenant.phone,
        'move_in_date': tenant.move_in_date.isoformat(),
        'move_out_date': tenant.move_out_date.isoformat() if tenant.move_out_date else None,
        'apartment_id': tenant.apartment_id
    })

@tenants_bp.route('/api', methods=['POST'])
@jwt_required()
def create_tenant_api():
    data = request.get_json()
    
    apartment = Apartment.query.get(data['apartment_id'])
    if not apartment:
        return jsonify({'error': 'Wohnung nicht gefunden'}), 404
    
    tenant = Tenant(
        id=str(uuid.uuid4()),
        first_name=data['first_name'],
        last_name=data['last_name'],
        email=data.get('email'),
        phone=data.get('phone'),
        move_in_date=datetime.strptime(data['move_in_date'], '%Y-%m-%d').date(),
        apartment_id=data['apartment_id']
    )
    
    db.session.add(tenant)
    db.session.commit()
    
    return jsonify({
        'message': 'Mieter erfolgreich angelegt', 
        'id': tenant.id
    }), 201

@tenants_bp.route('/api/<tenant_id>', methods=['PUT'])
@jwt_required()
def update_tenant_api(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json()
    
    tenant.first_name = data.get('first_name', tenant.first_name)
    tenant.last_name = data.get('last_name', tenant.last_name)
    tenant.email = data.get('email', tenant.email)
    tenant.phone = data.get('phone', tenant.phone)
    
    if data.get('move_in_date'):
        tenant.move_in_date = datetime.strptime(data['move_in_date'], '%Y-%m-%d').date()
    
    if data.get('move_out_date'):
        tenant.move_out_date = datetime.strptime(data['move_out_date'], '%Y-%m-%d').date()
    else:
        tenant.move_out_date = None
        
    tenant.apartment_id = data.get('apartment_id', tenant.apartment_id)
    
    db.session.commit()
    
    return jsonify({'message': 'Mieter erfolgreich aktualisiert'})

@tenants_bp.route('/api/<tenant_id>/move-out', methods=['POST'])
@jwt_required()
def move_out_tenant_api(tenant_id):
    tenant = Tenant.query.get_or_404(tenant_id)
    tenant.move_out_date = datetime.utcnow().date()
    db.session.commit()
    
    return jsonify({'message': 'Auszug erfolgreich erfasst'})