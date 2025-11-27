from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, send_file, session
from flask_jwt_extended import jwt_required
from app.extensions import db
from app.models import Document, Apartment, Tenant, Contract, Building
from sqlalchemy import or_
from datetime import datetime
from app.routes.main import login_required
import os
from werkzeug.utils import secure_filename

documents_bp = Blueprint('documents', __name__)

# Konfiguration für Datei-Uploads
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'txt'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@documents_bp.route('/documents')
@login_required
def documents_list():
    apartment_id = request.args.get('apartment_id')
    search_term = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    query = Document.query.order_by(Document.created_at.desc())
    if apartment_id:
        query = query.filter(Document.documentable_type == 'apartment', Document.documentable_id == apartment_id)
    if category:
        query = query.filter(Document.document_type == category)
    if search_term:
        like = f"%{search_term}%"
        query = query.filter(or_(Document.file_name.ilike(like), Document.description.ilike(like)))

    documents = query.all()

    # Zielobjekte in einem Rutsch auflösen
    apartment_ids = {doc.documentable_id for doc in documents if doc.documentable_type == 'apartment' and doc.documentable_id}
    tenant_ids = {doc.documentable_id for doc in documents if doc.documentable_type == 'tenant' and doc.documentable_id}
    contract_ids = {doc.documentable_id for doc in documents if doc.documentable_type == 'contract' and doc.documentable_id}
    building_ids = {doc.documentable_id for doc in documents if doc.documentable_type == 'building' and doc.documentable_id}

    apartments_lookup = {a.id: a for a in Apartment.query.filter(Apartment.id.in_(apartment_ids)).all()} if apartment_ids else {}
    tenants_lookup = {t.id: t for t in Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()} if tenant_ids else {}
    contracts_lookup = {c.id: c for c in Contract.query.filter(Contract.id.in_(contract_ids)).all()} if contract_ids else {}
    buildings_lookup = {b.id: b for b in Building.query.filter(Building.id.in_(building_ids)).all()} if building_ids else {}

    for doc in documents:
        target_label = '–'
        if doc.documentable_type == 'apartment' and doc.documentable_id in apartments_lookup:
            target_label = f"Wohnung: {apartments_lookup[doc.documentable_id].get_full_identifier()}"
        elif doc.documentable_type == 'tenant' and doc.documentable_id in tenants_lookup:
            tenant = tenants_lookup[doc.documentable_id]
            target_label = f"Mieter: {tenant.first_name} {tenant.last_name}"
        elif doc.documentable_type == 'contract' and doc.documentable_id in contracts_lookup:
            contract = contracts_lookup[doc.documentable_id]
            target_label = f"Vertrag: {contract.contract_number}"
        elif doc.documentable_type == 'building' and doc.documentable_id in buildings_lookup:
            target_label = f"Gebäude: {buildings_lookup[doc.documentable_id].name}"
        doc.target_label = target_label
        doc.search_blob = f"{doc.file_name} {doc.description or ''} {doc.document_type or ''} {target_label}"

    apartments = Apartment.query.options(db.joinedload(Apartment.building)).all()
    return render_template('documents/list.html', documents=documents, apartments=apartments)

@documents_bp.route('/documents/upload', methods=['GET', 'POST'])
@login_required
def upload_document():
    apartments = Apartment.query.all()
    tenants = Tenant.query.all()
    
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('Keine Datei ausgewählt', 'danger')
                return redirect(request.url)
            
            file = request.files['file']
            if file.filename == '':
                flash('Keine Datei ausgewählt', 'danger')
                return redirect(request.url)
            
            if file and allowed_file(file.filename):
                # Dateigröße prüfen
                file.seek(0, 2)  # Zum Ende der Datei springen
                file_size = file.tell()
                file.seek(0)  # Zurück zum Anfang
                
                if file_size > MAX_FILE_SIZE:
                    flash('Datei ist zu groß (max. 16MB)', 'danger')
                    return redirect(request.url)
                
                # Datei speichern
                original_name = secure_filename(file.filename)
                unique_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{original_name}"
                base_dir = os.path.join('uploads', 'documents')
                os.makedirs(base_dir, exist_ok=True)
                file_path = os.path.join(base_dir, unique_filename)
                file.save(file_path)

                # Dokument in Datenbank speichern
                document = Document(
                    file_name=original_name,
                    file_path=file_path,
                    file_size=file_size,
                    mime_type=file.content_type,
                    description=request.form.get('description'),
                    document_type=request.form.get('category') or 'other',
                    documentable_type=request.form.get('documentable_type') or ('apartment' if request.form.get('apartment_id') else ('tenant' if request.form.get('tenant_id') else None)),
                    documentable_id=request.form.get('apartment_id') or request.form.get('tenant_id') or None,
                    uploaded_by=session.get('user_id')
                )

                db.session.add(document)
                db.session.commit()
                flash('Dokument erfolgreich hochgeladen!', 'success')
                return redirect(url_for('documents.documents_list'))
            else:
                flash('Ungültiger Dateityp', 'danger')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Hochladen: {str(e)}', 'danger')
    
    return render_template('documents/upload.html', 
                         apartments=apartments, 
                         tenants=tenants)

@documents_bp.route('/documents/<int:document_id>/download')
@login_required
def download_document(document_id):
    document = Document.query.get_or_404(document_id)
    file_path = document.file_path

    if not os.path.exists(file_path):
        flash('Datei nicht gefunden', 'danger')
        return redirect(url_for('documents.documents_list'))

    inline = request.args.get('preview') == '1'
    return send_file(
        file_path,
        as_attachment=not inline,
        download_name=document.file_name or os.path.basename(file_path)
    )

@documents_bp.route('/documents/<int:document_id>/delete', methods=['POST'])
@login_required
def delete_document(document_id):
    document = Document.query.get_or_404(document_id)
    
    try:
        # Datei löschen
        file_path = document.file_path
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        
        # Datenbank-Eintrag löschen
        db.session.delete(document)
        db.session.commit()
        flash('Dokument erfolgreich gelöscht!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen: {str(e)}', 'danger')
    
    return redirect(url_for('documents.documents_list'))

# API Routes
@documents_bp.route('/documents', methods=['GET'])
@jwt_required()
def get_documents_api():
    documents = Document.query.all()
    return jsonify([{
        'id': doc.id,
        'file_name': doc.file_name,
        'file_type': doc.mime_type,
        'file_size': doc.file_size,
        'category': doc.document_type,
        'description': doc.description,
        'created_at': doc.created_at.isoformat(),
        'documentable_type': doc.documentable_type,
        'documentable_id': doc.documentable_id
    } for doc in documents])

@documents_bp.route('/documents/upload', methods=['POST'])
@jwt_required()
def upload_document_api():
    # API Upload ähnlich wie Web-Upload, aber mit JSON Response
    pass

@documents_bp.route('/documents/<int:document_id>', methods=['GET'])
@jwt_required()
def download_document_api(document_id):
    document = Document.query.get_or_404(document_id)
    file_path = document.file_path

    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=document.file_name or os.path.basename(file_path)
    )