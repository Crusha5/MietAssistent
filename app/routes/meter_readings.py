from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, session, current_app, send_from_directory
from flask_jwt_extended import jwt_required
from app.extensions import db
from app.models import MeterReading, Meter, MeterType, Apartment, Tenant, User, Building, UserPreference  # ✅ Building hinzugefügt
from datetime import datetime
from app.routes.main import login_required
import os
from werkzeug.utils import secure_filename
import uuid
import csv
import io
import json
from flask import Response
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def _meter_debug_enabled():
    user_id = session.get('user_id')
    if not user_id:
        return False

    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        return False

    prefs = UserPreference.query.filter_by(user_id=user_id).first()
    if not prefs:
        return False

    try:
        data = json.loads(prefs.preferences or '{}')
    except Exception:
        return False

    return bool(data.get('meter_debug_mode'))
def _active_readings_query():
    return MeterReading.query.filter(
        (MeterReading.is_archived.is_(False)) | (MeterReading.is_archived.is_(None))
    )


def _latest_active_value(meter_id, ignore_ids=None):
    ignore_ids = ignore_ids or []
    query = _active_readings_query().filter(MeterReading.meter_id == meter_id)
    if ignore_ids:
        query = query.filter(~MeterReading.id.in_(ignore_ids))
    reading = query.order_by(
        MeterReading.reading_date.desc(),
        MeterReading.created_at.desc(),
    ).first()
    return reading.reading_value if reading else None


def _validate_meter_hierarchy(meter, new_value, ignore_ids=None):
    if _meter_debug_enabled():
        return

    if not meter:
        return

    tolerance = 0.0001
    ignore_ids = ignore_ids or []

    if meter.parent_meter:
        parent_value = _latest_active_value(meter.parent_meter.id, ignore_ids)
        if parent_value is not None and new_value - parent_value > tolerance:
            raise ValueError(
                f'Der Unterzählerwert darf den Hauptzählerstand ({parent_value}) nicht überschreiten.'
            )

        sibling_sum = new_value
        for sub in meter.parent_meter.sub_meters or []:
            if sub.is_archived:
                continue
            if sub.id == meter.id:
                continue
            sibling_sum += _latest_active_value(sub.id, ignore_ids) or 0

        if parent_value is not None:
            delta = parent_value - sibling_sum
            if abs(delta) > tolerance:
                raise ValueError(
                    f'Die Summe der Unterzähler ({sibling_sum:.3f}) muss dem Hauptzähler ({parent_value:.3f}) entsprechen.'
                )

    active_subs = [s for s in (meter.sub_meters or []) if not s.is_archived]
    if active_subs:
        sub_sum = sum(_latest_active_value(sub.id, ignore_ids) or 0 for sub in active_subs)
        if sub_sum > 0:
            delta = new_value - sub_sum
            if abs(delta) > tolerance:
                raise ValueError(
                    f'Die Summe der Unterzähler ({sub_sum:.3f}) muss dem Hauptzähler ({new_value:.3f}) entsprechen.'
                )

meter_bp = Blueprint('meter_readings', __name__)

# Konfiguration für Datei-Uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'heic'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def build_filtered_query(filter_args):
    """Baut die gefilterte Query basierend auf den Filterargumenten"""
    query = db.session.query(MeterReading).\
        join(Meter, MeterReading.meter_id == Meter.id).\
        join(Building, Meter.building_id == Building.id).\
        join(MeterType, Meter.meter_type_id == MeterType.id).\
        outerjoin(Apartment, Meter.apartment_id == Apartment.id).\
        filter((MeterReading.is_archived.is_(False)) | (MeterReading.is_archived.is_(None)))

    # Filter anwenden
    building_id = filter_args.get('building_id')
    apartment_id = filter_args.get('apartment_id')
    meter_type_id = filter_args.get('meter_type_id')
    category = filter_args.get('category')
    date_from = filter_args.get('date_from')
    date_to = filter_args.get('date_to')
    show_only_submeters = filter_args.get('show_only_submeters')

    if building_id and building_id != 'all':
        query = query.filter(Meter.building_id == building_id)

    if apartment_id and apartment_id != 'all':
        query = query.filter(Meter.apartment_id == apartment_id)

    if meter_type_id and meter_type_id != 'all':
        query = query.filter(Meter.meter_type_id == meter_type_id)

    if category and category != 'all':
        query = query.filter(MeterType.category == category)

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date >= date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date <= date_to_obj)
        except ValueError:
            pass

    if show_only_submeters:
        query = query.filter(Meter.parent_meter_id.isnot(None))

    return query.order_by(
        Building.name, 
        Meter.meter_number,
        MeterReading.reading_date.desc()
    )

def get_filtered_readings_for_export(filter_args):
    """Hilfsfunktion für Export - gibt alle gefilterten Daten zurück (ohne Paginierung)"""
    query = build_filtered_query(filter_args)
    readings = query.all()
    
    # Für jeden Reading Parent-Meter separat laden
    for reading in readings:
        if reading.meter.parent_meter_id:
            reading.meter.parent_meter = Meter.query.get(reading.meter.parent_meter_id)
    
    return readings

@meter_bp.route('/')
@login_required
def meter_readings_list():
    try:
        # Filter-Zustand aus Session lesen (standardmäßig True = eingeklappt)
        filter_collapsed = session.get('meter_readings_filter_collapsed', True)
        
        # Filter-Parameter aus Request
        building_id = request.args.get('building_id')
        apartment_id = request.args.get('apartment_id')
        meter_type_id = request.args.get('meter_type_id')
        category = request.args.get('category')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        show_only_submeters = request.args.get('show_only_submeters')
        
        # Paginierung-Parameter
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        
        # Validiere per_page Werte
        if per_page not in [25, 50, 100]:
            per_page = 25

        # Bauen der gefilterten Query
        query = build_filtered_query({
            'building_id': building_id,
            'apartment_id': apartment_id,
            'meter_type_id': meter_type_id,
            'category': category,
            'date_from': date_from,
            'date_to': date_to,
            'show_only_submeters': show_only_submeters
        })

        # Paginierung anwenden
        pagination = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        readings = pagination.items

        # Für jeden Reading Parent-Meter separat laden
        for reading in readings:
            if reading.meter.parent_meter_id:
                reading.meter.parent_meter = Meter.query.get(reading.meter.parent_meter_id)

        # Daten für Filter-Dropdowns
        buildings = Building.query.order_by(Building.name).all()
        apartments = Apartment.query.order_by(Apartment.apartment_number).all()
        meter_types = MeterType.query.filter_by(is_active=True).order_by(MeterType.name).all()

        # Kategorien für Filter
        categories = db.session.query(MeterType.category).distinct().all()
        categories = [cat[0] for cat in categories if cat[0]]

        # Basis-URL-Parameter für Paginierung (ohne page und per_page)
        base_url_args = {}
        for key, value in request.args.items():
            if key not in ['page', 'per_page'] and value:
                base_url_args[key] = value

        return render_template('meter_readings/list.html', 
                             readings=readings,
                             pagination=pagination,
                             buildings=buildings,
                             apartments=apartments,
                             meter_types=meter_types,
                             categories=categories,
                             base_url_args=base_url_args,
                             filter_collapsed=filter_collapsed,  # Neue Variable für Filter-Zustand
                             current_filters={
                                 'building_id': building_id,
                                 'apartment_id': apartment_id,
                                 'meter_type_id': meter_type_id,
                                 'category': category,
                                 'date_from': date_from,
                                 'date_to': date_to,
                                 'show_only_submeters': show_only_submeters,
                                 'per_page': per_page
                             })
        
    except Exception as e:
        print(f"ERROR in meter_readings_list: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Fehler beim Laden der Zählerstände: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

# Neue Route zum Umschalten des Filter-Zustands
@meter_bp.route('/toggle-filter', methods=['POST'])
@login_required
def toggle_filter():
    """Schaltet den Filter-Zustand um und speichert ihn in der Session"""
    try:
        current_state = session.get('meter_readings_filter_collapsed', True)
        session['meter_readings_filter_collapsed'] = not current_state
        session.modified = True
        return jsonify({'success': True, 'collapsed': not current_state})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def get_filtered_readings(filter_args):
    """Hilfsfunktion für Filter - wiederverwendbar für Export"""
    from sqlalchemy.orm import aliased
    
    # Alias für Parent-Meter erstellen
    ParentMeter = aliased(Meter)
    
    query = db.session.query(MeterReading).\
        join(Meter, MeterReading.meter_id == Meter.id).\
        join(Building, Meter.building_id == Building.id).\
        join(MeterType, Meter.meter_type_id == MeterType.id).\
        outerjoin(Apartment, Meter.apartment_id == Apartment.id).\
        outerjoin(ParentMeter, Meter.parent_meter_id == ParentMeter.id)  # ✅ Korrigiert mit Alias
    
    # Filter anwenden
    building_id = filter_args.get('building_id')
    apartment_id = filter_args.get('apartment_id')
    meter_type_id = filter_args.get('meter_type_id')
    category = filter_args.get('category')
    date_from = filter_args.get('date_from')
    date_to = filter_args.get('date_to')
    show_only_submeters = filter_args.get('show_only_submeters')
    
    if building_id and building_id != 'all':
        query = query.filter(Meter.building_id == building_id)
    
    if apartment_id and apartment_id != 'all':
        query = query.filter(Meter.apartment_id == apartment_id)
    
    if meter_type_id and meter_type_id != 'all':
        query = query.filter(Meter.meter_type_id == meter_type_id)
    
    if category and category != 'all':
        query = query.filter(MeterType.category == category)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date <= date_to_obj)
        except ValueError:
            pass
    
    if show_only_submeters:
        query = query.filter(Meter.parent_meter_id.isnot(None))
    
    return query.order_by(
        Building.name, 
        Meter.meter_number,
        MeterReading.reading_date.desc()
    ).all()

@meter_bp.route('/export/csv')
@login_required
def export_csv():
    """Export Zählerstände als CSV - alle gefilterten Daten"""
    try:
        # Verwende die neue Funktion für Export (ohne Paginierung)
        readings = get_filtered_readings_for_export(request.args)
        
        # CSV erstellen
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_ALL)
        
        # Header
        writer.writerow([
            'Datum', 'Gebäude', 'Adresse', 'Zählernummer', 'Beschreibung',
            'Unterzähler von', 'Wohnung', 'Kategorie', 'Zählertyp', 'Wert', 
            'Einheit', 'Ablesetyp', 'Notizen'
        ])
        
        # Daten
        for reading in readings:
            parent_meter = reading.meter.parent_meter
            writer.writerow([
                reading.reading_date.strftime('%d.%m.%Y'),
                reading.meter.building.name,
                f"{reading.meter.building.street} {reading.meter.building.street_number}, {reading.meter.building.zip_code} {reading.meter.building.city}",
                reading.meter.meter_number,
                reading.meter.description or '',
                parent_meter.meter_number if parent_meter else '',
                reading.meter.apartment.apartment_number if reading.meter.apartment else '',
                reading.meter.meter_type.category,
                reading.meter.meter_type.name,
                str(reading.reading_value),
                reading.meter.meter_type.unit,
                reading.reading_type,
                reading.notes or ''
            ])
        
        # Response vorbereiten
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"zählerstände_export_{timestamp}.csv"
        
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        flash(f'Fehler beim CSV-Export: {str(e)}', 'danger')
        return redirect(url_for('meter_readings.meter_readings_list'))

@meter_bp.route('/export/excel')
@login_required
def export_excel():
    """Export Zählerstände als Excel - alle gefilterten Daten"""
    try:
        # Verwende die neue Funktion für Export (ohne Paginierung)
        readings = get_filtered_readings_for_export(request.args)
        
        # Daten für Excel vorbereiten
        data = []
        for reading in readings:
            parent_meter = reading.meter.parent_meter
            data.append({
                'Datum': reading.reading_date.strftime('%d.%m.%Y'),
                'Gebäude': reading.meter.building.name,
                'Adresse': f"{reading.meter.building.street} {reading.meter.building.street_number}",
                'PLZ': reading.meter.building.zip_code,
                'Stadt': reading.meter.building.city,
                'Zählernummer': reading.meter.meter_number,
                'Beschreibung': reading.meter.description or '',
                'Unterzähler von': parent_meter.meter_number if parent_meter else '',
                'Wohnung': reading.meter.apartment.apartment_number if reading.meter.apartment else '',
                'Kategorie': reading.meter.meter_type.category,
                'Zählertyp': reading.meter.meter_type.name,
                'Wert': reading.reading_value,
                'Einheit': reading.meter.meter_type.unit,
                'Ablesetyp': reading.reading_type,
                'Notizen': reading.notes or ''
            })
        
        # DataFrame erstellen
        df = pd.DataFrame(data)
        
        # Excel erstellen
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Zählerstände', index=False)
            
            # Formatierung
            workbook = writer.book
            worksheet = writer.sheets['Zählerstände']
            
            # Spaltenbreiten anpassen
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"zählerstände_export_{timestamp}.xlsx"
        
        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        flash(f'Fehler beim Excel-Export: {str(e)}', 'danger')
        return redirect(url_for('meter_readings.meter_readings_list'))

@meter_bp.route('/export/pdf')
@login_required
def export_pdf():
    """Export Zählerstände als PDF - alle gefilterten Daten"""
    try:
        # Verwende die neue Funktion für Export (ohne Paginierung)
        readings = get_filtered_readings_for_export(request.args)
        
        # PDF erstellen
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30)
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            textColor=colors.HexColor('#1e40af')
        )
        
        # Titel
        title = Paragraph("Zählerstände - Export", title_style)
        elements.append(title)
        
        # Metadaten
        meta_data = [
            f"Erstellt am: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Anzahl Einträge: {len(readings)}",
            f"Exportiert von: MietAssistent"
        ]
        
        for meta in meta_data:
            elements.append(Paragraph(meta, styles['Normal']))
            elements.append(Spacer(1, 5))
        
        elements.append(Spacer(1, 20))
        
        # Tabelle erstellen
        if readings:
            # Tabellen-Header
            table_data = [[
                'Datum', 'Gebäude', 'Zähler', 'Wohnung', 
                'Kategorie', 'Wert', 'Einheit', 'Typ'
            ]]
            
            # Tabellen-Daten
            for reading in readings:
                table_data.append([
                    reading.reading_date.strftime('%d.%m.%Y'),
                    reading.meter.building.name,
                    f"{reading.meter.meter_number}{' (U)' if reading.meter.parent_meter_id else ''}",
                    reading.meter.apartment.apartment_number if reading.meter.apartment else '-',
                    reading.meter.meter_type.category,
                    str(reading.reading_value),
                    reading.meter.meter_type.unit,
                    reading.reading_type
                ])
            
            # Tabelle formatieren
            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(table)
        else:
            elements.append(Paragraph("Keine Zählerstände gefunden", styles['Normal']))
        
        # PDF erstellen
        doc.build(elements)
        buffer.seek(0)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"zaehlerstaende_export_{timestamp}.pdf"
        
        return Response(
            buffer.getvalue(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        flash(f'Fehler beim PDF-Export: {str(e)}', 'danger')
        return redirect(url_for('meter_readings.meter_readings_list'))


def get_filtered_readings(filter_args):
    """Hilfsfunktion für Filter - ohne problematischen Selbst-Join"""
    # Einfache Query ohne Parent-Meter Join
    query = db.session.query(MeterReading).\
        join(Meter, MeterReading.meter_id == Meter.id).\
        join(Building, Meter.building_id == Building.id).\
        join(MeterType, Meter.meter_type_id == MeterType.id).\
        outerjoin(Apartment, Meter.apartment_id == Apartment.id)
    # KEIN Join auf Meter.parent_meter mehr!
    
    # Filter anwenden
    building_id = filter_args.get('building_id')
    apartment_id = filter_args.get('apartment_id')
    meter_type_id = filter_args.get('meter_type_id')
    category = filter_args.get('category')
    date_from = filter_args.get('date_from')
    date_to = filter_args.get('date_to')
    show_only_submeters = filter_args.get('show_only_submeters')
    
    if building_id and building_id != 'all':
        query = query.filter(Meter.building_id == building_id)
    
    if apartment_id and apartment_id != 'all':
        query = query.filter(Meter.apartment_id == apartment_id)
    
    if meter_type_id and meter_type_id != 'all':
        query = query.filter(Meter.meter_type_id == meter_type_id)
    
    if category and category != 'all':
        query = query.filter(MeterType.category == category)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(MeterReading.reading_date <= date_to_obj)
        except ValueError:
            pass
    
    if show_only_submeters:
        query = query.filter(Meter.parent_meter_id.isnot(None))
    
    return query.order_by(
        Building.name, 
        Meter.meter_number,
        MeterReading.reading_date.desc()
    ).all()

# Konfiguration für Datei-Uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'heic'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@meter_bp.route('/create', methods=['GET', 'POST'])
@meter_bp.route('/meter-readings/create', methods=['GET', 'POST'])
@login_required
def create_meter_reading():
    meter_id = request.args.get('meter_id')
    selected_meter = None
    
    if meter_id:
        selected_meter = Meter.query.get(meter_id)
    
    meters = Meter.query.all()
    
    if request.method == 'POST':
        try:
            # Debug: Formulardaten ausgeben
            print("Form data:", dict(request.form))

            meter = Meter.query.options(
                db.joinedload(Meter.parent_meter).joinedload(Meter.sub_meters),
                db.joinedload(Meter.sub_meters),
            ).get(request.form['meter_id'])
            if not meter:
                raise ValueError('Ungültiger Zähler.')

            # Erstelle Zählerstand mit allen erforderlichen Feldern
            reading = MeterReading(
                id=str(uuid.uuid4()),
                meter_id=meter.id,
                reading_value=float(request.form['reading_value']),
                reading_date=datetime.strptime(request.form['reading_date'], '%Y-%m-%d').date(),
                reading_type=request.form.get('reading_type', 'actual'),
                notes=request.form.get('notes', ''),
                is_manual_entry=True,
                created_by=session.get('user_id')  # Verwende Session User ID
            )

            _validate_meter_hierarchy(meter, reading.reading_value)

            # Foto-Upload verarbeiten
            if 'photo' in request.files:
                file = request.files['photo']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    upload_dir = os.path.join(current_app.config.get('UPLOAD_ROOT') or '/uploads', 'meter_photos')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, unique_filename)
                    file.save(file_path)
                    reading.photo_path = unique_filename
            
            db.session.add(reading)
            db.session.commit()
            flash('Zählerstand erfolgreich erfasst!', 'success')
            return redirect(url_for('meter_readings.meter_readings_list'))
            
        except ValueError as ve:
            db.session.rollback()
            flash(str(ve), 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Erfassen des Zählerstands: {str(e)}", exc_info=True)
            flash(f'Fehler beim Erfassen des Zählerstands: {str(e)}', 'danger')
    
    return render_template('meter_readings/create.html', 
                         meters=meters,
                         selected_meter=selected_meter)

@meter_bp.route('/<reading_id>')
@meter_bp.route('/meter-readings/<reading_id>')
@login_required
def reading_detail(reading_id):
    reading = MeterReading.query.options(
        db.joinedload(MeterReading.meter).joinedload(Meter.building),
        db.joinedload(MeterReading.meter).joinedload(Meter.meter_type),
        db.joinedload(MeterReading.meter).joinedload(Meter.apartment),
        db.joinedload(MeterReading.user)
    ).get_or_404(reading_id)
    
    # Lade Korrektur-Historie falls vorhanden
    correction_readings = []
    if reading.correction_of_id:
        # Dies ist eine Korrektur, zeige das Original an
        original_reading = MeterReading.query.get(reading.correction_of_id)
        if original_reading:
            correction_readings = MeterReading.query.filter_by(correction_of_id=reading.correction_of_id).all()
    else:
        # Dies ist ein Original, zeige alle Korrekturen an
        correction_readings = MeterReading.query.filter_by(correction_of_id=reading.id).all()

    return render_template('meter_readings/detail.html',
                         reading=reading,
                         correction_readings=correction_readings,
                         meter_debug=_meter_debug_enabled())


@meter_bp.route('/photos/<path:filename>')
@login_required
def meter_photo(filename):
    """Stellt hochgeladene Zählerfotos bereit."""
    directory = os.path.join(current_app.config.get('UPLOAD_ROOT') or '/uploads', 'meter_photos')
    return send_from_directory(directory, filename)

@meter_bp.route('/debug/upload-test')
@login_required
def debug_upload_test():
    """Debug-Route um Upload-Konfiguration zu testen"""
    try:
        upload_dir = os.path.join(current_app.config.get('UPLOAD_ROOT') or '/uploads', 'meter_photos')
        exists = os.path.exists(upload_dir)
        writable = os.access(upload_dir, os.W_OK) if exists else False
        
        return jsonify({
            'upload_folder': current_app.config.get('UPLOAD_ROOT') or '/uploads',
            'meter_photos_dir': upload_dir,
            'dir_exists': exists,
            'dir_writable': writable,
            'max_file_size': current_app.config['MAX_CONTENT_LENGTH']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API Routes
@meter_bp.route('/api/meter-readings', methods=['GET'])
@jwt_required()
def get_meter_readings_api():
    readings = _active_readings_query().all()
    return jsonify([{
        'id': reading.id,
        'meter_id': reading.meter_id,
        'reading_value': float(reading.reading_value),
        'reading_date': reading.reading_date.isoformat(),
        'reading_type': reading.reading_type,
        'notes': reading.notes,
        'created_at': reading.created_at.isoformat()
    } for reading in readings])

@meter_bp.route('/api/meter-readings', methods=['POST'])
@jwt_required()
def create_meter_reading_api():
    data = request.get_json()

    try:
        meter = Meter.query.options(
            db.joinedload(Meter.parent_meter).joinedload(Meter.sub_meters),
            db.joinedload(Meter.sub_meters),
        ).get(data['meter_id'])
        if not meter:
            raise ValueError('Ungültiger Zähler.')

        reading = MeterReading(
            id=str(uuid.uuid4()),
            meter_id=meter.id,
            reading_value=float(data['reading_value']),
            reading_date=datetime.fromisoformat(data['reading_date']).date(),
            reading_type=data.get('reading_type', 'actual'),
            notes=data.get('notes', ''),
            is_manual_entry=True
        )

        _validate_meter_hierarchy(meter, reading.reading_value)

        db.session.add(reading)
        db.session.commit()
        
        return jsonify({
            'message': 'Zählerstand erfolgreich erfasst',
            'id': reading.id
        }), 201
        
    except ValueError as ve:
        db.session.rollback()
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@meter_bp.route('/api/meters/<meter_id>/readings', methods=['GET'])
@jwt_required()
def get_meter_readings_by_meter(meter_id):
    readings = (
        _active_readings_query()
        .filter(MeterReading.meter_id == meter_id)
        .order_by(MeterReading.reading_date.desc())
        .all()
    )
    return jsonify([{
        'id': reading.id,
        'reading_value': float(reading.reading_value),
        'reading_date': reading.reading_date.isoformat(),
        'reading_type': reading.reading_type,
        'notes': reading.notes,
        'created_at': reading.created_at.isoformat()
    } for reading in readings])

@meter_bp.route('/<reading_id>/create-correction', methods=['POST'])
@login_required
def create_correction(reading_id):
    """Erstellt eine Korrekturbuchung für einen Zählerstand"""
    original_reading = MeterReading.query.get_or_404(reading_id)

    if request.method == 'POST':
        try:
            # Erstelle Korrekturbuchung
            meter = Meter.query.options(
                db.joinedload(Meter.parent_meter).joinedload(Meter.sub_meters),
                db.joinedload(Meter.sub_meters),
            ).get(original_reading.meter_id)

            correction_value = float(request.form['correction_value'])
            _validate_meter_hierarchy(meter, correction_value, ignore_ids=[original_reading.id])

            correction_reading = MeterReading(
                id=str(uuid.uuid4()),
                meter_id=original_reading.meter_id,
                reading_value=correction_value,
                reading_date=datetime.strptime(request.form['correction_date'], '%Y-%m-%d').date(),
                reading_type='correction',
                notes=f"Korrektur von Zählerstand {original_reading.id}. Ursprünglicher Wert: {original_reading.reading_value} vom {original_reading.reading_date.strftime('%d.%m.%Y')}.\nKorrektur-Grund: {request.form['correction_reason']}",
                correction_of_id=original_reading.id,
                correction_reason=request.form['correction_reason'],
                is_manual_entry=True,
                created_by=session.get('user_id')
            )

            original_reading.is_archived = True
            db.session.add(correction_reading)
            db.session.commit()

            flash('Korrektur erfolgreich erstellt!', 'success')
            return redirect(url_for('meter_readings.reading_detail', reading_id=correction_reading.id))

        except ValueError as ve:
            db.session.rollback()
            flash(str(ve), 'danger')
            return redirect(url_for('meter_readings.reading_detail', reading_id=reading_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Erstellen der Korrektur: {str(e)}", exc_info=True)
            flash(f'Fehler beim Erstellen der Korrektur: {str(e)}', 'danger')
            return redirect(url_for('meter_readings.reading_detail', reading_id=reading_id))


@meter_bp.route('/<reading_id>/debug-delete', methods=['POST'])
@login_required
def debug_delete_reading(reading_id):
    if not _meter_debug_enabled():
        flash('Debug-Modus nur für Administratoren verfügbar.', 'danger')
        return redirect(url_for('meter_readings.reading_detail', reading_id=reading_id))

    reading = MeterReading.query.get_or_404(reading_id)

    try:
        db.session.delete(reading)
        db.session.commit()
        flash('Zählerstand revisionsfrei gelöscht.', 'warning')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Debug-Löschung fehlgeschlagen: %s', exc, exc_info=True)
        flash(f'Löschung nicht möglich: {exc}', 'danger')
        return redirect(url_for('meter_readings.reading_detail', reading_id=reading_id))

    return redirect(url_for('meter_readings.meter_readings_list'))