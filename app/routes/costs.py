from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.routes.main import login_required
from app.extensions import db
from sqlalchemy import inspect, text
from app.models import OperatingCost, CostCategory, Building, Apartment
import uuid
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from app.routes.contracts import ensure_writable_dir

costs_bp = Blueprint('costs', __name__, url_prefix='/costs')


def _ensure_cost_columns(inspector):
    columns = [col['name'] for col in inspector.get_columns('operating_costs')]
    if 'until_consumed' not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE operating_costs ADD COLUMN until_consumed BOOLEAN DEFAULT 0"))
    if 'is_archived' not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE operating_costs ADD COLUMN is_archived BOOLEAN DEFAULT 0"))
    if 'vendor_invoice_number' not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE operating_costs ADD COLUMN vendor_invoice_number VARCHAR(120)"))
    if 'apartment_id' not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE operating_costs ADD COLUMN apartment_id VARCHAR(36)"))


def _parse_cost_form(form, existing_cost=None, document_path=None):
    def parse_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    net_val = parse_float(form.get('amount_net'))
    tax_val = parse_float(form.get('tax_rate'))
    gross_val = parse_float(form.get('amount_gross'))

    start_date_raw = form.get('billing_period_start')
    if not start_date_raw:
        raise ValueError('Bitte ein Abrechnungsbeginndatum angeben')

    end_date_val = form.get('billing_period_end')
    invoice_date_raw = form.get('invoice_date')
    until_consumed = bool(form.get('until_consumed'))

    target = existing_cost or OperatingCost(id=str(uuid.uuid4()))
    target.building_id = form.get('building_id')
    target.apartment_id = form.get('apartment_id') or None
    target.cost_category_id = form.get('cost_category_id')
    target.description = form.get('description')
    target.amount_net = net_val
    target.tax_rate = tax_val
    target.amount_gross = gross_val if gross_val else net_val * (1 + tax_val / 100)
    target.billing_period_start = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
    target.billing_period_end = datetime.strptime(end_date_val, '%Y-%m-%d').date() if end_date_val else None
    target.invoice_date = datetime.strptime(invoice_date_raw, '%Y-%m-%d').date() if invoice_date_raw else None
    target.invoice_number = form.get('invoice_number')
    target.vendor_invoice_number = form.get('vendor_invoice_number')
    target.system_invoice_number = form.get('system_invoice_number') or target.system_invoice_number or f"SYS-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:6]}"
    target.distribution_method = form.get('distribution_method') or 'manual'
    target.allocation_percent = parse_float(form.get('allocation_percent'), 0)
    target.until_consumed = until_consumed
    if document_path is not None:
        target.document_path = document_path
    return target


def _handle_invoice_upload(file_storage, existing_path=None):
    document = file_storage.get('invoice_document') if file_storage else None
    if not document or not document.filename:
        return existing_path

    upload_root = current_app.config.get('UPLOAD_ROOT') or '/uploads'
    ensure_writable_dir(upload_root)
    cost_dir = os.path.join(upload_root, 'costs')
    ensure_writable_dir(cost_dir)

    safe_name = secure_filename(document.filename)
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    target_path = os.path.join(cost_dir, unique_name)
    document.save(target_path)
    return os.path.join('costs', unique_name)


@costs_bp.route('/', methods=['GET', 'POST'])
@login_required
def costs_home():
    """Kostenübersicht und Verwaltung von Betriebskosten."""
    inspector = inspect(db.engine)
    buildings = []
    categories = []
    costs = []
    apartments = []

    try:
        if inspector.has_table('buildings'):
            buildings = Building.query.all()
        if inspector.has_table('cost_categories'):
            categories = CostCategory.query.order_by(CostCategory.sort_order).all()
        if inspector.has_table('operating_costs'):
            _ensure_cost_columns(inspector)
            costs = OperatingCost.query.order_by(OperatingCost.billing_period_start.desc()).all()
        if inspector.has_table('apartments'):
            apartments = Apartment.query.order_by(Apartment.apartment_number).all()
    except Exception as exc:
        current_app.logger.error('Kostenübersicht konnte nicht geladen werden: %s', exc, exc_info=True)
        flash('Kostenübersicht konnte nicht geladen werden. Bitte versuchen Sie es erneut.', 'danger')

    if request.method == 'POST':
        try:
            document_path = _handle_invoice_upload(request.files)
            cost = _parse_cost_form(request.form, document_path=document_path)
            db.session.add(cost)
            db.session.commit()
            flash('Kostenposition gespeichert.', 'success')
            return redirect(url_for('costs.costs_home'))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('Kosten konnten nicht gespeichert werden: %s', exc, exc_info=True)
            flash(f'Kosten konnten nicht gespeichert werden: {exc}', 'danger')

    default_number = f"SYS-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    return render_template(
        'costs/list.html',
        costs=costs,
        buildings=buildings,
        apartments=apartments,
        categories=categories,
        default_system_number=default_number
    )


@costs_bp.route('/categories', methods=['POST'])
@login_required
def add_category():
    try:
        category = CostCategory(
            id=str(uuid.uuid4()),
            name=request.form['name'],
            description=request.form.get('description'),
            sort_order=CostCategory.query.count()
        )
        db.session.add(category)
        db.session.commit()
        flash('Kategorie gespeichert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Kategorie konnte nicht gespeichert werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/categories/<category_id>', methods=['POST'])
@login_required
def update_category(category_id):
    category = CostCategory.query.get_or_404(category_id)
    try:
        category.name = request.form['name']
        category.description = request.form.get('description')
        category.is_active = request.form.get('is_active') == 'on'
        db.session.commit()
        flash('Kategorie aktualisiert.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Kategorie konnte nicht aktualisiert werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/categories/<category_id>/delete', methods=['POST'])
@login_required
def delete_category(category_id):
    category = CostCategory.query.get_or_404(category_id)
    try:
        db.session.delete(category)
        db.session.commit()
        flash('Kategorie gelöscht.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Kategorie konnte nicht gelöscht werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/<cost_id>/update', methods=['POST'])
@login_required
def update_cost(cost_id):
    cost = OperatingCost.query.get_or_404(cost_id)
    try:
        document_path = _handle_invoice_upload(request.files, cost.document_path)
        _parse_cost_form(request.form, cost, document_path)
        db.session.commit()
        flash('Kostenposition aktualisiert.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Kosten konnten nicht aktualisiert werden: %s', exc, exc_info=True)
        flash(f'Kosten konnten nicht aktualisiert werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/<cost_id>/archive', methods=['POST'])
@login_required
def archive_cost(cost_id):
    cost = OperatingCost.query.get_or_404(cost_id)
    try:
        cost.is_archived = True
        db.session.commit()
        flash('Kostenposition archiviert.', 'info')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Kosten konnten nicht archiviert werden: %s', exc, exc_info=True)
        flash(f'Kosten konnten nicht archiviert werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/<cost_id>/restore', methods=['POST'])
@login_required
def restore_cost(cost_id):
    cost = OperatingCost.query.get_or_404(cost_id)
    try:
        cost.is_archived = False
        db.session.commit()
        flash('Kostenposition wiederhergestellt.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Kosten konnten nicht wiederhergestellt werden: %s', exc, exc_info=True)
        flash(f'Kosten konnten nicht wiederhergestellt werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))


@costs_bp.route('/<cost_id>/delete', methods=['POST'])
@login_required
def delete_cost(cost_id):
    cost = OperatingCost.query.get_or_404(cost_id)
    try:
        db.session.delete(cost)
        db.session.commit()
        flash('Kostenposition gelöscht.', 'warning')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Kosten konnten nicht gelöscht werden: %s', exc, exc_info=True)
        flash(f'Kosten konnten nicht gelöscht werden: {exc}', 'danger')
    return redirect(url_for('costs.costs_home'))
