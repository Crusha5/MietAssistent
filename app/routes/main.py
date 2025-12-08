from flask import Blueprint, render_template, redirect, url_for, session, request, flash, jsonify
from app.models import User, Apartment, Tenant, Building, Meter, MeterType, MeterReading, Document, Contract, Protocol, OperatingCost, Income, DueDate, MaintenanceTask, Notification, Settlement
from datetime import datetime, timedelta, date
import uuid
from app.extensions import db
from app.utils.project_profile import load_project_profile
from app.utils.schema_helpers import ensure_archiving_columns, ensure_user_landlord_flag
from sqlalchemy import inspect, text

main_bp = Blueprint('main', __name__)


def _contract_options(contracts):
    options = []
    for c in contracts:
        label_parts = [c.contract_number or 'Vertrag']
        if c.apartment and c.apartment.building:
            building_label = c.apartment.building.name or c.apartment.building.address or c.apartment.building.id
            label_parts.append(building_label)
        if c.tenant:
            label_parts.append(f"{c.tenant.first_name} {c.tenant.last_name}")
        options.append({'id': c.id, 'label': ' – '.join(label_parts), 'tenant_id': c.tenant_id})
    return options

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ensure_user_landlord_flag()
        if 'user_id' not in session:
            flash('Ihre Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.', 'warning')
            return redirect(url_for('auth.web_login'))

        user = User.query.get(session['user_id'])
        if not user or not user.is_active:
            session.clear()
            flash('Ihr Konto ist inaktiv. Bitte wenden Sie sich an einen Administrator.', 'danger')
            return redirect(url_for('auth.web_login'))
        return f(*args, **kwargs)
    return decorated_function

# Setze Session-Lifetime (optional, in deiner Haupt-App)
# app.permanent_session_lifetime = timedelta(hours=24)


def _ensure_notifications_table():
    inspector = inspect(db.engine)
    if not inspector.has_table('notifications'):
        db.create_all()
    else:
        columns = {col['name'] for col in inspector.get_columns('notifications')}
        with db.engine.begin() as conn:
            if 'read_at' not in columns:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN read_at DATETIME"))
            if 'last_shown_at' not in columns:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN last_shown_at DATETIME"))


def _push_notification(user_id, title, message, link=None, category='info', dedup_hours=24):
    """Leichte Deduplizierung, damit Erinnerungen nicht gespammt werden."""
    if not user_id:
        return None

    _ensure_notifications_table()
    window_start = datetime.utcnow() - timedelta(hours=dedup_hours)
    existing = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.title == title,
        Notification.message == message,
        Notification.created_at >= window_start,
    ).first()
    if existing:
        existing.last_shown_at = datetime.utcnow()
        db.session.commit()
        return existing

    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        category=category,
        last_shown_at=datetime.utcnow(),
    )
    db.session.add(notif)
    db.session.commit()
    return notif


def _refresh_notification_state(user_id, remind_after_hours=24):
    """Reaktiviert gelesene Benachrichtigungen nach Ablauf des Erinnerungsfensters."""
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=remind_after_hours)

    stale = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.is_read.is_(True),
        Notification.read_at <= cutoff,
    ).all()

    needs_commit = False
    for notif in stale:
        notif.is_read = False
        notif.read_at = None
        notif.last_shown_at = now
        needs_commit = True

    missing_last_shown = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.last_shown_at.is_(None)
    ).all()

    for notif in missing_last_shown:
        notif.last_shown_at = notif.created_at or now
        needs_commit = True

    if needs_commit:
        db.session.commit()


def _get_active_notifications(user_id, limit=20):
    _ensure_notifications_table()
    _refresh_notification_state(user_id)

    items = (
        Notification.query
        .filter_by(user_id=user_id, is_read=False)
        .order_by(Notification.last_shown_at.desc())
        .limit(limit)
        .all()
    )
    unread = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return items, unread

def _build_dashboard_context(user=None):
    ensure_archiving_columns()
    ensure_user_landlord_flag()
    inspector = inspect(db.engine)

    # Ensure new tables exist for landlord cockpit data
    if not inspector.has_table('incomes') or not inspector.has_table('due_dates'):
        db.create_all()

    apartments = Apartment.query.all()
    tenants = Tenant.query.all()
    buildings = Building.query.all()
    meters = Meter.query.all()
    contracts = Contract.query.filter((Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None))).all()
    protocols = Protocol.query.filter((Protocol.is_archived.is_(False)) | (Protocol.is_archived.is_(None))).all()

    stats = {
        'apartment_count': len(apartments),
        'tenant_count': len(tenants),
        'building_count': len(buildings),
        'occupied_count': len([apt for apt in apartments if apt.status == 'occupied']),
        'vacant_count': len([apt for apt in apartments if apt.status == 'vacant'])
    }

    month_start = date.today().replace(day=1)
    monthly_income = sum(
        (income.amount or 0) for income in Income.query.filter(Income.received_on >= month_start).all()
    )
    total_expenses = sum((c.amount_gross or 0) for c in OperatingCost.query.all())

    due_contracts = [
        c for c in contracts
        if c.end_date and datetime.utcnow().date() <= c.end_date <= datetime.utcnow().date() + timedelta(days=30)
    ]
    open_protocols = [p for p in protocols if not p.pdf_path]
    due_dates_open = DueDate.query.filter_by(status='open').order_by(DueDate.due_on.asc()).limit(10).all()

    _ensure_notifications_table()
    notifications = []
    unread_notifications = 0
    if user:
        # Erinnerungen für Wartungen
        reminders_dirty = False
        for task in MaintenanceTask.query.filter_by(status='open').all():
            if task.reminder_date and task.reminder_date <= date.today():
                _push_notification(
                    user.id,
                    f"Wartung fällig: {task.title}",
                    f"{task.category} am {task.scheduled_on.strftime('%d.%m.%Y')} einplanen.",
                    link=url_for('main.maintenance_list'),
                    category='maintenance'
                )
                if not task.reminder_sent:
                    task.reminder_sent = True
                    reminders_dirty = True

        if reminders_dirty:
            db.session.commit()

        remind_interval_hours = 24 * 14
        today = date.today()
        previous_year = today.year - 1
        previous_year_end = date(previous_year, 12, 31)

        if today > previous_year_end:
            for apartment in apartments:
                previous_settlement_exists = Settlement.query.filter(
                    Settlement.apartment_id == apartment.id,
                    Settlement.settlement_year == previous_year,
                    (Settlement.is_archived.is_(False)) | (Settlement.is_archived.is_(None)),
                ).first()

                if previous_settlement_exists:
                    continue

                _push_notification(
                    user.id,
                    f"Nebenkostenabrechnung {previous_year} fehlt",
                    f"Für {apartment.get_full_identifier()} wurde noch keine Abrechnung erstellt. Bitte den Anteil Mieter prüfen und eine Abrechnung anlegen.",
                    link=url_for('settlements.calculate_settlement', apartment_id=apartment.id),
                    category='settlement',
                    dedup_hours=remind_interval_hours,
                )

        for tenant in tenants:
            if not tenant.move_out_date or tenant.move_out_date >= today:
                continue

            settlement_after_move_out = Settlement.query.filter(
                Settlement.tenant_id == tenant.id,
                Settlement.period_end >= tenant.move_out_date,
                (Settlement.is_archived.is_(False)) | (Settlement.is_archived.is_(None)),
            ).first()

            if settlement_after_move_out:
                continue

            apt_label = tenant.apartment.get_full_identifier() if tenant.apartment else 'Wohnung'
            _push_notification(
                user.id,
                f"Abrechnung nach Auszug von {tenant.first_name} {tenant.last_name} fehlt",
                f"Für {apt_label} wurde nach dem Auszug am {tenant.move_out_date.strftime('%d.%m.%Y')} noch keine Nebenkostenabrechnung mit Anteil Mieter erstellt.",
                link=url_for('settlements.calculate_settlement', apartment_id=tenant.apartment_id) if tenant.apartment_id else None,
                category='settlement',
                dedup_hours=remind_interval_hours,
            )

        # Erinnerungen für Vertragsende und Auszug
        for contract in due_contracts:
            _push_notification(
                user.id,
                f"Vertrag endet am {contract.end_date.strftime('%d.%m.%Y')}",
                f"{contract.contract_number or 'Mietvertrag'} läuft aus.",
                link=url_for('contracts.contract_detail', contract_id=contract.id),
                category='contract'
            )

        for tenant in tenants:
            if tenant.move_out_date and date.today() <= tenant.move_out_date <= date.today() + timedelta(days=30):
                _push_notification(
                    user.id,
                    f"Auszug geplant: {tenant.first_name} {tenant.last_name}",
                    f"Auszug am {tenant.move_out_date.strftime('%d.%m.%Y')} prüfen.",
                    link=url_for('tenants.tenant_detail', tenant_id=tenant.id) if hasattr(tenant, 'id') else None,
                    category='tenant'
                )

        notifications, unread_notifications = _get_active_notifications(user.id, limit=15)

    # Datenqualität / automatische Prüfungen
    data_quality = []
    missing_invoices = OperatingCost.query.filter((OperatingCost.invoice_number.is_(None)) | (OperatingCost.invoice_number == '')).count()
    if missing_invoices:
        data_quality.append({
            'title': 'Fehlende Rechnungsnummern',
            'details': f'{missing_invoices} Kostenpositionen ohne Rechnungsnummer'
        })

    anomaly_count = 0
    sorted_readings = sorted(MeterReading.query.all(), key=lambda r: (r.meter_id, r.reading_date))
    last_by_meter = {}
    for reading in sorted_readings:
        previous = last_by_meter.get(reading.meter_id)
        if previous and reading.reading_value < previous:
            anomaly_count += 1
        last_by_meter[reading.meter_id] = reading.reading_value
    if anomaly_count:
        data_quality.append({
            'title': 'Auffällige Zählerstände',
            'details': f'{anomaly_count} Messwerte sind niedriger als der vorherige Stand'
        })

    latest_heat = 0
    if meters:
        for meter in meters:
            if meter.meter_type and 'heiz' in meter.meter_type.name.lower():
                reading = (
                    MeterReading.query.filter_by(meter_id=meter.id)
                    .order_by(MeterReading.reading_date.desc())
                    .first()
                )
                if reading:
                    latest_heat += reading.reading_value

    building_costs = {}
    for cost in OperatingCost.query.all():
        key = str(cost.building_id)
        building_costs[key] = building_costs.get(key, 0) + (cost.amount_gross or 0)

    doc_coverage = 0
    if contracts:
        docs_for_contracts = Document.query.filter(Document.documentable_id.in_([c.id for c in contracts])).count()
        doc_coverage = round((docs_for_contracts / max(len(contracts), 1)) * 100)

    contract_options = _contract_options(contracts)

    maintenance_upcoming = MaintenanceTask.query.order_by(MaintenanceTask.scheduled_on.asc()).limit(5).all()

    landlord_dashboard = {
        'income': monthly_income,
        'expenses': total_expenses,
        'due_dates': len(due_dates_open),
        'open_protocols': len(open_protocols),
        'document_status': doc_coverage,
        'heat_usage': latest_heat,
        'building_costs': building_costs,
        'maintenance': len([m for m in maintenance_upcoming if m.status == 'open'])
    }

    show_landlord_dashboard = False
    if user and (
        user.role == 'landlord'
        or getattr(user, 'is_landlord', False)
        or getattr(user, 'landlord_id', None)
    ):
        show_landlord_dashboard = True

    activities = []
    recent_apartments = Apartment.query.order_by(Apartment.created_at.desc()).limit(3).all()
    for apt in recent_apartments:
        activities.append({
            'type': 'apartment_created',
            'message': f'Wohnung {apt.apartment_number} angelegt',
            'timestamp': apt.created_at,
            'icon': 'bi-building',
            'color': 'primary'
        })

    recent_tenants = Tenant.query.order_by(Tenant.created_at.desc()).limit(3).all()
    for tenant in recent_tenants:
        activities.append({
            'type': 'tenant_created',
            'message': f'Mieter {tenant.first_name} {tenant.last_name} angelegt',
            'timestamp': tenant.created_at,
            'icon': 'bi-person',
            'color': 'success'
        })

    recent_readings = MeterReading.query.order_by(MeterReading.created_at.desc()).limit(3).all()
    for reading in recent_readings:
        activities.append({
            'type': 'meter_reading',
            'message': f'Zählerstand für {reading.meter.meter_number} erfasst',
            'timestamp': reading.created_at,
            'icon': 'bi-speedometer2',
            'color': 'info'
        })

    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    activities = activities[:5]

    return {
        'stats': stats,
        'apartments': apartments,
        'tenants': tenants,
        'contracts': contracts,
        'contract_options': contract_options,
        'landlord_dashboard': landlord_dashboard,
        'data_quality': data_quality,
        'activities': activities,
        'recent_incomes': Income.query.order_by(Income.received_on.desc()).limit(10).all(),
        'open_due_dates': due_dates_open,
        'maintenance_upcoming': maintenance_upcoming,
        'show_landlord_dashboard': show_landlord_dashboard,
        'notifications': notifications,
        'unread_notifications': unread_notifications,
    }


@main_bp.route('/')
def index():
    ensure_user_landlord_flag()
    # Wenn kein Benutzer in der Datenbank existiert, zum Setup weiterleiten
    if not User.query.first():
        return redirect('/setup')

    # Wenn der Benutzer nicht in der Session ist, zum Login weiterleiten
    if 'user_id' not in session:
        return redirect(url_for('auth.web_login'))

    user = User.query.get(session.get('user_id'))
    context = _build_dashboard_context(user=user)

    return render_template('main/dashboard.html', now=datetime.now(), user=user, **context)


@main_bp.route('/projekt')
def project_overview():
    """Öffentliche Seite mit der Produktvision und Kernarchitektur."""
    profile = load_project_profile()
    return render_template('main/project_overview.html', profile=profile, show_sidebar=False)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    context = _build_dashboard_context(user=user)

    return render_template('main/dashboard.html',
                         user=user,
                         now=datetime.now(),
                         **context)


@main_bp.route('/notifications')
@login_required
def notifications_feed():
    user_id = session.get('user_id')
    items, unread = _get_active_notifications(user_id, limit=20)

    def serialize(n):
        return {
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'category': n.category,
            'link': n.link,
            'created_at': (n.last_shown_at or n.created_at).strftime('%d.%m.%Y %H:%M'),
            'is_read': n.is_read,
        }

    return jsonify({'items': [serialize(n) for n in items], 'unread': unread})


@main_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications():
    user_id = session.get('user_id')
    _ensure_notifications_table()
    now = datetime.utcnow()
    Notification.query.filter_by(user_id=user_id, is_read=False).update({
        Notification.is_read: True,
        Notification.read_at: now
    })
    db.session.commit()
    return jsonify({'success': True})


@main_bp.route('/landlord/incomes', methods=['POST'])
@login_required
def add_income_entry():
    flash('Einnahmen bitte auf der Finanzen-Seite erfassen.', 'info')
    return redirect(url_for('finances.incomes_overview'))


@main_bp.route('/landlord/incomes/<income_id>/update', methods=['POST'])
@login_required
def update_income_entry(income_id):
    flash('Einnahmen werden jetzt unter Finanzen > Einnahmen bearbeitet.', 'info')
    return redirect(url_for('finances.incomes_overview'))


@main_bp.route('/landlord/incomes/<income_id>/delete', methods=['POST'])
@login_required
def delete_income(income_id):
    flash('Bitte Einnahmen-Löschungen über Finanzen > Einnahmen durchführen.', 'info')
    return redirect(url_for('finances.incomes_overview'))


@main_bp.route('/landlord/due-dates', methods=['POST'])
@login_required
def add_due_date_entry():
    inspector = inspect(db.engine)
    if not inspector.has_table('due_dates'):
        db.create_all()

    try:
        title = request.form.get('title')
        if not title:
            raise ValueError('Titel angeben')
        due_on_raw = request.form.get('due_on')
        due_on = datetime.strptime(due_on_raw, '%Y-%m-%d').date() if due_on_raw else None
        if not due_on:
            raise ValueError('Fälligkeit angeben')

        due_date = DueDate(
            id=str(uuid.uuid4()),
            title=title,
            due_on=due_on,
            contract_id=request.form.get('contract_id') or None,
            status='open'
        )
        db.session.add(due_date)
        db.session.commit()
        flash('Termin gespeichert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Termin konnte nicht gespeichert werden: {exc}', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/landlord/incomes')
@login_required
def list_incomes():
    return redirect(url_for('finances.incomes_overview'))


@main_bp.route('/landlord/due-dates')
@login_required
def list_due_dates():
    inspector = inspect(db.engine)
    if not inspector.has_table('due_dates'):
        db.create_all()

    page = max(int(request.args.get('page', 1)), 1)
    q = (request.args.get('q') or '').strip()
    status = request.args.get('status') or ''

    query = DueDate.query.outerjoin(Contract)
    if q:
        query = query.filter(Contract.contract_number.ilike(f"%{q}%"))
    if status:
        query = query.filter(DueDate.status == status)

    pagination = query.order_by(DueDate.due_on.desc()).paginate(page=page, per_page=50, error_out=False)
    active_contracts = Contract.query.filter((Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None))).all()

    return render_template(
        'main/due_dates_list.html',
        due_dates=pagination.items,
        pagination=pagination,
        q=q,
        status=status,
        contracts=active_contracts,
        contract_options=_contract_options(active_contracts),
        tenants=Tenant.query.all(),
    )


@main_bp.route('/landlord/due-dates/<due_date_id>/update', methods=['POST'])
@login_required
def update_due_date_entry(due_date_id):
    inspector = inspect(db.engine)
    if not inspector.has_table('due_dates'):
        db.create_all()

    due_date = DueDate.query.get_or_404(due_date_id)
    try:
        due_date.title = request.form.get('title') or due_date.title
        due_on_raw = request.form.get('due_on')
        if due_on_raw:
            due_date.due_on = datetime.strptime(due_on_raw, '%Y-%m-%d').date()
        due_date.contract_id = request.form.get('contract_id') or None
        due_date.status = request.form.get('status') or due_date.status
        db.session.commit()
        flash('Termin aktualisiert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Termin konnte nicht aktualisiert werden: {exc}', 'danger')

    return redirect(request.referrer or url_for('main.dashboard'))


@main_bp.route('/landlord/due-dates/<due_date_id>/delete', methods=['POST'])
@login_required
def delete_due_date(due_date_id):
    due_date = DueDate.query.get_or_404(due_date_id)
    try:
        db.session.delete(due_date)
        db.session.commit()
        flash('Termin gelöscht.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Löschen fehlgeschlagen: {exc}', 'danger')
    return redirect(request.referrer or url_for('main.dashboard'))


@main_bp.route('/maintenance', methods=['GET'])
@login_required
def maintenance_list():
    inspector = inspect(db.engine)
    if not inspector.has_table('maintenance_tasks'):
        db.create_all()

    page = max(int(request.args.get('page', 1)), 1)
    status = request.args.get('status') or ''
    category = request.args.get('category') or ''

    query = MaintenanceTask.query.order_by(MaintenanceTask.scheduled_on.asc())
    if status:
        query = query.filter(MaintenanceTask.status == status)
    if category:
        query = query.filter(MaintenanceTask.category == category)

    pagination = query.paginate(page=page, per_page=50, error_out=False)

    return render_template(
        'main/maintenance.html',
        tasks=pagination.items,
        pagination=pagination,
        status=status,
        category=category,
        contracts=Contract.query.filter((Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None))).all(),
        buildings=Building.query.all(),
    )


@main_bp.route('/maintenance', methods=['POST'])
@login_required
def create_maintenance_task():
    inspector = inspect(db.engine)
    if not inspector.has_table('maintenance_tasks'):
        db.create_all()

    try:
        title = request.form.get('title') or 'Wartung'
        category = request.form.get('category') or 'inspection'
        scheduled_raw = request.form.get('scheduled_on')
        scheduled_on = datetime.strptime(scheduled_raw, '%Y-%m-%d').date()
        reminder_days = int(request.form.get('reminder_days_before') or 7)
        task = MaintenanceTask(
            id=str(uuid.uuid4()),
            title=title,
            category=category,
            scheduled_on=scheduled_on,
            reminder_days_before=reminder_days,
            status=request.form.get('status') or 'open',
            notes=request.form.get('notes'),
            contract_id=request.form.get('contract_id') or None,
            building_id=request.form.get('building_id') or None,
            protocol_required=True
        )
        db.session.add(task)
        db.session.commit()
        flash('Wartungstermin gespeichert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Termin konnte nicht gespeichert werden: {exc}', 'danger')

    return redirect(request.referrer or url_for('main.maintenance_list'))


@main_bp.route('/maintenance/<task_id>/update', methods=['POST'])
@login_required
def update_maintenance_task(task_id):
    inspector = inspect(db.engine)
    if not inspector.has_table('maintenance_tasks'):
        db.create_all()

    task = MaintenanceTask.query.get_or_404(task_id)
    try:
        task.title = request.form.get('title') or task.title
        task.category = request.form.get('category') or task.category
        scheduled_raw = request.form.get('scheduled_on')
        if scheduled_raw:
            task.scheduled_on = datetime.strptime(scheduled_raw, '%Y-%m-%d').date()
        task.status = request.form.get('status') or task.status
        task.reminder_days_before = int(request.form.get('reminder_days_before') or task.reminder_days_before or 0)
        task.notes = request.form.get('notes')
        task.contract_id = request.form.get('contract_id') or None
        task.building_id = request.form.get('building_id') or None
        if task.status == 'done' and task.protocol_required:
            task.reminder_sent = True
        db.session.commit()
        flash('Wartungstermin aktualisiert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Aktualisierung fehlgeschlagen: {exc}', 'danger')

    return redirect(request.referrer or url_for('main.maintenance_list'))


@main_bp.route('/maintenance/<task_id>/delete', methods=['POST'])
@login_required
def delete_maintenance_task(task_id):
    inspector = inspect(db.engine)
    if not inspector.has_table('maintenance_tasks'):
        db.create_all()

    task = MaintenanceTask.query.get_or_404(task_id)
    try:
        db.session.delete(task)
        db.session.commit()
        flash('Termin gelöscht.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Löschen fehlgeschlagen: {exc}', 'danger')

    return redirect(request.referrer or url_for('main.maintenance_list'))

@main_bp.route('/login')
def login_page():
    return redirect(url_for('auth.web_login'))

# Apartments Routes


# Meters Routes
@main_bp.route('/meters')
@login_required
def meters_page():
    meters = Meter.query.all()
    return render_template('meters/list.html', meters=meters)

@main_bp.route('/meter-readings/create', methods=['GET', 'POST'])
@login_required
def create_meter_reading_page():
    if request.method == 'POST':
        try:
            reading = MeterReading(
                reading_value=float(request.form['value']),
                reading_date=datetime.strptime(request.form['reading_date'], '%Y-%m-%d').date(),
                notes=request.form.get('notes'),
                meter_id=request.form['meter_id']
            )
            
            db.session.add(reading)
            db.session.commit()
            flash('Zählerstand erfolgreich erfasst!', 'success')
            return redirect(url_for('main.meter_readings_page'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Erfassen des Zählerstands: {str(e)}', 'danger')
    
    apartments = Apartment.query.all()
    meters = Meter.query.all()
    return render_template('meter_readings/create.html', apartments=apartments, meters=meters)

# Documents Routes
@main_bp.route('/documents')
@login_required
def documents_page():
    documents = Document.query.order_by(Document.created_at.desc()).all()
    return render_template('documents/list.html', documents=documents)

@main_bp.route('/documents/upload', methods=['GET', 'POST'])
@login_required
def upload_document_page():
    if request.method == 'POST':
        try:
            if 'file' not in request.files:
                flash('Keine Datei ausgewählt', 'danger')
                return redirect(request.url)
            
            file = request.files['file']
            if file.filename == '':
                flash('Keine Datei ausgewählt', 'danger')
                return redirect(request.url)
            
            # Vereinfachte Datei-Prüfung
            if file and '.' in file.filename:
                # Datei speichern
                import os
                from werkzeug.utils import secure_filename
                
                filename = secure_filename(file.filename)
                unique_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file_path = os.path.join('uploads', 'documents', unique_filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                file.save(file_path)
                
                # Dokument in Datenbank speichern
                document = Document(
                    filename=unique_filename,
                    original_filename=filename,
                    file_type=file.content_type or 'application/octet-stream',
                    file_size=os.path.getsize(file_path),
                    category=request.form['category'],
                    description=request.form.get('description'),
                    apartment_id=request.form.get('apartment_id') or None,
                    tenant_id=request.form.get('tenant_id') or None
                )
                
                db.session.add(document)
                db.session.commit()
                flash('Dokument erfolgreich hochgeladen!', 'success')
                return redirect(url_for('main.documents_page'))
            else:
                flash('Ungültige Datei', 'danger')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Hochladen: {str(e)}', 'danger')
    
    apartments = Apartment.query.all()
    tenants = Tenant.query.all()
    return render_template('documents/upload.html', apartments=apartments, tenants=tenants)

@main_bp.route('/documents/<document_id>/download')
@login_required
def download_document_page(document_id):
    from flask import send_file
    import os
    
    document = Document.query.get_or_404(document_id)
    file_path = os.path.join('uploads', 'documents', document.filename)
    
    if not os.path.exists(file_path):
        flash('Datei nicht gefunden', 'danger')
        return redirect(url_for('main.documents_page'))
    
    return send_file(file_path, as_attachment=True, download_name=document.original_filename)

@main_bp.route('/documents/<document_id>/delete', methods=['POST'])
@login_required
def delete_document_page(document_id):
    import os
    
    document = Document.query.get_or_404(document_id)
    
    try:
        # Datei löschen
        file_path = os.path.join('uploads', 'documents', document.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Datenbank-Eintrag löschen
        db.session.delete(document)
        db.session.commit()
        flash('Dokument erfolgreich gelöscht!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen: {str(e)}', 'danger')
    
    return redirect(url_for('main.documents_page'))

