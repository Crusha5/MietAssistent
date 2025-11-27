# In app/routes/contract_editor.py - Komplette aktualisierte Version

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app
from app.extensions import db
from app.routes.main import login_required
from app.models import User
import uuid, json, re
from datetime import datetime


contract_editor_bp = Blueprint(
    'contract_editor',
    __name__,
    url_prefix='/contract-editor'
)

landlords_api_bp = Blueprint(
    'landlords_api',
    __name__,
    url_prefix='/api/landlords'
)


def _strip_paragraph_prefix(title: str) -> str:
    """Entfernt ein führendes Paragraphenzeichen aus einem Titel."""
    if not title:
        return title
    cleaned = title.lstrip('§').strip()
    return cleaned if cleaned else title


def _clean_bullet_markers(text: str) -> str:
    if not text:
        return text
    bullet_pattern = r"(<li[^>]*>)\\s*(?:•|&bull;|&#8226;)\\s*"
    cleaned = re.sub(bullet_pattern, r"\\1", text)
    cleaned = re.sub(r"(</li>)\\s*(?:•|&bull;|&#8226;)\\s*", r"\\1", cleaned)
    return cleaned

def get_contract_models():
    """Importiert Models erst bei Bedarf - KORRIGIERTE VERSION"""
    try:
        from app.models import Contract, ClauseTemplate, ContractClause, Apartment, Tenant, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock
        
        # StandardClauseTemplate könnte unter einem anderen Namen existieren
        # Versuchen wir es mit verschiedenen Namen:
        StandardClauseTemplate = None
        try:
            from app.models import StandardClauseTemplate
        except ImportError:
            try:
                from app.models import StandardClause
                StandardClauseTemplate = StandardClause
            except ImportError:
                # Fallback: Verwenden wir ClauseTemplate für Standard-Klauseln
                StandardClauseTemplate = ClauseTemplate
                current_app.logger.info("Using ClauseTemplate as fallback for StandardClauseTemplate")
        
        return (Contract, ClauseTemplate, ContractClause, Apartment, Tenant, 
                StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock)
    except ImportError as e:
        current_app.logger.error(f"Model import error in contract_editor: {e}")
        return (None, None, None, None, None, None, None, None, None, None)
    
def load_contract_tree(contract):
    """Lädt die Paragraphen-Struktur aus contract_data (JSON)"""
    try:
        if not contract.contract_data:
            return []
        data = json.loads(contract.contract_data)
        return data.get('paragraph_tree', [])
    except Exception:
        return []


def save_contract_tree(contract, tree):
    """Speichert die Paragraphen-Struktur in contract_data (JSON)"""
    try:
        data = {}
        if contract.contract_data:
            # Bestehende Daten (z.B. Formulardaten) nicht verlieren
            data = json.loads(contract.contract_data)
        data['paragraph_tree'] = tree
        contract.contract_data = json.dumps(data)
    except Exception as e:
        current_app.logger.error(f"Error saving contract tree JSON: {e}", exc_info=True)
        # Fallback: einfach nur Tree speichern
        contract.contract_data = json.dumps({'paragraph_tree': tree})


def _build_default_paragraph_tree(contract):
    """Erzeugt eine editierbare Standard-Struktur für den Tree-Editor."""

    def _safe(value, fallback=""):
        return value if value not in [None, ""] else fallback

    def _paragraph(title, content, category="basis"):
        return {
            'id': str(uuid.uuid4()),
            'type': 'paragraph',
            'title': title,
            'content': content,
            'category': category,
            'icon': '',
            'mandatory': False,
            'children': []
        }

    landlord = getattr(contract, 'landlord', None)
    landlord_name = _safe(getattr(landlord, 'company_name', None) or
                          f"{_safe(getattr(landlord, 'first_name', ''))} {_safe(getattr(landlord, 'last_name', ''))}".strip(),
                          "[Vermieter]")
    landlord_street = _safe(
        f"{_safe(getattr(landlord, 'street', ''))} {_safe(getattr(landlord, 'street_number', ''))}".strip(),
        "[Straße Hausnummer]"
    )
    landlord_city = _safe(
        f"{_safe(getattr(landlord, 'zip_code', ''))} {_safe(getattr(landlord, 'city', ''))}".strip(),
        "[PLZ Ort]"
    )

    tenant = getattr(contract, 'tenant', None)
    tenant_name = f"{_safe(getattr(tenant, 'first_name', '[Mieter]'))} {_safe(getattr(tenant, 'last_name', ''))}".strip()
    tenant_street = _safe(
        f"{contract.apartment.building.street} {_safe(getattr(contract.apartment.building, 'street_number', ''))}".strip()
        if getattr(contract, 'apartment', None) and getattr(contract.apartment, 'building', None) else None,
        "[Straße Hausnummer]"
    )
    tenant_city = _safe(
        f"{_safe(getattr(contract.apartment.building, 'zip_code', ''))} {_safe(getattr(contract.apartment.building, 'city', ''))}".strip()
        if getattr(contract, 'apartment', None) and getattr(contract.apartment, 'building', None) else None,
        "[Ort]"
    )

    apartment = getattr(contract, 'apartment', None)
    building = getattr(apartment, 'building', None)
    apartment_desc = "[Mietobjekt]"
    if apartment and building:
        apartment_desc = (
            f"{_safe(building.name, 'Gebäude')} - Wohnung {_safe(apartment.apartment_number, '')}, "
            f"{_safe(building.street, '')} {_safe(building.street_number, '')}, "
            f"{_safe(building.zip_code, '')} {_safe(building.city, '')}"
        )

    start_date = getattr(contract, 'start_date', None)
    end_date = getattr(contract, 'end_date', None)
    start_text = start_date.strftime('%d.%m.%Y') if start_date else '[Startdatum]'
    end_text = 'unbefristet' if not end_date else end_date.strftime('%d.%m.%Y')

    rent_net = getattr(contract, 'rent_net', 0) or 0
    rent_additional = getattr(contract, 'rent_additional', 0) or 0
    deposit = getattr(contract, 'deposit', 0) or 0
    total_rent = rent_net + rent_additional

    default_paragraphs = [
        _paragraph(
            'Vertragsparteien',
            f"""
            <strong>Vermieter:</strong><br>
            {landlord_name}<br>
            {landlord_street}<br>
            {landlord_city}<br><br>
            <strong>Mieter:</strong><br>
            {tenant_name}<br>
            {tenant_street}<br>
            {tenant_city}
            """,
            'allgemein'
        ),
        _paragraph(
            'Mietobjekt',
            f"Das Mietobjekt ist: <strong>{apartment_desc}</strong>.",
            'mietobjekt'
        ),
        _paragraph(
            'Mietdauer',
            f"Der Mietvertrag beginnt am <strong>{start_text}</strong> und endet am <strong>{end_text}</strong>.",
            'laufzeit'
        ),
        _paragraph(
            'Mietkosten',
            f"""
            Monatliche Kosten:<br>
            - Kaltmiete: {rent_net:.2f} €<br>
            - Nebenkosten: {rent_additional:.2f} €<br>
            - Gesamtmiete: {total_rent:.2f} €<br><br>
            Kaution: {deposit:.2f} €
            """,
            'kosten'
        ),
        _paragraph(
            'Datenschutz (DSGVO)',
            """
            Der Mieter willigt ein, dass seine personenbezogenen Daten (Name, Anschrift, Kontaktdaten, Zahlungsinformationen
            sowie mietvertragsbezogene Dokumente) zum Zweck der Vertragsdurchführung, Nebenkostenabrechnung und gesetzlicher
            Aufbewahrungspflichten gemäß DSGVO und BDSG verarbeitet werden dürfen. Eine Weitergabe erfolgt nur an
            Dienstleister (z.B. Ablesedienste, Zahlungsdienstleister) und Behörden, soweit dies zur Erfüllung des Vertrages
            oder gesetzlicher Pflichten erforderlich ist. Der Mieter kann Auskunft, Berichtigung, Löschung, Einschränkung der
            Verarbeitung und Datenübertragbarkeit verlangen sowie eine erteilte Einwilligung jederzeit mit Wirkung für die
            Zukunft widerrufen.
            """,
            'datenschutz'
        )
    ]

    return default_paragraphs

def _landlord_to_dict(landlord):
    return {
        'id': landlord.id,
        'name': landlord.company_name or f"{landlord.first_name} {landlord.last_name}",
        'type': landlord.type,
        'city': landlord.city,
        'email': landlord.email
    }


def _create_landlord_from_payload(data):
    # Landlord liegt an Index 7 der Rückgabe von get_contract_models()
    Landlord = get_contract_models()[7]

    return Landlord(
        id=str(uuid.uuid4()),
        type=data.get('type', 'natural'),
        first_name=data.get('first_name'),
        last_name=data.get('last_name'),
        company_name=data.get('company_name'),
        legal_form=data.get('legal_form'),
        commercial_register=data.get('commercial_register'),
        tax_id=data.get('tax_id'),
        vat_id=data.get('vat_id'),
        street=data.get('street'),
        street_number=data.get('street_number'),
        zip_code=data.get('zip_code'),
        city=data.get('city'),
        country=data.get('country', 'Deutschland'),
        phone=data.get('phone'),
        email=data.get('email'),
        website=data.get('website'),
        bank_name=data.get('bank_name'),
        iban=data.get('iban'),
        bic=data.get('bic'),
        account_holder=data.get('account_holder'),
        representative=data.get('representative'),
        birth_date=datetime.strptime(data['birth_date'], '%Y-%m-%d').date() if data.get('birth_date') else None
    )


def _update_landlord_from_payload(landlord, data):
    landlord.type = data.get('type', landlord.type)
    landlord.first_name = data.get('first_name') or landlord.first_name
    landlord.last_name = data.get('last_name') or landlord.last_name
    landlord.company_name = data.get('company_name') or landlord.company_name
    landlord.legal_form = data.get('legal_form') or landlord.legal_form
    landlord.tax_id = data.get('tax_id') or landlord.tax_id
    landlord.vat_id = data.get('vat_id') or landlord.vat_id
    landlord.street = data.get('street') or landlord.street
    landlord.street_number = data.get('street_number') or landlord.street_number
    landlord.zip_code = data.get('zip_code') or landlord.zip_code
    landlord.city = data.get('city') or landlord.city
    landlord.country = data.get('country') or landlord.country
    landlord.phone = data.get('phone') or landlord.phone
    landlord.email = data.get('email') or landlord.email
    landlord.website = data.get('website') or landlord.website
    landlord.bank_name = data.get('bank_name') or landlord.bank_name
    landlord.iban = data.get('iban') or landlord.iban
    landlord.bic = data.get('bic') or landlord.bic
    landlord.account_holder = data.get('account_holder') or landlord.account_holder
    landlord.representative = data.get('representative') or landlord.representative
    landlord.birth_date = datetime.strptime(data['birth_date'], '%Y-%m-%d').date() if data.get('birth_date') else landlord.birth_date


@contract_editor_bp.route('/api/landlords', methods=['POST'])
@login_required
def create_landlord_api():
    """API: Vermieter anlegen"""
    try:
        current_user = User.query.get(session.get('user_id'))
        if not current_user or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Nur Administratoren dürfen Vermieter anlegen.'}), 403
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        landlord = _create_landlord_from_payload(data)

        db.session.add(landlord)
        db.session.commit()

        return jsonify({
            'success': True,
            'landlord_id': landlord.id,
            'landlord': _landlord_to_dict(landlord),
            'message': 'Vermieter erfolgreich angelegt'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating landlord: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@contract_editor_bp.route('/api/landlords/<landlord_id>', methods=['PUT', 'PATCH'])
@login_required
def update_landlord_api(landlord_id):
    """API: Vermieter aktualisieren"""
    try:
        current_user = User.query.get(session.get('user_id'))
        if not current_user or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Nur Administratoren dürfen Vermieter bearbeiten.'}), 403
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        # Korrekte Modell-Position verwenden (Index 7 in get_contract_models)
        Landlord = get_contract_models()[7]
        landlord = Landlord.query.get_or_404(landlord_id)
        _update_landlord_from_payload(landlord, data)
        landlord.is_active = str(data.get('is_active', 'true')).lower() not in ['false', '0', 'none']
        db.session.commit()
        return jsonify({'success': True, 'landlord': _landlord_to_dict(landlord)})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating landlord: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@contract_editor_bp.route('/api/landlords/<landlord_id>', methods=['DELETE'])
@login_required
def delete_landlord_api(landlord_id):
    try:
        current_user = User.query.get(session.get('user_id'))
        if not current_user or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Nur Administratoren dürfen Vermieter löschen.'}), 403
        Landlord = get_contract_models()[7]
        landlord = Landlord.query.get_or_404(landlord_id)
        landlord.is_active = False
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting landlord: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@contract_editor_bp.route('/api/landlords')
@login_required
def get_landlords_api():
    """API: Alle Vermieter abrufen"""
    try:
        Landlord = get_contract_models()[7]
        landlords = Landlord.query.filter_by(is_active=True).all()
        return jsonify([_landlord_to_dict(landlord) for landlord in landlords])

    except Exception as e:
        current_app.logger.error(f"Error getting landlords: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@landlords_api_bp.route('/', methods=['POST'])
@login_required
def create_landlord_public():
    return create_landlord_api()


@landlords_api_bp.route('/')
@login_required
def list_landlords_public():
    return get_landlords_api()


@landlords_api_bp.route('/<landlord_id>', methods=['PUT', 'PATCH'])
@login_required
def update_landlord_public(landlord_id):
    """Öffentlicher Endpunkt für Vermieter-Updates (identisch zu Editor-API)."""
    return update_landlord_api(landlord_id)


@landlords_api_bp.route('/<landlord_id>', methods=['DELETE'])
@login_required
def delete_landlord_public(landlord_id):
    """Öffentlicher Endpunkt für Vermieter-Archivierung (nur Admins)."""
    return delete_landlord_api(landlord_id)

@contract_editor_bp.route('/<contract_id>/block-editor')
@login_required  
def block_editor(contract_id):
    """Block-Editor für Verträge - SEPARATE URL"""
    Contract, _, Apartment, Tenant, _, _, _, _, ContractBlock, ContractTemplateBlock = get_contract_models()
    
    contract = Contract.query.options(
        db.joinedload(Contract.apartment).joinedload(Apartment.building),
        db.joinedload(Contract.tenant),
        db.joinedload(Contract.blocks)
    ).get_or_404(contract_id)
    
    # Template-Blöcke nach Kategorien gruppieren
    template_blocks = ContractTemplateBlock.query.filter_by(is_active=True)\
        .order_by(ContractTemplateBlock.category, ContractTemplateBlock.sort_order).all()
    
    blocks_by_category = {}
    for block in template_blocks:
        category = block.category or 'allgemein'
        if category not in blocks_by_category:
            blocks_by_category[category] = []
        blocks_by_category[category].append(block)
    
    return render_template('contract_editor/block_editor.html',
                         contract=contract,
                         template_blocks=blocks_by_category)

@contract_editor_bp.route('/<contract_id>/add-template-block', methods=['POST'])
@login_required
def add_template_block(contract_id):
    """Template-Block zum Vertrag hinzufügen"""
    try:
        Contract, _, _, _, _, _, _, _, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        template_block_id = request.json.get('template_block_id')
        template_block = ContractTemplateBlock.query.get_or_404(template_block_id)
        
        # Bestehende Blöcke zählen für Sortierreihenfolge
        existing_blocks_count = ContractBlock.query.filter_by(contract_id=contract_id).count()
        
        # Neuen Block erstellen
        block = ContractBlock(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            block_type=template_block.block_type,
            title=template_block.title,
            content=template_block.content,
            sort_order=existing_blocks_count + 1,
            is_required=template_block.is_required,
            variables=template_block.variables
        )
        
        db.session.add(block)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'block_id': block.id,
            'message': 'Block hinzugefügt'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding template block: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@contract_editor_bp.route('/<contract_id>/blocks', methods=['POST'])
@login_required
def create_block(contract_id):
    """Neuen Block erstellen"""
    try:
        Contract, _, _, _, _, _, _, _, ContractBlock, _ = get_contract_models()
        
        data = request.json
        
        # Bestehende Blöcke zählen für Sortierreihenfolge
        existing_blocks_count = ContractBlock.query.filter_by(contract_id=contract_id).count()
        
        block = ContractBlock(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            block_type=data.get('block_type', 'paragraph'),
            title=data.get('title'),
            content=data.get('content'),
            sort_order=existing_blocks_count + 1,
            is_required=data.get('is_required', False)
        )
        
        db.session.add(block)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'block_id': block.id,
            'message': 'Block erstellt'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating block: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@contract_editor_bp.route('/<contract_id>/blocks/<block_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_block(contract_id, block_id):
    """Block bearbeiten oder löschen"""
    try:
        Contract, _, _, _, _, _, _, _, ContractBlock, _ = get_contract_models()
        
        block = ContractBlock.query.filter_by(id=block_id, contract_id=contract_id).first_or_404()
        
        if request.method == 'PUT':
            data = request.json
            block.title = data.get('title', block.title)
            block.content = data.get('content', block.content)
            block.block_type = data.get('block_type', block.block_type)
            block.is_required = data.get('is_required', block.is_required)
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'Block aktualisiert'})
            
        elif request.method == 'DELETE':
            db.session.delete(block)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Block gelöscht'})
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error managing block: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@contract_editor_bp.route('/<contract_id>/update-block-order', methods=['POST'])
@login_required
def update_block_order(contract_id):
    """Reihenfolge der Blöcke aktualisieren"""
    try:
        Contract, _, _, _, _, _, _, _, ContractBlock, _ = get_contract_models()
        
        block_order = request.json.get('block_order', [])
        
        for item in block_order:
            block = ContractBlock.query.filter_by(id=item['block_id'], contract_id=contract_id).first()
            if block:
                block.sort_order = item['sort_order']
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Reihenfolge aktualisiert'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating block order: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def generate_block_based_contract_html(contract, blocks=None, inventory_items=None):
    """Generiert Vertrags-HTML basierend auf Blöcken"""
    if blocks is None:
        blocks = contract.blocks
    if inventory_items is None:
        inventory_items = getattr(contract, 'inventory_items', [])

    variables = {
        'mieter_vorname': contract.tenant.first_name,
        'mieter_nachname': contract.tenant.last_name,
        'wohnung_adresse': f"{contract.apartment.building.street} {contract.apartment.building.street_number}",
        'miete_netto': f"{contract.rent_net:.2f}",
        'miete_nebenkosten': f"{contract.rent_additional:.2f}",
        'kaution': f"{contract.deposit:.2f}",
        'vertragsbeginn': contract.start_date.strftime('%d.%m.%Y'),
        'vertragsende': contract.end_date.strftime('%d.%m.%Y') if contract.end_date else "unbefristet",
        'datum_heute': datetime.now().strftime('%d.%m.%Y')
    }

    if hasattr(contract, 'landlord') and contract.landlord:
        landlord = contract.landlord
        variables['vermieter_name'] = landlord.company_name or f"{landlord.first_name} {landlord.last_name}"
    else:
        variables['vermieter_name'] = "[Vermieter]"

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
# Ändern Sie diese Route - von clause_management zu edit_contract_content
@contract_editor_bp.route('/<contract_id>/edit-content')
@login_required
def edit_contract_content(contract_id):
    """Vertragsinhalt bearbeiten - JETZT DER KLAUSEL-EDITOR"""
    try:
        models = get_contract_models()
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = models
        
        # Debug-Information
        current_app.logger.info(f"Loading clause editor for contract {contract_id}")
        
        if None in [Contract, ClauseTemplate, ContractClause]:
            flash('Vertrags-Editor Modelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
        
        # Contract mit allen Beziehungen laden
        contract = Contract.query.options(
            db.joinedload(Contract.apartment).joinedload(Apartment.building),
            db.joinedload(Contract.tenant)
        ).get_or_404(contract_id)
        
        # Klausel-Templates laden
        clause_templates = ClauseTemplate.query.filter_by(is_active=True).order_by(ClauseTemplate.sort_order).all() if ClauseTemplate else []
        
        # Standard-Klauseln nach Kategorien gruppieren
        clauses_by_category = {}
        if StandardClauseTemplate:
            try:
                standard_clauses = StandardClauseTemplate.query.filter_by(is_active=True).order_by(StandardClauseTemplate.sort_order).all()
                for clause in standard_clauses:
                    category = clause.category if hasattr(clause, 'category') else 'allgemein'
                    if category not in clauses_by_category:
                        clauses_by_category[category] = []
                    clauses_by_category[category].append(clause)
            except Exception as e:
                current_app.logger.warning(f"Could not load standard clauses: {e}")
                # Fallback: Verwende ClauseTemplate als Standard-Klauseln
                for template in clause_templates:
                    category = template.category if hasattr(template, 'category') else 'allgemein'
                    if category not in clauses_by_category:
                        clauses_by_category[category] = []
                    clauses_by_category[category].append(template)
        
        # Inventory Items laden
        inventory_items = InventoryItem.query.filter_by(contract_id=contract_id).all() if InventoryItem else []
        
        return render_template('contract_editor/edit.html',
                             contract=contract,
                             clause_templates=clause_templates,
                             clauses_by_category=clauses_by_category,
                             inventory_items=inventory_items)
        
    except Exception as e:
        current_app.logger.error(f"Error in edit_contract_content: {str(e)}", exc_info=True)
        flash(f'Fehler beim Laden des Vertrags-Editors: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


@contract_editor_bp.route('/<contract_id>/inventory', methods=['GET', 'POST'])
@login_required
def inventory_management(contract_id):
    """Einfache Inventarverwaltung für Verträge (Fehlerbehebung für fehlende Route)."""
    try:
        Contract, _, _, _, _, _, InventoryItem, _, _, _ = get_contract_models()

        contract = Contract.query.get_or_404(contract_id)

        if request.method == 'POST':
            item = InventoryItem(
                id=str(uuid.uuid4()),
                contract_id=contract_id,
                room=request.form.get('room') or None,
                item_name=request.form.get('item_name'),
                description=request.form.get('description'),
                quantity=int(request.form.get('quantity') or 1),
                condition=request.form.get('condition') or None,
                notes=request.form.get('notes') or None,
            )
            db.session.add(item)
            db.session.commit()
            flash('Inventargegenstand gespeichert.', 'success')
            return redirect(url_for('contract_editor.inventory_management', contract_id=contract_id))

        inventory_items = InventoryItem.query.filter_by(contract_id=contract_id).order_by(InventoryItem.created_at.desc()).all()
        return render_template(
            'contract_editor/inventory.html',
            contract=contract,
            inventory_items=inventory_items,
        )

    except Exception as e:
        current_app.logger.error(f"Error in inventory management: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Fehler beim Laden des Inventars: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


@contract_editor_bp.route('/<contract_id>/add-clause', methods=['POST'])
@login_required
def add_clause_to_contract(contract_id):
    """Klausel zum Vertrag hinzufügen - VERBESSERTE VERSION"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        # ✅ VERBESSERT: Bessere Fehlerbehandlung
        if None in [ContractClause, ClauseTemplate]:
            return jsonify({'success': False, 'error': 'Vertragsmodelle nicht verfügbar'}), 503
        
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'Keine Daten empfangen'}), 400
            
        clause_template_id = data.get('clause_template_id')
        if not clause_template_id:
            return jsonify({'success': False, 'error': 'Klausel-Template-ID fehlt'}), 400
        
        # Prüfe ob Vertrag existiert
        contract = Contract.query.get(contract_id)
        if not contract:
            return jsonify({'success': False, 'error': 'Vertrag nicht gefunden'}), 404
        
        clause_template = ClauseTemplate.query.get(clause_template_id)
        if not clause_template:
            return jsonify({'success': False, 'error': 'Klausel-Vorlage nicht gefunden'}), 404
        
        # Prüfe ob Klausel bereits existiert
        existing_clause = ContractClause.query.filter_by(
            contract_id=contract_id, 
            clause_template_id=clause_template_id
        ).first()
        
        if existing_clause:
            return jsonify({
                'success': False, 
                'error': f'Klausel "{clause_template.title}" ist bereits im Vertrag vorhanden'
            }), 400
        
        # Bestehende Klauseln zählen für Sortierreihenfolge
        existing_clauses_count = ContractClause.query.filter_by(contract_id=contract_id).count()
        
        # Neue Klausel erstellen
        clause = ContractClause(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            clause_template_id=clause_template_id,
            custom_title=clause_template.title,
            custom_content=clause_template.content,
            sort_order=existing_clauses_count
        )
        
        db.session.add(clause)
        db.session.commit()
        
        current_app.logger.info(f"Klausel {clause_template.title} zu Vertrag {contract_id} hinzugefügt")
        
        return jsonify({
            'success': True,
            'message': f'Klausel "{clause_template.title}" hinzugefügt'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding clause to contract {contract_id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    

@contract_editor_bp.route('/<contract_id>/clauses/<clause_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_clause(contract_id, clause_id):
    """Klausel bearbeiten oder löschen"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        clause = ContractClause.query.filter_by(id=clause_id, contract_id=contract_id).first_or_404()
        
        if request.method == 'PUT':
            data = request.json
            clause.custom_title = data.get('custom_title', clause.custom_title)
            clause.custom_content = data.get('custom_content', clause.custom_content)
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'Klausel aktualisiert'})
            
        elif request.method == 'DELETE':
            db.session.delete(clause)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Klausel gelöscht'})
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error managing clause: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@contract_editor_bp.route('/<contract_id>/clause-management')
@login_required
def clause_management(contract_id):
    """Klausel-Verwaltung"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        contract = Contract.query.options(
            db.joinedload(Contract.apartment).joinedload(Apartment.building),
            db.joinedload(Contract.tenant)
        ).get_or_404(contract_id)
        
        # Standard-Klauseln nach Kategorien gruppieren und Paragraphenzeichen bereinigen
        standard_clauses = StandardClauseTemplate.query.filter_by(is_active=True).order_by(StandardClauseTemplate.sort_order).all()
        clauses_by_category = {}
        for clause in standard_clauses:
            cleaned_title = _strip_paragraph_prefix(clause.title)
            if cleaned_title != clause.title:
                clause.title = cleaned_title
                db.session.add(clause)

            if clause.category not in clauses_by_category:
                clauses_by_category[clause.category] = []
            clauses_by_category[clause.category].append(clause)

        db.session.commit()
        
        return render_template('contract_editor/clause_management.html',
                             contract=contract,
                             clauses_by_category=clauses_by_category)
        
    except Exception as e:
        current_app.logger.error(f"Error in clause_management: {str(e)}", exc_info=True)
        flash(f'Fehler beim Laden der Klausel-Verwaltung: {str(e)}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))
    
@contract_editor_bp.route('/init-standard-clauses')
@login_required
def init_standard_clauses():
    """Standard-Klauselvorlagen initialisieren"""
    try:
        from app.models import ClauseTemplate, db
        
        # Überprüfen, ob bereits Klauseln existieren
        existing_count = ClauseTemplate.query.count()
        if existing_count > 0:
            flash(f'Bereits {existing_count} Klauselvorlagen vorhanden', 'info')
            return redirect(url_for('contracts.contracts_list'))
        
        # Standard-Klauseln erstellen (ohne vorangestelltes Paragraphenzeichen im Titel)
        standard_clauses = [
            {
                'name': 'Mietdauer',
                'category': 'mietrecht',
                'title': 'Mietdauer',
                'content': (
                    "Der Mietvertrag beginnt am §vertragsbeginn§ und endet am §vertragsende§. "
                    "Ist kein Enddatum vereinbart, gilt der Vertrag als unbefristet. Eine ordentliche Kündigung "
                    "ist erstmals nach Ablauf der gesetzlichen Fristen möglich. Verlängerungen oder Verlängerungsoptionen "
                    "bedürfen der Schriftform."
                ),
                'is_mandatory': True
            },
            {
                'name': 'Kündigungsfrist',
                'category': 'mietrecht',
                'title': 'Kündigung',
                'content': (
                    "Die Kündigung des Mietverhältnisses bedarf der Schriftform. Für den Vermieter gelten die gesetzlichen "
                    "Kündigungsfristen gemäß § 573c BGB. Der Mieter kann mit der gesetzlichen Frist kündigen; bei unbefristeten "
                    "Verträgen beträgt diese drei Monate. Das Recht zur fristlosen Kündigung aus wichtigem Grund bleibt unberührt."
                ),
                'is_mandatory': True
            },
            {
                'name': 'Nebenkosten',
                'category': 'kosten',
                'title': 'Betriebskosten',
                'content': (
                    "Der Mieter leistet monatliche Vorauszahlungen auf die umlagefähigen Betriebskosten in Höhe von §miete_nebenkosten§ €. "
                    "Die Abrechnung erfolgt jährlich nach den Vorgaben der Betriebskostenverordnung. Nachzahlungen oder Guthaben werden "
                    "innerhalb von 30 Tagen nach Zugang der Abrechnung ausgeglichen."
                ),
                'is_mandatory': False
            },
            {
                'name': 'Haustiere',
                'category': 'nutzung',
                'title': 'Haustiere',
                'content': (
                    "Die Haltung üblicher Kleintiere (z. B. Zierfische, Hamster) ist erlaubt. Die Haltung größerer Haustiere, "
                    "insbesondere von Hunden oder Katzen, bedarf der vorherigen schriftlichen Zustimmung des Vermieters. "
                    "Die Zustimmung kann widerrufen werden, wenn berechtigte Interessen des Vermieters oder anderer Hausbewohner "
                    "beeinträchtigt werden."
                ),
                'is_mandatory': False
            }
        ]
        
        for clause_data in standard_clauses:
            clause = ClauseTemplate(
                id=str(uuid.uuid4()),
                name=clause_data['name'],
                category=clause_data['category'],
                title=clause_data['title'],
                content=clause_data['content'],
                is_mandatory=clause_data['is_mandatory'],
                is_active=True
            )
            db.session.add(clause)
        
        db.session.commit()
        flash('Standard-Klauselvorlagen erfolgreich initialisiert!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error initializing standard clauses: {str(e)}", exc_info=True)
        flash(f'Fehler beim Initialisieren der Standard-Klauseln: {str(e)}', 'danger')
    
    return redirect(url_for('contracts.contracts_list'))

@contract_editor_bp.route('/debug/models')
@login_required
def debug_models():
    """Debug-Informationen für Modelle"""
    models = get_contract_models()
    model_names = [
        'Contract', 'ClauseTemplate', 'ContractClause', 'Apartment', 'Tenant',
        'StandardClauseTemplate', 'InventoryItem', 'Landlord', 'ContractBlock', 'ContractTemplateBlock'
    ]
    
    status = {}
    for i, name in enumerate(model_names):
        status[name] = {
            'available': models[i] is not None,
            'class': str(models[i]) if models[i] else None
        }
    
    # Versuche, Modelle direkt zu importieren
    try:
        from app.models import ClauseTemplate
        clause_count = ClauseTemplate.query.count()
        status['ClauseTemplate']['count'] = clause_count
    except Exception as e:
        status['ClauseTemplate']['error'] = str(e)
    
    return jsonify({
        "models_status": status,
        "all_models_available": all(m is not None for m in models),
        "timestamp": datetime.now().isoformat()
    })

# NEUE ROUTEN FÜR DIE KLAUSELVERWALTUNG - MIT EINDEUTIGEN NAMEN

@contract_editor_bp.route('/<contract_id>/check-duplicate-clauses', methods=['POST'])
@login_required
def check_duplicate_clauses_handler(contract_id):
    """Prüft auf doppelte Klauseln"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        data = request.json
        clause_template_ids = data.get('clause_template_ids', [])
        
        # Prüfe welche Klauseln bereits existieren
        existing_clauses = ContractClause.query.filter(
            ContractClause.contract_id == contract_id,
            ContractClause.clause_template_id.in_(clause_template_ids)
        ).all()
        
        duplicates = []
        for clause in existing_clauses:
            # Finde den Template-Namen
            template = ClauseTemplate.query.get(clause.clause_template_id)
            if template:
                duplicates.append({
                    'id': clause.clause_template_id,
                    'name': template.title or template.name
                })
        
        return jsonify({
            'duplicates': duplicates
        })
        
    except Exception as e:
        current_app.logger.error(f"Error checking duplicate clauses: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@contract_editor_bp.route('/<contract_id>/create-custom-clause', methods=['POST'])
@login_required
def create_custom_clause_handler(contract_id):
    """Erstellt eine benutzerdefinierte Klausel - KORRIGIERTE VERSION"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        data = request.json
        title = data.get('title')
        content = data.get('content')
        
        if not title or not content:
            return jsonify({'success': False, 'error': 'Titel und Inhalt sind erforderlich'}), 400
        
        # Bestehende Klauseln zählen für Sortierreihenfolge
        existing_clauses_count = ContractClause.query.filter_by(contract_id=contract_id).count()
        
        # Neue benutzerdefinierte Klausel erstellen
        clause = ContractClause(
            id=str(uuid.uuid4()),
            contract_id=contract_id,
            clause_template_id=None,  # Keine Template-ID für benutzerdefinierte Klauseln
            custom_title=title,
            custom_content=content,
            sort_order=existing_clauses_count
        )
        
        db.session.add(clause)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Benutzerdefinierte Klausel erstellt'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating custom clause: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    
@contract_editor_bp.route('/<contract_id>/update-clause-order', methods=['POST'])
@login_required
def update_clause_order_handler(contract_id):
    """Aktualisiert die Reihenfolge der Klauseln"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        data = request.json
        clause_order = data.get('clause_order', [])
        
        for item in clause_order:
            clause = ContractClause.query.filter_by(id=item['clause_id'], contract_id=contract_id).first()
            if clause:
                clause.sort_order = item['sort_order']
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Reihenfolge aktualisiert'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating clause order: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

# DEBUG ROUTE FÜR ENDPOINTS
@contract_editor_bp.route('/debug/endpoints')
def debug_endpoints():
    """Zeigt alle registrierten Endpunkte"""
    from flask import current_app
    endpoints = []
    for rule in current_app.url_map.iter_rules():
        if 'contract_editor' in rule.endpoint:
            endpoints.append({
                'endpoint': rule.endpoint,
                'methods': list(rule.methods),
                'path': rule.rule
            })
    return jsonify(sorted(endpoints, key=lambda x: x['endpoint']))

@contract_editor_bp.route('/<contract_id>/create-test-clauses')
@login_required
def create_test_clauses(contract_id):
    """Erstellt zwei Test-Klauseln für Sortier-Tests"""
    try:
        Contract, ClauseTemplate, ContractClause, Apartment, Tenant, StandardClauseTemplate, InventoryItem, Landlord, ContractBlock, ContractTemplateBlock = get_contract_models()
        
        # Prüfe ob bereits Test-Klauseln existieren
        existing_test_clauses = ContractClause.query.filter(
            ContractClause.contract_id == contract_id,
            ContractClause.custom_title.like('Test-Klausel%')
        ).count()
        
        if existing_test_clauses >= 2:
            return jsonify({
                'success': True,
                'message': 'Test-Klauseln existieren bereits',
                'count': existing_test_clauses
            })
        
        # Erstelle zwei Test-Klauseln
        test_clauses = [
            {
                'title': 'Test-Klausel A - Mietdauer',
                'content': 'Dies ist Test-Klausel A für die Mietdauer. Der Vertrag beginnt am §vertragsbeginn§.'
            },
            {
                'title': 'Test-Klausel B - Nebenkosten', 
                'content': 'Dies ist Test-Klausel B für Nebenkosten. Die Vorauszahlung beträgt §miete_nebenkosten§ €.'
            }
        ]
        
        for i, clause_data in enumerate(test_clauses):
            clause = ContractClause(
                id=str(uuid.uuid4()),
                contract_id=contract_id,
                clause_template_id=None,
                custom_title=clause_data['title'],
                custom_content=clause_data['content'],
                sort_order=i
            )
            db.session.add(clause)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(test_clauses)} Test-Klauseln erstellt',
            'clauses_created': len(test_clauses)
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating test clauses: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    

@contract_editor_bp.route('/<contract_id>/tree-editor')
@login_required
def tree_editor(contract_id):
    """
    Kombinierter Tree-Editor:
    - links: Klausel-Templates (clause_templates)
    - mitte: Paragraphen/Unterparagraphen-Struktur
    - rechts: Live-Vorschau
    """
    try:
        # Modelle holen
        (Contract, ClauseTemplate, ContractClause, Apartment, Tenant,
         StandardClauseTemplate, InventoryItem, Landlord,
         ContractBlock, ContractTemplateBlock) = get_contract_models()

        if Contract is None:
            flash('Vertragsmodelle sind noch nicht verfügbar', 'warning')
            return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

        # Vertrag laden
        contract = Contract.query.options(
            db.joinedload(Contract.apartment).joinedload(Apartment.building),
            db.joinedload(Contract.tenant),
            db.joinedload(Contract.clauses) if hasattr(Contract, 'clauses') else db.lazyload('*')
        ).get_or_404(contract_id)

        # Klausel-Templates (Standardklauseln) laden & nach Kategorien gruppieren
        clauses_by_category = {}
        template_subclauses = {}
        if ClauseTemplate:
            templates = ClauseTemplate.query.filter_by(is_active=True).order_by(ClauseTemplate.sort_order).all()
            for tpl in templates:
                category = tpl.category or 'allgemein'
                if category not in clauses_by_category:
                    clauses_by_category[category] = []
                clauses_by_category[category].append(tpl)
                try:
                    if tpl.variables:
                        template_subclauses[tpl.id] = json.loads(tpl.variables).get('subclauses', [])
                    else:
                        template_subclauses[tpl.id] = []
                except Exception:
                    template_subclauses[tpl.id] = []

        # Paragraphen-Baum aus JSON laden oder mit Standardwerten vorbelegen
        initial_tree = load_contract_tree(contract)
        if not initial_tree:
            initial_tree = _build_default_paragraph_tree(contract)
            save_contract_tree(contract, initial_tree)
            db.session.commit()

        return render_template(
            'contract_editor/tree_editor.html',
            contract=contract,
            clauses_by_category=clauses_by_category,
            initial_tree=initial_tree,
            template_subclauses=template_subclauses
        )
    except Exception as e:
        current_app.logger.error(f"Error loading tree_editor for contract {contract_id}: {e}", exc_info=True)
        flash(f'Fehler beim Laden des Tree-Editors: {e}', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

@contract_editor_bp.route('/<contract_id>/save-structure', methods=['POST'])
@login_required
def save_contract_structure(contract_id):
    """
    Speichert die Paragraphen-/Unterparagraphen-Struktur als JSON in contracts.contract_data
    Erwarteter Body: { "tree": [ ... ] }
    """
    try:
        (Contract, ClauseTemplate, ContractClause, Apartment, Tenant,
         StandardClauseTemplate, InventoryItem, Landlord,
         ContractBlock, ContractTemplateBlock) = get_contract_models()

        if Contract is None:
            return jsonify({'success': False, 'error': 'Contract model not available'}), 503

        contract = Contract.query.get_or_404(contract_id)

        data = request.get_json(silent=True) or {}
        tree = data.get('tree', [])

        if not isinstance(tree, list):
            return jsonify({'success': False, 'error': 'Invalid tree format'}), 400

        # JSON in contract_data mitschreiben
        save_contract_tree(contract, tree)
        contract.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({'success': True, 'message': 'Struktur gespeichert'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving contract structure for {contract_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
