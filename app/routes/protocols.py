from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, send_from_directory, send_file
from app.routes.main import login_required
from app.extensions import db
from app.models import Protocol, Contract, ProtocolRevision, Meter, MeterReading
import uuid
import json
from datetime import datetime
import re
import os
import mimetypes
from types import SimpleNamespace
from io import BytesIO
import base64
import pandas as pd
from PIL import Image, ImageOps
from app.utils.pdf_generator import generate_pdf_bytes, save_protocol_pdf
from app.utils.schema_helpers import ensure_archiving_columns

protocols_bp = Blueprint('protocols', __name__)


def _normalize_attachments(raw_attachments):
    """Ensure attachments have a uniform dict structure."""
    normalized = []
    if not isinstance(raw_attachments, list):
        return normalized

    for item in raw_attachments:
        if isinstance(item, dict):
            file_name = item.get('file') or item.get('file_name') or item.get('path') or item.get('filename')
            caption = item.get('caption') or item.get('title') or ''
            mime = item.get('mime') or mimetypes.guess_type(file_name or '')[0]
        elif isinstance(item, str):
            file_name = item
            caption = ''
            mime = mimetypes.guess_type(file_name or '')[0]
        else:
            continue

        if not file_name:
            continue

        normalized.append({
            'file': file_name,
            'caption': caption,
            'mime': mime
        })

    return normalized


def _build_attachment_views(raw_attachments):
    base_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'protocols')
    normalized = _normalize_attachments(raw_attachments)
    for item in normalized:
        ext = (os.path.splitext(item.get('file') or '')[1] or '').lower()
        mime = (item.get('mime') or '').lower()
        absolute_path = os.path.abspath(os.path.join(base_dir, item['file'])) if item.get('file') else ''
        item['local_path'] = f"file://{absolute_path}" if absolute_path else ''
        item['is_image'] = mime.startswith('image') or ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']
        if item['is_image'] and absolute_path and os.path.exists(absolute_path):
            try:
                with open(absolute_path, 'rb') as fh:
                    encoded = base64.b64encode(fh.read()).decode('utf-8')
                item['image_data_uri'] = f"data:{mime or 'image/png'};base64,{encoded}"
            except Exception:
                item['image_data_uri'] = ''
        else:
            item['image_data_uri'] = ''
    return normalized


def _save_protocol_file(file, upload_dir: str, prefix: str) -> str:
    """Speichert eine Datei unterhalb des Protokoll-Ordners und skaliert Bilder."""
    ext = os.path.splitext(file.filename or '')[1]
    stored_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    target_path = os.path.join(upload_dir, stored_name)

    try:
        mime = (file.mimetype or '').lower()
        if mime.startswith('image/'):
            file.stream.seek(0)
            with Image.open(file.stream) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((1800, 1800), Image.LANCZOS)
                format_hint = (img.format or '').upper()
                save_kwargs = {}

                if (format_hint == 'JPEG') or ext.lower() in ['.jpg', '.jpeg']:
                    format_hint = 'JPEG'
                    save_kwargs.update({'quality': 90, 'optimize': True})
                elif (format_hint == 'PNG') or ext.lower() == '.png':
                    format_hint = 'PNG'
                else:
                    format_hint = 'PNG'

                img.save(target_path, format=format_hint, **save_kwargs)
        else:
            file.save(target_path)
    except Exception:
        file.save(target_path)

    return stored_name


def _is_protocol_finalized(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get('is_finalized'))

@protocols_bp.route('/')
@login_required
def protocols_list():
    """Liste aller Protokolle"""
    ensure_archiving_columns()
    protocols = Protocol.query.filter((Protocol.is_archived.is_(False)) | (Protocol.is_archived.is_(None))).order_by(Protocol.protocol_date.desc()).all()
    return render_template('protocols/list.html', protocols=protocols)


@protocols_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_protocol():
    """Neues Übergabe- oder Rücknahmeprotokoll erfassen."""
    ensure_archiving_columns()
    contract_id = request.args.get('contract_id') or request.form.get('contract_id')
    contract = Contract.query.get(contract_id) if contract_id else None
    requested_type = request.args.get('protocol_type')

    if not contract:
        flash('Bitte wählen Sie zuerst einen Vertrag aus, um ein Protokoll zu erstellen.', 'danger')
        return redirect(url_for('contracts.contracts_list'))

    if not contract.apartment:
        flash('Dem Vertrag ist keine Wohnung zugeordnet.', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract_id))

    meters = Meter.query.filter(
        (Meter.apartment_id == contract.apartment_id) | (
            (Meter.apartment_id.is_(None)) & (Meter.building_id == contract.apartment.building_id)
        )
    ).options(db.joinedload(Meter.meter_type)).all()

    # Ermittle letzte Zählerstände für Anzeige
    for meter in meters:
        last_reading = (
            MeterReading.query.filter_by(meter_id=meter.id)
            .order_by(MeterReading.reading_date.desc())
            .first()
        )
        meter.latest_reading_value = last_reading.reading_value if last_reading else None

    # Neuerfassung beginnt immer mit leerem Payload
    existing_payload = {}

    if request.method == 'POST':
        try:
            protocol_type = request.form.get('protocol_type', 'uebernahme')

            try:
                protocol_date_raw = request.form.get('protocol_date')
                protocol_date = datetime.strptime(protocol_date_raw, '%Y-%m-%d').date()
            except Exception:
                raise ValueError('Ungültiges Protokolldatum')

            raw_keys = json.loads(request.form.get('keys_json') or '[]')
            key_entries = []
            for entry in raw_keys:
                # Überspringe leere Einträge aus dem Modal
                if not any(entry.get(field) for field in ['title', 'description', 'location']):
                    continue

                quantity = entry.get('quantity')
                try:
                    quantity = max(int(quantity), 1)
                except (ValueError, TypeError):
                    digits = re.findall(r"\d+", str(quantity) if quantity is not None else '')
                    quantity = max(int(digits[0]), 1) if digits else 1

                key_entries.append({
                    'title': entry.get('title'),
                    'description': entry.get('description'),
                    'location': entry.get('location'),
                    'quantity': quantity
                })

            raw_inventory = json.loads(request.form.get('inventory_json') or '[]')
            inventory_entries = []
            for entry in raw_inventory:
                if not any(entry.get(field) for field in ['name', 'item_name', 'location', 'condition', 'notes']):
                    continue
                try:
                    qty = max(int(entry.get('quantity') or 1), 1)
                except Exception:
                    qty = 1
                inventory_entries.append({
                    'name': entry.get('name') or entry.get('item_name'),
                    'location': entry.get('location'),
                    'condition': entry.get('condition'),
                    'quantity': qty,
                    'damages': entry.get('damages'),
                    'notes': entry.get('notes')
                })

            meter_entries = []
            meter_photo_map = {}
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'protocols')
            os.makedirs(upload_dir, exist_ok=True)

            uploaded_files = request.files.getlist('protocol_upload')
            attachment_captions = request.form.getlist('attachment_captions[]') or []
            attachment_meta = []

            for meter in meters:
                raw_value = request.form.get(f'meter_readings[{meter.id}]')
                value = None
                if raw_value:
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        current_app.logger.warning(
                            "Ungültiger Zählerstand für %s: %s", meter.id, raw_value
                        )
                        value = None
                photo = request.files.get(f'meter_photo_{meter.id}')
                photo_name = None

                if photo and photo.filename:
                    photo_name = _save_protocol_file(photo, upload_dir, prefix=f"meter_{meter.id}")
                    meter_photo_map[str(meter.id)] = photo_name

                meter_entries.append({
                    'id': meter.id,
                    'number': meter.meter_number,
                    'type': meter.meter_type.name if meter.meter_type else 'Zähler',
                    'unit': meter.meter_type.unit if meter.meter_type else '',
                    'location': meter.location_description or '',
                    'reading_value': value,
                    'photo': photo_name
                })

                if value is not None:
                    reading = MeterReading(
                        id=str(uuid.uuid4()),
                        meter_id=meter.id,
                        reading_value=value,
                        reading_date=protocol_date,
                        photo_path=photo_name,
                        notes=f'Protokoll {protocol_type}',
                        created_by=session.get('user_id'),
                        is_manual_entry=True
                    )
                    db.session.add(reading)

            # Protokollanhänge speichern
            for idx, file in enumerate(uploaded_files):
                if file and file.filename:
                    stored_name = _save_protocol_file(file, upload_dir, prefix='protocol')
                    caption = attachment_captions[idx] if idx < len(attachment_captions) else ''
                    attachment_meta.append({
                        'file': stored_name,
                        'caption': caption,
                        'mime': file.mimetype
                    })

            try:
                computed_key_count = sum(
                    (int(key.get('quantity')) if isinstance(key.get('quantity'), int) else int(re.findall(r"\d+", str(key.get('quantity') or '1'))[0]))
                    if re.findall(r"\d+", str(key.get('quantity') or '1')) else 1
                    for key in key_entries
                )
            except Exception:
                computed_key_count = len(key_entries)

            protocol_data = {
                'condition_summary': request.form.get('condition_summary'),
                'meter_notes': request.form.get('meter_notes'),
                'damages': request.form.get('damages'),
                'key_count': computed_key_count,
                'notes': request.form.get('notes'),
                'keys': key_entries,
                'inventory': inventory_entries,
                'meter_entries': meter_entries,
                'meter_photos': meter_photo_map,
                'attachments': attachment_meta,
                'room_notes': request.form.get('room_notes'),
                'handover_notes': request.form.get('handover_notes'),
                'follow_up_notes': request.form.get('follow_up_notes'),
                'return_notes': request.form.get('return_notes')
            }

            protocol_data['is_finalized'] = existing_payload.get('is_finalized') if isinstance(existing_payload, dict) else False

            protocol_data.setdefault('is_finalized', False)

            attachment_entries = _build_attachment_views(attachment_meta)

            protocol = Protocol(
                id=str(uuid.uuid4()),
                contract_id=contract_id,
                protocol_type=protocol_type,
                protocol_date=protocol_date,
                protocol_data=json.dumps(protocol_data, ensure_ascii=False),
                created_by=session.get('user_id')
            )

            if attachment_meta:
                # erstes PDF oder Bild als pdf_path, damit abrufbar
                protocol.pdf_path = attachment_meta[0].get('file')

            protocol.final_content = render_template(
                'protocols/protocol_document.html',
                protocol=protocol,
                contract=contract,
                protocol_data=protocol_data,
                meter_entries=meter_entries,
                keys=key_entries,
                inventory_entries=inventory_entries,
                attachment_entries=attachment_entries
            )

            db.session.add(protocol)

            if ProtocolRevision:
                revision = ProtocolRevision(
                    id=str(uuid.uuid4()),
                    protocol_id=protocol.id,
                    revision_number=1,
                    changed_by=session.get('user_id'),
                    change_description='Protokoll erstellt',
                    new_data=protocol.protocol_data
                )
                db.session.add(revision)

            db.session.commit()
            flash('Protokoll erfolgreich gespeichert.', 'success')
            return redirect(url_for('protocols.protocol_detail', protocol_id=protocol.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating protocol: {e}", exc_info=True)
            flash(f'Protokoll konnte nicht gespeichert werden: {e}', 'danger')

    prefill_payload = None
    if request.method == 'GET':
        if (requested_type or 'uebernahme') == 'ruecknahme':
            reference_protocol = (
                Protocol.query
                .filter_by(contract_id=contract_id, protocol_type='uebernahme')
                .order_by(Protocol.protocol_date.desc())
                .first()
            )
            try:
                reference_data = json.loads(reference_protocol.protocol_data) if reference_protocol and reference_protocol.protocol_data else {}
            except Exception:
                reference_data = {}

            if reference_data:
                if not reference_data.get('key_count') and isinstance(reference_data.get('keys'), list):
                    try:
                        reference_data['key_count'] = sum((int(item.get('quantity') or 1) for item in reference_data.get('keys', [])))
                    except Exception:
                        reference_data['key_count'] = len(reference_data.get('keys', []))
                prefill_payload = SimpleNamespace(**reference_data)

    return render_template('protocols/create.html',
                         contract=contract,
                         contract_id=contract_id,
                         meters=meters,
                         protocol=None,
                         protocol_payload=prefill_payload)


@protocols_bp.route('/<protocol_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_protocol(protocol_id):
    ensure_archiving_columns()
    protocol = Protocol.query.get_or_404(protocol_id)
    contract = Contract.query.get(protocol.contract_id)
    if not contract:
        flash('Vertrag nicht gefunden.', 'danger')
        return redirect(url_for('protocols.protocols_list'))

    if not getattr(contract, 'apartment', None):
        flash('Dem Vertrag ist keine Wohnung zugeordnet. Bitte weisen Sie zuerst eine Wohnung zu, bevor das Protokoll bearbeitet wird.', 'danger')
        return redirect(url_for('contracts.contract_detail', contract_id=contract.id))

    building_id = contract.apartment.building_id if getattr(contract, 'apartment', None) else None
    meters = []
    if contract and contract.apartment_id:
        meters = Meter.query.filter(
            (Meter.apartment_id == contract.apartment_id) | (
                (Meter.apartment_id.is_(None)) & (Meter.building_id == building_id)
            )
        ).options(db.joinedload(Meter.meter_type)).all()

    try:
        existing_payload = json.loads(protocol.protocol_data) if protocol.protocol_data else {}
    except Exception:
        existing_payload = {}

    if _is_protocol_finalized(existing_payload):
        flash('Der Vorgang ist abgeschlossen und kann nicht mehr bearbeitet werden.', 'warning')
        return redirect(url_for('protocols.protocol_detail', protocol_id=protocol.id))

    if request.method == 'POST':
        try:
            protocol_type = request.form.get('protocol_type', protocol.protocol_type)
            protocol_date_raw = request.form.get('protocol_date')
            protocol_date = datetime.strptime(protocol_date_raw, '%Y-%m-%d').date() if protocol_date_raw else protocol.protocol_date

            raw_keys = json.loads(request.form.get('keys_json') or '[]')
            key_entries = [entry for entry in raw_keys if any(entry.get(field) for field in ['title', 'description', 'location'])]

            raw_inventory = json.loads(request.form.get('inventory_json') or '[]')
            inventory_entries = [
                {
                    'name': entry.get('name') or entry.get('item_name'),
                    'location': entry.get('location'),
                    'condition': entry.get('condition'),
                    'quantity': entry.get('quantity') or 1,
                    'damages': entry.get('damages'),
                    'notes': entry.get('notes')
                }
                for entry in raw_inventory if any(entry.get(field) for field in ['name', 'item_name', 'location', 'notes', 'damages'])
            ]

            meter_entries = []
            meter_photo_map = existing_payload.get('meter_photos', {}) if isinstance(existing_payload, dict) else {}
            if not isinstance(meter_photo_map, dict):
                meter_photo_map = {}
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'protocols')
            os.makedirs(upload_dir, exist_ok=True)

            for meter in meters:
                raw_value = request.form.get(f'meter_readings[{meter.id}]')
                value = None
                if raw_value:
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        value = None
                photo = request.files.get(f'meter_photo_{meter.id}')
                photo_name = meter_photo_map.get(str(meter.id)) if isinstance(meter_photo_map, dict) else None
                if photo and photo.filename:
                    photo_name = _save_protocol_file(photo, upload_dir, prefix=f"meter_{meter.id}")
                    meter_photo_map[str(meter.id)] = photo_name

                meter_entries.append({
                    'id': meter.id,
                    'number': meter.meter_number,
                    'type': meter.meter_type.name if meter.meter_type else 'Zähler',
                    'unit': meter.meter_type.unit if meter.meter_type else '',
                    'location': meter.location_description or '',
                    'reading_value': value,
                    'photo': photo_name
                })

                if value is not None:
                    reading = MeterReading(
                        id=str(uuid.uuid4()),
                        meter_id=meter.id,
                        reading_value=value,
                        reading_date=protocol_date,
                        photo_path=photo_name,
                        notes=f'Protokoll {protocol_type} (bearbeitet)',
                        created_by=session.get('user_id'),
                        is_manual_entry=True
                    )
                    db.session.add(reading)

            uploaded_files = request.files.getlist('protocol_upload')
            attachment_captions = request.form.getlist('attachment_captions[]') or []
            attachment_paths = _normalize_attachments(existing_payload.get('attachments', [])) if isinstance(existing_payload, dict) else []

            remove_targets = {item for item in request.form.getlist('remove_attachments[]') if item}
            if remove_targets:
                base_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'protocols')
                remaining_paths = []
                for att in attachment_paths:
                    fname = att.get('file') if isinstance(att, dict) else att
                    if fname in remove_targets:
                        try:
                            file_path = os.path.join(base_dir, fname)
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except Exception:
                            current_app.logger.warning('Konnte Anlage %s nicht entfernen', fname)
                        continue
                    remaining_paths.append(att)
                attachment_paths = remaining_paths
            for idx, file in enumerate(uploaded_files):
                if file and file.filename:
                    stored_name = _save_protocol_file(file, upload_dir, prefix='protocol')
                    caption = attachment_captions[idx] if idx < len(attachment_captions) else ''
                    attachment_paths.append({
                        'file': stored_name,
                        'caption': caption,
                        'mime': file.mimetype
                    })

            try:
                computed_key_count = sum((int(item.get('quantity') or 1) for item in key_entries))
            except Exception:
                computed_key_count = len(key_entries)

            protocol_data = {
                'condition_summary': request.form.get('condition_summary'),
                'meter_notes': request.form.get('meter_notes'),
                'damages': request.form.get('damages'),
                'key_count': computed_key_count,
                'notes': request.form.get('notes'),
                'keys': key_entries,
                'inventory': inventory_entries,
                'meter_entries': meter_entries,
                'meter_photos': meter_photo_map,
                'attachments': attachment_paths,
                'room_notes': request.form.get('room_notes'),
                'handover_notes': request.form.get('handover_notes'),
                'follow_up_notes': request.form.get('follow_up_notes'),
                'return_notes': request.form.get('return_notes')
            }

            attachment_entries = _build_attachment_views(attachment_paths)

            protocol.protocol_type = protocol_type
            protocol.protocol_date = protocol_date
            protocol.protocol_data = json.dumps(protocol_data, ensure_ascii=False)
            protocol.final_content = render_template(
                'protocols/protocol_document.html',
                protocol=protocol,
                contract=contract,
                protocol_data=protocol_data,
                meter_entries=meter_entries,
                keys=key_entries,
                inventory_entries=inventory_entries,
                attachment_entries=attachment_entries
            )
            db.session.commit()
            flash('Protokoll aktualisiert.', 'success')
            return redirect(url_for('protocols.protocol_detail', protocol_id=protocol.id))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(f"Error updating protocol: {exc}", exc_info=True)
            flash(f'Protokoll konnte nicht aktualisiert werden: {exc}', 'danger')

    payload_ns = SimpleNamespace(**existing_payload) if isinstance(existing_payload, dict) else None
    return render_template(
        'protocols/create.html',
        contract=contract,
        contract_id=contract.id,
        meters=meters,
        protocol=protocol,
        protocol_payload=payload_ns,
    )


@protocols_bp.route('/<protocol_id>')
@login_required
def protocol_detail(protocol_id):
    """Protokoll Details"""
    try:
        ensure_archiving_columns()
        protocol = Protocol.query.get_or_404(protocol_id)
        contract = Contract.query.get(protocol.contract_id)
        data = {}
        try:
            data = json.loads(protocol.protocol_data) if protocol.protocol_data else {}
        except json.JSONDecodeError:
            pass

        keys = data.get('keys') if isinstance(data.get('keys'), list) else []
        meter_entries = data.get('meter_entries') if isinstance(data.get('meter_entries'), list) else []
        attachments = _normalize_attachments(data.get('attachments', []))
        attachment_views = _build_attachment_views(attachments)
        inventory_entries = data.get('inventory') if isinstance(data.get('inventory'), list) else []

        data['is_finalized'] = bool(data.get('is_finalized'))
        data['keys'] = keys
        data['meter_entries'] = meter_entries
        data['meter_photos'] = data.get('meter_photos') if isinstance(data.get('meter_photos'), dict) else {}
        data['attachments'] = attachments
        data['inventory'] = inventory_entries

        if not data.get('key_count') and keys:
            try:
                data['key_count'] = sum((int(k.get('quantity') or 1) for k in keys))
            except Exception:
                data['key_count'] = len(keys)

        protocol_data = SimpleNamespace(**data)

        return render_template(
            'protocols/detail.html',
            protocol=protocol,
            contract=contract,
            protocol_data=protocol_data,
            protocol_keys=keys,
            protocol_meter_entries=meter_entries,
            protocol_attachments=attachment_views,
            protocol_inventory=inventory_entries,
        )
    except Exception as exc:
        current_app.logger.error('Protocol detail failed: %s', exc, exc_info=True)
        flash(f'Protokoll konnte nicht geladen werden: {exc}', 'danger')
        return redirect(url_for('protocols.protocols_list'))


@protocols_bp.route('/<protocol_id>/finalize', methods=['POST'])
@login_required
def finalize_protocol(protocol_id):
    ensure_archiving_columns()
    protocol = Protocol.query.get_or_404(protocol_id)
    contract = Contract.query.get(protocol.contract_id)
    try:
        data = json.loads(protocol.protocol_data) if protocol.protocol_data else {}
    except Exception:
        data = {}

    if _is_protocol_finalized(data):
        flash('Der Vorgang ist bereits abgeschlossen.', 'info')
        return redirect(url_for('protocols.protocol_detail', protocol_id=protocol.id))

    data['is_finalized'] = True
    data['finalized_at'] = datetime.utcnow().isoformat()
    data['finalized_by'] = session.get('user_id')

    keys = data.get('keys') if isinstance(data.get('keys'), list) else []
    meter_entries = data.get('meter_entries') if isinstance(data.get('meter_entries'), list) else []
    inventory_entries = data.get('inventory') if isinstance(data.get('inventory'), list) else []
    attachments = _normalize_attachments(data.get('attachments', []))
    attachment_views = _build_attachment_views(attachments)

    protocol.protocol_data = json.dumps(data, ensure_ascii=False)
    protocol.final_content = render_template(
        'protocols/protocol_document.html',
        protocol=protocol,
        contract=contract,
        protocol_data=data,
        meter_entries=meter_entries,
        keys=keys,
        inventory_entries=inventory_entries,
        attachment_entries=attachment_views
    )
    db.session.commit()
    flash('Protokoll revisionssicher abgeschlossen.', 'success')
    return redirect(url_for('protocols.protocol_detail', protocol_id=protocol.id))


@protocols_bp.route('/photos/<path:filename>')
@login_required
def protocol_photo(filename):
    """Stellt hochgeladene Zählerstand-Fotos bereit."""
    directory = os.path.join(current_app.config['UPLOAD_FOLDER'], 'protocols')
    return send_from_directory(directory, filename)


@protocols_bp.route('/export/<string:fmt>')
@login_required
def export_protocols(fmt):
    ensure_archiving_columns()
    protocols = Protocol.query.order_by(Protocol.protocol_date.desc()).all()

    records = []
    for proto in protocols:
        try:
            data = json.loads(proto.protocol_data) if proto.protocol_data else {}
        except json.JSONDecodeError:
            data = {}
        records.append({
            'Protokoll-ID': proto.id,
            'Vertragsnummer': proto.protocol_contract.contract_number if proto.protocol_contract else '',
            'Typ': proto.protocol_type,
            'Datum': proto.protocol_date.strftime('%d.%m.%Y'),
            'Schlüsselanzahl': data.get('key_count', ''),
            'Inventarposten': len(data.get('inventory', []) or []),
            'Anmerkungen': data.get('notes', ''),
        })

    if not records:
        flash('Keine Protokolle vorhanden.', 'warning')
        return redirect(url_for('protocols.protocols_list'))

    df = pd.DataFrame(records)
    buffer = BytesIO()

    if fmt == 'csv':
        buffer.write(df.to_csv(index=False).encode('utf-8'))
        buffer.seek(0)
        return send_file(buffer, mimetype='text/csv', download_name='protokolle.csv', as_attachment=True)

    if fmt == 'xlsx':
        df.to_excel(buffer, index=False)
        buffer.seek(0)
        return send_file(buffer, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', download_name='protokolle.xlsx', as_attachment=True)

    if fmt == 'pdf':
        html = render_template('protocols/export_pdf.html', protocols=records)
        pdf_bytes = generate_pdf_bytes(html)
        buffer = BytesIO(pdf_bytes)
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', download_name='protokolle.pdf', as_attachment=True)

    flash('Unbekanntes Exportformat', 'danger')
    return redirect(url_for('protocols.protocols_list'))


@protocols_bp.route('/<protocol_id>/download/pdf')
@login_required
def download_protocol_pdf(protocol_id):
    ensure_archiving_columns()
    protocol = Protocol.query.get_or_404(protocol_id)
    contract = Contract.query.get(protocol.contract_id)

    try:
        data = json.loads(protocol.protocol_data) if protocol.protocol_data else {}
    except json.JSONDecodeError:
        data = {}

    keys = data.get('keys') if isinstance(data.get('keys'), list) else []
    meter_entries = data.get('meter_entries') if isinstance(data.get('meter_entries'), list) else []
    inventory_entries = data.get('inventory') if isinstance(data.get('inventory'), list) else []
    attachments = _build_attachment_views(_normalize_attachments(data.get('attachments', [])))

    # Fallback für fehlende Schlüsselanzahl, damit das PDF konsistent ist
    if not data.get('key_count') and keys:
        try:
            data['key_count'] = sum((int(k.get('quantity') or 1) for k in keys))
        except Exception:
            data['key_count'] = len(keys)

    html = render_template(
        'protocols/protocol_document.html',
        protocol=protocol,
        contract=contract,
        protocol_data=data,
        meter_entries=meter_entries,
        keys=keys,
        inventory_entries=inventory_entries,
        attachment_entries=attachments
    )

    pdf_bytes = generate_pdf_bytes(html)
    buffer = BytesIO(pdf_bytes)
    buffer.seek(0)

    protocol.final_content = html
    save_protocol_pdf(protocol, html)
    db.session.commit()

    filename = f"protokoll_{protocol.protocol_date.strftime('%Y%m%d')}.pdf"
    return send_file(buffer, mimetype='application/pdf', download_name=filename, as_attachment=True)
