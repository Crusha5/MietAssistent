from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app
from flask_jwt_extended import jwt_required
from app.extensions import db
from app.routes.main import login_required
from datetime import datetime
import uuid
import json
import os
import re

from app.routes.contract_editor import load_contract_tree
from app.models import Landlord, Protocol, Meter, MeterReading, Document, Tenant
from app.utils.schema_helpers import ensure_archiving_columns
from app.utils.pdf_generator import generate_professional_contract_html, save_contract_pdf

contracts_bp = Blueprint('contracts', __name__)


def ensure_writable_dir(path: str):
    """Erstellt ein Verzeichnis falls nötig und stellt Schreibrechte sicher."""
    if not path:
        path = os.path.abspath('/home/pascal/docker-services/rental-management/uploads')

    try:
        os.makedirs(path, mode=0o775, exist_ok=True)
        if not os.access(path, os.W_OK):
            os.chmod(path, 0o775)
    except PermissionError:
        # Letzter Versuch mit großzügigeren Rechten
        os.makedirs(path, mode=0o777, exist_ok=True)
        os.chmod(path, 0o777)

# Späte Import-Funktion um Zirkelbezüge zu vermeiden
def get_contract_models():
    """Importiert Models erst bei Bedarf - vermeidet Zirkelbezüge"""
    try:
        ensure_archiving_columns()
        from app.models import Contract, ContractTemplate, Apartment, Tenant, ContractRevision, User
        return Contract, ContractTemplate, Apartment, Tenant, ContractRevision, User
    except ImportError as e:
        current_app.logger.error(f"Model import error in contracts: {e}")
        return None, None, None, None, None, None

# EINFACHE DEBUG ROUTE - Ohne Model-Import
@contracts_bp.route('/debug/test')
def debug_test():
    return jsonify({
        "status": "contracts blueprint is working", 
        "timestamp": datetime.now().isoformat(),
        "message": "Basic blueprint route works"
    })

@contracts_bp.route('/debug/health')
def health_check():
    """Health Check ohne Model-Abhängigkeiten"""
    return jsonify({
        "status": "healthy",
        "blueprint": "contracts",
        "models_available": get_contract_models()[0] is not None
    })

@contracts_bp.route('/')
@login_required
def contracts_list():
    """Liste aller Mietverträge"""
    try:
        Contract, _, _, _, _, _ = get_contract_models()
        if Contract is None:
            current_app.logger.error("Contract models not available")
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return render_template('contracts/list.html', contracts=[])
        
        q = (request.args.get('q') or '').strip()
        status = (request.args.get('status') or '').strip()
        archived_filter = request.args.get('archived', 'active')

        query = Contract.query.options(
            db.joinedload(Contract.apartment),
            db.joinedload(Contract.tenant),
            db.joinedload(Contract.template)
        )

        if q:
            like_term = f"%{q}%"
            query = query.join(Tenant, Contract.tenant_id == Tenant.id).filter(
                db.or_(
                    Contract.contract_number.ilike(like_term),
                    Tenant.first_name.ilike(like_term),
                    Tenant.last_name.ilike(like_term)
                )
            )

        if status:
            if status == 'archived':
                query = query.filter(Contract.is_archived.is_(True))
            else:
                query = query.filter(Contract.status == status)

        if archived_filter != 'all' and status != 'archived':
            query = query.filter(
                (Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None))
            )

        contracts = query.order_by(Contract.created_at.desc()).all()
        
        current_app.logger.info(f"Loaded {len(contracts)} contracts")
        return render_template(
            'contracts/list.html',
            contracts=contracts,
            q=q,
            status=status,
            archived_filter=archived_filter
        )
        
    except Exception as e:
        current_app.logger.error(f"Error in contracts_list: {str(e)}", exc_info=True)
        flash(f'Fehler beim Laden der Mietverträge: {str(e)}', 'danger')
        return render_template('contracts/list.html', contracts=[])

@contracts_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_contract():
    """Neuen Mietvertrag erstellen"""
    try:
        Contract, ContractTemplate, Apartment, Tenant, ContractRevision, User = get_contract_models()

        if None in [Contract, Apartment, Tenant]:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contracts_list'))

        apartments = Apartment.query.all()
        tenants = Tenant.query.all()
        landlords = Landlord.query.filter_by(is_active=True).all()
        templates = ContractTemplate.query.filter_by(template_type='mietvertrag', is_active=True).all() if ContractTemplate else []

        current_app.logger.info(f"Create contract - Apartments: {len(apartments)}, Tenants: {len(tenants)}")

        if request.method == 'POST':
            try:
                # Validierung
                if not request.form.get('apartment_id'):
                    flash('Bitte wählen Sie eine Wohnung aus!', 'danger')
                    return render_template('contracts/create.html',
                                           apartments=apartments,
                                           tenants=tenants,
                                           landlords=landlords,
                                           templates=templates)

                if not request.form.get('tenant_id'):
                    flash('Bitte wählen Sie einen Mieter aus!', 'danger')
                    return render_template('contracts/create.html',
                                           apartments=apartments,
                                           tenants=tenants,
                                           landlords=landlords,
                                           templates=templates)

                # Vertragsnummer generieren
                contract_number = f"MV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

                contract = Contract(
                    id=str(uuid.uuid4()),
                    contract_number=contract_number,
                    template_id=request.form.get('template_id'),
                    apartment_id=request.form['apartment_id'],
                    tenant_id=request.form['tenant_id'],
                    contract_type=request.form.get('contract_type', 'hauptmietvertrag'),
                    landlord_id=request.form.get('landlord_id') or None,
                    start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
                    end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None,
                    rent_net=float(request.form['rent_net']),
                    rent_additional=float(request.form.get('rent_additional', 0)),
                    deposit=float(request.form.get('deposit', 0)),
                    notice_period=int(request.form.get('notice_period', 3)),
                    additional_agreements=request.form.get('special_agreements'),
                    contract_data=json.dumps(dict(request.form)),
                    created_by=session.get('user_id')
                )

                db.session.add(contract)

                # Mietdaten an Wohnung spiegeln
                apartment = Apartment.query.get(contract.apartment_id)
                if apartment:
                    apartment.rent_net = contract.rent_net
                    apartment.rent_additional = contract.rent_additional
                    apartment.deposit = contract.deposit
                    db.session.add(apartment)

                # Erste Revision erstellen
                if ContractRevision:
                    revision = ContractRevision(
                        id=str(uuid.uuid4()),
                        contract_id=contract.id,
                        revision_number=1,
                        changed_by=session.get('user_id'),
                        change_description="Vertrag initial erstellt",
                        new_data=json.dumps(dict(request.form))
                    )
                    db.session.add(revision)

                db.session.commit()

                current_app.logger.info(f"Contract created: {contract.contract_number}")
                flash('Mietvertrag erfolgreich erstellt!', 'success')
                return redirect(url_for('contracts.contract_detail', contract_id=contract.id))

            except ValueError as e:
                db.session.rollback()
                flash(f'Ungültige Eingabe: {str(e)}', 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating contract: {str(e)}", exc_info=True)
                flash(f'Fehler beim Erstellen des Mietvertrags: {str(e)}', 'danger')

        return render_template('contracts/create.html',
                               apartments=apartments,
                               tenants=tenants,
                               landlords=landlords,
                               templates=templates)

    except Exception as e:
        current_app.logger.error(f"Error in create_contract: {str(e)}", exc_info=True)
        flash(f'Fehler: {str(e)}', 'danger')
        return render_template('contracts/create.html',
                               apartments=[],
                               tenants=[],
                               landlords=[],
                               templates=[])

@contracts_bp.route('/<contract_id>')
@login_required
def contract_detail(contract_id):
    """Mietvertrag Details - Vereinfachte und robuste Version"""
    try:
        Contract, _, Apartment, Tenant, _, _ = get_contract_models()
        
        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return render_template('contracts/detail.html', 
                                 contract=None,
                                 message="Modelle nicht verfügbar")
        
        # Einfache Abfrage ohne komplexe Joins
        contract = Contract.query.get(contract_id)
        if not contract:
            flash('Vertrag nicht gefunden', 'danger')
            return redirect(url_for('contracts.contracts_list'))
        
        # Debug-Info
        current_app.logger.info(f"✅ Contract loaded: {contract.contract_number}")
        current_app.logger.info(f"📊 Contract status: {contract.status}")
        
        # Manuell die Beziehungen laden falls nötig
        if contract.apartment_id and not contract.apartment:
            contract.apartment = Apartment.query.get(contract.apartment_id)

        if contract.tenant_id and not contract.tenant:
            contract.tenant = Tenant.query.get(contract.tenant_id)

        if contract.landlord_id and not contract.landlord:
            contract.landlord = Landlord.query.get(contract.landlord_id)

        return render_template('contracts/detail.html', contract=contract)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error loading contract {contract_id}: {str(e)}", exc_info=True)
        
        # Fallback: Zeige minimale Vertragsinfo
        try:
            Contract, _, _, _, _, _ = get_contract_models()
            contract = Contract.query.get(contract_id)
            if contract:
                flash(f'Vertrag geladen, aber mit Einschränkungen: {str(e)}', 'warning')
                return render_template('contracts/detail.html', contract=contract)
        except:
            pass
            
        flash(f'Fehler beim Laden der Vertragsdetails: {str(e)}', 'danger')
        return redirect(url_for('contracts.contracts_list'))


@contracts_bp.route('/<contract_id>/archive', methods=['POST'])
@login_required
def archive_contract(contract_id):
    Contract, _, Apartment, _, _, _ = get_contract_models()
    ensure_archiving_columns()

    if Contract is None:
        flash('Vertrag konnte nicht geladen werden.', 'danger')
        return redirect(url_for('contracts.contracts_list'))

    contract = Contract.query.get_or_404(contract_id)
    if contract.status == 'active':
        flash('Aktive Mietverhältnisse können nicht archiviert werden.', 'warning')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    try:
        contract.status = 'archived'
        contract.is_archived = True

        protocols = Protocol.query.filter_by(contract_id=contract_id).all()
        for proto in protocols:
            proto.is_archived = True

        meters = []
        if contract.apartment_id:
            meters = Meter.query.filter_by(apartment_id=contract.apartment_id).all()
        meter_ids = [m.id for m in meters]
        if meter_ids:
            MeterReading.query.filter(MeterReading.meter_id.in_(meter_ids)).update({'is_archived': True}, synchronize_session=False)

        Document.query.filter(Document.documentable_id == contract_id).update({'is_archived': True}, synchronize_session=False)
        if protocols:
            Document.query.filter(Document.documentable_id.in_([p.id for p in protocols])).update({'is_archived': True}, synchronize_session=False)

        db.session.commit()
        flash('Vertrag und zugehörige Daten wurden archiviert.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Archivierung fehlgeschlagen: %s', exc, exc_info=True)
        flash(f'Archivierung fehlgeschlagen: {exc}', 'danger')

    return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
    
@contracts_bp.route('/<contract_id>/test')
@login_required
def test_contract_loading(contract_id):
    """Testet das Laden eines Vertrags"""
    try:
        Contract, _, Apartment, Tenant, _, _ = get_contract_models()
        
        # Test 1: Einfaches Laden
        contract = Contract.query.get(contract_id)
        if not contract:
            return jsonify({"error": "Contract not found"})
        
        result = {
            "contract_found": True,
            "contract_number": contract.contract_number,
            "apartment_id": contract.apartment_id,
            "tenant_id": contract.tenant_id
        }
        
        # Test 2: Mit Joins laden
        try:
            contract_with_joins = Contract.query.options(
                db.joinedload(Contract.apartment),
                db.joinedload(Contract.tenant)
            ).get(contract_id)
            result["joins_successful"] = True
            result["has_apartment"] = contract_with_joins.apartment is not None
            result["has_tenant"] = contract_with_joins.tenant is not None
        except Exception as e:
            result["joins_error"] = str(e)
            result["joins_successful"] = False
        
        # Test 3: Template laden
        try:
            if contract.template_id:
                from app.models import ContractTemplate
                template = ContractTemplate.query.get(contract.template_id)
                result["has_template"] = template is not None
        except Exception as e:
            result["template_error"] = str(e)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500
    
@contracts_bp.route('/debug/table-info')
def debug_table_info():
    """Zeigt Informationen über die contracts-Tabelle"""
    from sqlalchemy import inspect, text
    
    inspector = inspect(db.engine)
    columns = inspector.get_columns('contracts')
    
    column_info = []
    for col in columns:
        column_info.append({
            'name': col['name'],
            'type': str(col['type']),
            'nullable': col['nullable'],
            'default': col['default']
        })
    
    return jsonify({
        "table": "contracts",
        "columns": column_info,
        "count": len(columns)
    })
    
@contracts_bp.route('/<contract_id>/terminate', methods=['POST'])
@login_required
def terminate_contract(contract_id):
    """Vertrag kündigen"""
    try:
        Contract, _, _, _, ContractRevision, _ = get_contract_models()
        
        contract = Contract.query.get_or_404(contract_id)
        landlords = Landlord.query.filter_by(is_active=True).all()
        contract.status = 'terminated'
        
        if ContractRevision:
            revision = ContractRevision(
                id=str(uuid.uuid4()),
                contract_id=contract.id,
                revision_number=len(contract.revisions) + 1,
                changed_by=session.get('user_id'),
                change_description="Vertrag gekündigt",
                old_data=json.dumps({'status': contract.status}),
                new_data=json.dumps({'status': 'terminated'})
            )
            db.session.add(revision)
        
        db.session.commit()
        
        current_app.logger.info(f"Contract terminated: {contract.contract_number}")
        flash('Vertrag erfolgreich gekündigt!', 'success')
        return redirect(url_for('contracts.contract_detail', contract_id=contract.id))
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error terminating contract {contract_id}: {str(e)}", exc_info=True)
        flash(f'Fehler beim Kündigen des Vertrags: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


@contracts_bp.route('/<contract_id>/duplicate', methods=['POST'])
@login_required
def duplicate_contract(contract_id):
    """Erstellt eine Kopie eines bestehenden Vertrags als neuen Entwurf."""
    try:
        Contract, _, Apartment, Tenant, ContractRevision, _ = get_contract_models()
        if Contract is None:
            flash('Vertragsmodelle sind nicht verfügbar.', 'warning')
            return redirect(url_for('contracts.contracts_list'))

        original = Contract.query.get_or_404(contract_id)

        duplicate = Contract(
            id=str(uuid.uuid4()),
            contract_number=f"MV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            template_id=original.template_id,
            apartment_id=original.apartment_id,
            tenant_id=original.tenant_id,
            landlord_id=original.landlord_id,
            contract_type=original.contract_type,
            start_date=original.start_date,
            end_date=original.end_date,
            rent_net=original.rent_net,
            rent_additional=original.rent_additional,
            deposit=original.deposit,
            notice_period=original.notice_period,
            status='draft',
            contract_data=original.contract_data,
            additional_agreements=(original.additional_agreements or '') + ('\n\nKopie' if original.additional_agreements else 'Kopie'),
            created_by=session.get('user_id')
        )

        db.session.add(duplicate)

        if ContractRevision:
            revision = ContractRevision(
                id=str(uuid.uuid4()),
                contract_id=duplicate.id,
                revision_number=1,
                changed_by=session.get('user_id'),
                change_description=f"Dupliziert von Vertrag {original.contract_number}",
                old_data=None,
                new_data=json.dumps({'source_contract': original.id})
            )
            db.session.add(revision)

        db.session.commit()
        flash('Vertrag dupliziert. Der Entwurf kann nun angepasst werden.', 'success')
        return redirect(url_for('contracts.edit_contract', contract_id=duplicate.id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error duplicating contract {contract_id}: {str(e)}", exc_info=True)
        flash(f'Vertrag konnte nicht dupliziert werden: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

@contracts_bp.route('/<contract_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_contract(contract_id):
    """Mietvertrag bearbeiten"""
    try:
        Contract, _, _, _, ContractRevision, _ = get_contract_models()
        landlords = Landlord.query.filter_by(is_active=True).all()

        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contracts_list'))
        
        contract = Contract.query.get_or_404(contract_id)
        
        if request.method == 'POST':
            try:
                if not request.form.get('change_description'):
                    flash('Bitte geben Sie einen Änderungsgrund an!', 'danger')
                    return render_template('contracts/edit.html', contract=contract, landlords=landlords)
                
                # Alte Daten für Revision speichern
                old_data = {
                    'contract_type': contract.contract_type,
                    'start_date': contract.start_date.isoformat() if contract.start_date else None,
                    'end_date': contract.end_date.isoformat() if contract.end_date else None,
                    'rent_net': contract.rent_net,
                    'rent_additional': contract.rent_additional,
                    'deposit': contract.deposit,
                    'notice_period': contract.notice_period,
                    'status': contract.status,
                    'landlord_id': contract.landlord_id,
                    'additional_agreements': contract.additional_agreements,
                }
                
                # Vertragsdaten aktualisieren
                contract.contract_type = request.form.get('contract_type', contract.contract_type)
                contract.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
                
                if request.form.get('end_date'):
                    contract.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
                else:
                    contract.end_date = None
                    
                contract.rent_net = float(request.form['rent_net'])
                contract.rent_additional = float(request.form.get('rent_additional', 0))
                contract.deposit = float(request.form.get('deposit', 0))
                contract.notice_period = int(request.form.get('notice_period', 3))
                contract.status = request.form.get('status', contract.status)
                contract.landlord_id = request.form.get('landlord_id') or None
                contract.additional_agreements = request.form.get('additional_agreements')
                contract.contract_data = json.dumps(dict(request.form))
                
                # Neue Revision erstellen
                if ContractRevision:
                    revision = ContractRevision(
                        id=str(uuid.uuid4()),
                        contract_id=contract.id,
                        revision_number=len(contract.revisions) + 1,
                        changed_by=session.get('user_id'),
                        change_description=request.form['change_description'],
                        old_data=json.dumps(old_data),
                        new_data=json.dumps(dict(request.form))
                    )
                    db.session.add(revision)
                
                db.session.commit()
                
                current_app.logger.info(f"Contract updated: {contract.contract_number}")
                flash('Mietvertrag erfolgreicht aktualisiert!', 'success')
                return redirect(url_for('contracts.contract_detail', contract_id=contract.id))
                
            except ValueError as e:
                db.session.rollback()
                flash(f'Ungültige Eingabe: {str(e)}', 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating contract: {str(e)}", exc_info=True)
                flash(f'Fehler beim Aktualisieren des Mietvertrags: {str(e)}', 'danger')
        
        return render_template('contracts/edit.html', contract=contract, landlords=landlords)
    
    except Exception as e:
        current_app.logger.error(f"Error in edit_contract: {str(e)}", exc_info=True)
        flash(f'Fehler: {str(e)}', 'danger')
        return redirect(url_for('contracts.contracts_list'))
    
@contracts_bp.route('/<contract_id>/activate', methods=['POST'])
@login_required
def activate_contract(contract_id):
    """Vertrag aktivieren"""
    try:
        Contract, _, _, _, ContractRevision, _ = get_contract_models()
        
        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contracts_list'))
        
        contract = Contract.query.get_or_404(contract_id)
        contract.status = 'active'
        
        # Revision für Aktivierung erstellen
        if ContractRevision:
            revision = ContractRevision(
                id=str(uuid.uuid4()),
                contract_id=contract.id,
                revision_number=len(contract.revisions) + 1,
                changed_by=session.get('user_id'),
                change_description="Vertrag aktiviert",
                old_data=json.dumps({'status': 'draft'}),
                new_data=json.dumps({'status': 'active'})
            )
            db.session.add(revision)
        
        db.session.commit()
        
        current_app.logger.info(f"Contract activated: {contract.contract_number}")
        flash('Vertrag erfolgreich aktiviert!', 'success')
        return redirect(url_for('contracts.contract_detail', contract_id=contract.id))
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error activating contract {contract_id}: {str(e)}", exc_info=True)
        flash(f'Fehler beim Aktivieren des Vertrags: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


# In contracts.py - Erweiterte PDF-Generierung


def generate_block_based_contract_html(contract, blocks=None, inventory_items=None):
    """Generiert Vertrags-HTML basierend auf Blöcken"""
    if blocks is None:
        blocks = contract.blocks
    if inventory_items is None:
        inventory_items = contract.inventory_items

    def _clean_bullet_markers(text: str) -> str:
        if not text:
            return text
        bullet_pattern = r"(<li[^>]*>)\\s*(?:•|&bull;|&#8226;)\\s*"
        cleaned = re.sub(bullet_pattern, r"\\1", text)
        cleaned = re.sub(r"(</li>)\\s*(?:•|&bull;|&#8226;)\\s*", r"\\1", cleaned)
        return cleaned

    variables = {
        'mieter_vorname': contract.tenant.first_name,
        'mieter_nachname': contract.tenant.last_name,
        'vermieter_name': contract.landlord.company_name or f"{contract.landlord.first_name} {contract.landlord.last_name}",
        'wohnung_adresse': f"{contract.apartment.building.street} {contract.apartment.building.street_number}",
        'miete_netto': f"{contract.rent_net:.2f}",
        'miete_nebenkosten': f"{contract.rent_additional:.2f}",
        'kaution': f"{contract.deposit:.2f}",
        'vertragsbeginn': contract.start_date.strftime('%d.%m.%Y'),
        'vertragsende': contract.end_date.strftime('%d.%m.%Y') if contract.end_date else "unbefristet",
        'datum_heute': datetime.now().strftime('%d.%m.%Y')
    }

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset=\"utf-8\">
        <link rel=\"stylesheet\" href=\"static/css/contract_pdf.css\">
    </head>
    <body class=\"contract-body\">
        <header class=\"contract-header\">
            <div>
                <div class=\"label\">Vertragsnummer</div>
                <div class=\"value\">{contract.contract_number}</div>
            </div>
            <div>
                <div class=\"label\">Erstellt am</div>
                <div class=\"value\">{variables['datum_heute']}</div>
            </div>
        </header>
        <h1 class=\"main-title\">Mietvertrag</h1>
        <section class=\"meta-grid\">
            <div>
                <div class=\"label\">Vermieter</div>
                <div class=\"value\">{variables['vermieter_name']}</div>
            </div>
            <div>
                <div class=\"label\">Mieter</div>
                <div class=\"value\">{variables['mieter_vorname']} {variables['mieter_nachname']}</div>
            </div>
            <div>
                <div class=\"label\">Adresse</div>
                <div class=\"value\">{variables['wohnung_adresse']}</div>
            </div>
            <div>
                <div class=\"label\">Mietbeginn</div>
                <div class=\"value\">{variables['vertragsbeginn']}</div>
            </div>
        </section>
        <div class=\"divider\"></div>
    """

    for block in sorted(blocks, key=lambda x: x.sort_order):
        content = block.content
        for key, value in variables.items():
            content = content.replace(f'§{key}§', str(value))
        content = _clean_bullet_markers(content)

        html_content += f"""
        <section class=\"clause\">
            <div class=\"clause-title\">{block.title}</div>
            <div class=\"clause-body\">{content}</div>
        </section>
        """

    html_content += f"""
        <section class=\"signature-block\">
            <p class=\"label\">Ort, Datum</p>
            <div class=\"signature-date-line\"></div>
            <div class=\"signature-row\">
                <div class=\"sig-cell\">
                    <div class=\"sig-line\"></div>
                    <div class=\"sig-label\">Vermieter</div>
                    <div class=\"sig-name\">{variables['vermieter_name']}</div>
                </div>
                <div class=\"sig-cell\">
                    <div class=\"sig-line\"></div>
                    <div class=\"sig-label\">Mieter</div>
                    <div class=\"sig-name\">{variables['mieter_vorname']} {variables['mieter_nachname']}</div>
                </div>
            </div>
        </section>
    </body>
    </html>
    """

    return html_content
@contracts_bp.route('/<contract_id>/generate-pdf')
@login_required
def generate_contract_pdf(contract_id):
    """
    Generiert ein professionelles PDF für einen Mietvertrag.
    Nutzt den Tree-Editor (paragraph_tree) + generate_professional_contract_html().
    Speichert PDF und erzeugt automatisch eine neue Revision.
    """

    from app.models import Contract, ContractClause, InventoryItem, ContractRevision

    # 1. Vertrag laden
    contract = Contract.query.filter_by(id=contract_id).first_or_404()

    # Berechtigungsprüfung (nur Vermieter oder Admin)
    if contract.landlord_id != session.get('user_id') and session.get('role') != 'admin':
        flash('Keine Berechtigung, um dieses PDF zu erstellen.', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    # 2. Paragraph-Tree laden
    paragraph_tree = []
    try:
        if contract.contract_data:
            data = json.loads(contract.contract_data)
            paragraph_tree = data.get('paragraph_tree', [])
    except Exception as e:
        current_app.logger.error(f"Tree-Editor Daten fehlerhaft: {e}")
        paragraph_tree = []

    # 3. Klauseln laden (falls genutzt)
    clauses = ContractClause.query.filter_by(contract_id=contract.id).order_by(
        ContractClause.sort_order.asc()
    ).all()

    # 4. Inventar laden
    inventory_items = InventoryItem.query.filter_by(contract_id=contract.id).all()

    # 5. HTML generieren
    try:
        html_content = generate_professional_contract_html(
            contract=contract,
            clauses=clauses,
            paragraph_tree=paragraph_tree,
            inventory_items=inventory_items
        )
    except Exception as e:
        current_app.logger.error(f"Fehler bei HTML-Generierung: {e}", exc_info=True)
        flash("Fehler beim Generieren des HTML-Dokuments.", "danger")
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    # 6. PDF speichern
    try:
        pdf_ok = save_contract_pdf(contract, html_content)
    except Exception as e:
        current_app.logger.error(f"PDF-Speicherfehler: {e}", exc_info=True)
        flash("Fehler beim Speichern des PDFs.", "danger")
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    if not pdf_ok:
        flash("Fehler beim PDF-Erstellen.", "danger")
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    # 7. Finale HTML-Version speichern
    contract.final_content = html_content

    # 8. Neue Revision erzeugen
    try:
        # letzte Revision suchen
        last_rev = (
            ContractRevision.query
            .filter_by(contract_id=contract.id)
            .order_by(ContractRevision.revision_number.desc())
            .first()
        )
        next_rev = (last_rev.revision_number + 1) if last_rev else 1

        revision = ContractRevision(
            id=str(uuid.uuid4()),
            contract_id=contract.id,
            revision_number=next_rev,
            changed_by=session.get('user_id'),
            change_description="PDF generiert",
            old_data=contract.final_content,
            new_data=html_content
        )
        db.session.add(revision)

    except Exception as e:
        current_app.logger.error(f"Revision konnte nicht gespeichert werden: {e}", exc_info=True)
        flash("PDF erstellt – Revision konnte aber nicht gespeichert werden.", "warning")

    db.session.commit()

    flash("PDF erfolgreich generiert!", "success")
    return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


@contracts_bp.route('/<contract_id>/download')
@login_required
def download_contract(contract_id):
    """Mietvertrag PDF herunterladen"""
    try:
        Contract, _, _, _, _, _ = get_contract_models()
        
        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contracts_list'))
        
        contract = Contract.query.get_or_404(contract_id)
        
        if not contract.pdf_path:
            flash('Für diesen Vertrag wurde noch kein PDF hochgeladen.', 'warning')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
        
        from flask import send_file
        import os
        
        upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.abspath('uploads')
        file_path = os.path.join(upload_root, 'contracts', contract.pdf_path)
        
        if not os.path.exists(file_path):
            flash('PDF-Datei wurde nicht gefunden.', 'danger')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
        
        return send_file(file_path, as_attachment=True, download_name=f"Vertrag_{contract.contract_number}.pdf")
        
    except Exception as e:
        current_app.logger.error(f"Error downloading contract {contract_id}: {str(e)}", exc_info=True)
        flash(f'Fehler beim Herunterladen: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
    
@contracts_bp.route('/<contract_id>/upload-pdf', methods=['POST'])
@login_required
def upload_contract_pdf(contract_id):
    """PDF für unterschriebenen Vertrag hochladen"""
    try:
        Contract, _, _, _, _, _ = get_contract_models()
        
        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contracts_list'))
        
        contract = Contract.query.get_or_404(contract_id)
        
        if 'pdf_file' not in request.files:
            flash('Keine Datei ausgewählt', 'danger')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
        
        file = request.files['pdf_file']
        if file.filename == '':
            flash('Keine Datei ausgewählt', 'danger')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
        
        if file and file.filename.lower().endswith('.pdf'):
            import os
            from werkzeug.utils import secure_filename
            
            filename = secure_filename(file.filename)
            unique_filename = f"contract_{contract.contract_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.abspath('uploads')
            file_path = os.path.join(upload_root, 'contracts', unique_filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
            
            contract.pdf_path = unique_filename
            db.session.commit()
            
            current_app.logger.info(f"PDF uploaded for contract: {contract.contract_number}")
            flash('PDF erfolgreich hochgeladen!', 'success')
        else:
            flash('Nur PDF-Dateien sind erlaubt', 'danger')
        
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
            
    except Exception as e:
        current_app.logger.error(f"Error uploading PDF for contract {contract_id}: {str(e)}", exc_info=True)
        flash(f'Fehler beim Hochladen des PDFs: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

# API Routes
@contracts_bp.route('/api/contracts', methods=['GET'])
@jwt_required()
def get_contracts_api():
    """API: Alle Mietverträge abrufen"""
    try:
        Contract, _, Apartment, Tenant, _, _ = get_contract_models()
        
        if Contract is None:
            return jsonify({'error': 'Contract models not available'}), 503
        
        contracts = Contract.query.options(
            db.joinedload(Contract.apartment),
            db.joinedload(Contract.tenant)
        ).all()
        
        return jsonify([{
            'id': contract.id,
            'contract_number': contract.contract_number,
            'contract_type': contract.contract_type,
            'status': contract.status,
            'start_date': contract.start_date.isoformat() if contract.start_date else None,
            'end_date': contract.end_date.isoformat() if contract.end_date else None,
            'rent_net': contract.rent_net,
            'rent_additional': contract.rent_additional,
            'deposit': contract.deposit,
            'apartment': contract.apartment.apartment_number if contract.apartment else None,
            'tenant': f"{contract.tenant.first_name} {contract.tenant.last_name}" if contract.tenant else None,
            'created_at': contract.created_at.isoformat()
        } for contract in contracts])
        
    except Exception as e:
        current_app.logger.error(f"API Error in get_contracts_api: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    

# Debug Route für Model-Status
@contracts_bp.route('/debug/models')
def debug_models():
    """Zeigt Status der Models"""
    models = get_contract_models()
    model_names = ['Contract', 'ContractTemplate', 'Apartment', 'Tenant', 'ContractRevision', 'User']
    
    status = {}
    for i, name in enumerate(model_names):
        status[name] = models[i] is not None
    
    return jsonify({
        "models_status": status,
        "all_models_available": all(models),
        "timestamp": datetime.now().isoformat()
    })
    
@contracts_bp.route('/<contract_id>/debug-info')
@login_required
def contract_debug_info(contract_id):
    """Debug-Informationen für Vertrag"""
    try:
        Contract, _, Apartment, Tenant, _, _ = get_contract_models()
        
        contract = Contract.query.get(contract_id)
        if not contract:
            return jsonify({"error": "Contract not found"})
        
        return jsonify({
            "contract_id": contract.id,
            "contract_number": contract.contract_number,
            "apartment_id": contract.apartment_id,
            "tenant_id": contract.tenant_id,
            "has_apartment": contract.apartment is not None,
            "has_tenant": contract.tenant is not None,
            "apartment_details": {
                "id": contract.apartment.id if contract.apartment else None,
                "number": contract.apartment.apartment_number if contract.apartment else None,
                "building_id": contract.apartment.building_id if contract.apartment else None,
                "has_building": contract.apartment.building is not None if contract.apartment else False
            } if contract.apartment else None
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})
    
