import io
import re
import uuid
from datetime import date, datetime

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, inspect
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader

from app.extensions import db
from app.models import Contract, Income, Tenant
from app.routes.main import login_required, _contract_options
from app.utils.income_helpers import allocate_income_components, parse_amount, pick_contract_for_tenant

finances_bp = Blueprint('finances', __name__)


@finances_bp.route('/finances/incomes')
@login_required
def incomes_overview():
    inspector = inspect(db.engine)
    if not inspector.has_table('incomes'):
        db.create_all()

    page = max(int(request.args.get('page', 1)), 1)
    tenant_filter = request.args.get('tenant_id') or ''
    contract_filter = request.args.get('contract_id') or ''
    search = (request.args.get('q') or '').strip()

    query = Income.query.join(Contract)
    if tenant_filter:
        query = query.filter(Income.tenant_id == tenant_filter)
    if contract_filter:
        query = query.filter(Income.contract_id == contract_filter)
    if search:
        like = f"%{search}%"
        query = query.filter((Income.reference.ilike(like)) | (Income.notes.ilike(like)))

    totals = query.with_entities(
        func.coalesce(func.sum(Income.amount), 0),
        func.coalesce(func.sum(Income.rent_portion), 0),
        func.coalesce(func.sum(Income.service_charge_portion), 0),
        func.coalesce(func.sum(Income.special_portion), 0),
    ).first()

    pagination = query.order_by(Income.received_on.desc()).paginate(page=page, per_page=40, error_out=False)

    contracts = Contract.query.filter((Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None))).all()
    tenants = Tenant.query.all()

    contract_options = _contract_options(contracts)

    return render_template(
        'finance/incomes.html',
        incomes=pagination.items,
        pagination=pagination,
        tenants=tenants,
        contracts=contracts,
        contract_options=contract_options,
        totals={
            'amount': totals[0] if totals else 0,
            'rent': totals[1] if totals else 0,
            'service': totals[2] if totals else 0,
            'special': totals[3] if totals else 0,
        },
        filters={'tenant_id': tenant_filter, 'contract_id': contract_filter, 'q': search},
    )


def _match_tenant_by_text(text_value: str, tenants):
    content = (text_value or '').lower()
    for tenant in tenants:
        first = (tenant.first_name or '').lower()
        last = (tenant.last_name or '').lower()
        if first and last and first in content and last in content:
            return tenant
    return None


def _parse_csv_transactions(file_bytes: bytes):
    df = pd.read_csv(io.BytesIO(file_bytes), sep=None, engine='python')
    normalized_cols = {col.lower(): col for col in df.columns}

    def pick_column(candidates):
        for name in candidates:
            if name in normalized_cols:
                return normalized_cols[name]
        return None

    amount_col = pick_column(['betrag', 'amount', 'value', 'summe'])
    date_col = pick_column(['buchungstag', 'datum', 'date'])
    text_col = pick_column(['verwendungszweck', 'purpose', 'text', 'beschreibung', 'descr'])

    if not amount_col:
        raise ValueError('CSV enthält keine Betrags-Spalte (z.B. Betrag oder Amount).')

    transactions = []
    for _, row in df.iterrows():
        amt = parse_amount(row.get(amount_col))
        if amt <= 0:
            continue
        booking_date = None
        if date_col and row.get(date_col):
            try:
                booking_date = pd.to_datetime(row.get(date_col)).date()
            except Exception:
                booking_date = date.today()
        purpose = str(row.get(text_col)) if text_col else ''
        transactions.append({
            'amount': amt,
            'date': booking_date or date.today(),
            'reference': purpose,
            'raw': row.to_dict(),
        })
    return transactions


def _parse_pdf_transactions(file_bytes: bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join([page.extract_text() or '' for page in reader.pages])
    pattern = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4}).{0,50}?(?P<amount>[+-]?[0-9.,]+)")
    transactions = []
    for match in pattern.finditer(text):
        amt = parse_amount(match.group('amount'))
        if amt <= 0:
            continue
        try:
            booking_date = datetime.strptime(match.group('date'), '%d.%m.%Y').date()
        except Exception:
            booking_date = date.today()
        context_start = max(match.start() - 40, 0)
        context_end = min(match.end() + 40, len(text))
        context = text[context_start:context_end]
        transactions.append({
            'amount': amt,
            'date': booking_date,
            'reference': context.strip(),
            'raw': context,
            'is_advance': 'voraus' in context.lower(),
        })
    return transactions


def _persist_income_entry(txn, tenants, default_contract_id=None, mark_advance=False):
    tenant = _match_tenant_by_text(txn.get('reference'), tenants)
    contract = pick_contract_for_tenant(tenant)
    if not contract and default_contract_id:
        contract = Contract.query.get(default_contract_id)

    if not contract:
        return None

    rent, service_charge, special, amount = allocate_income_components(
        total_amount=txn.get('amount'),
        contract=contract,
    )
    income = Income(
        id=str(uuid.uuid4()),
        contract_id=contract.id,
        tenant_id=tenant.id if tenant else contract.tenant_id,
        income_type='rent',
        amount=amount,
        rent_portion=rent,
        service_charge_portion=service_charge,
        special_portion=special,
        is_advance_payment=mark_advance or txn.get('is_advance', False),
        reference=txn.get('reference'),
        source=txn.get('source', 'import'),
        import_metadata=str(txn.get('raw')),
        received_on=txn.get('date') or date.today(),
        notes=txn.get('notes') or '',
    )
    db.session.add(income)
    return income


@finances_bp.route('/finances/incomes/import', methods=['POST'])
@login_required
def import_incomes():
    file = request.files.get('statement_file')
    if not file or not file.filename:
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(request.referrer or url_for('finances.incomes_overview'))

    filename = secure_filename(file.filename)
    file_bytes = file.read()
    tenants = Tenant.query.all()
    default_contract_id = request.form.get('fallback_contract_id') or None
    mark_advance = bool(request.form.get('mark_as_advance'))

    ext = filename.lower().split('.')[-1]
    try:
        if ext == 'csv':
            transactions = _parse_csv_transactions(file_bytes)
        elif ext == 'pdf':
            transactions = _parse_pdf_transactions(file_bytes)
        else:
            flash('Bitte CSV- oder PDF-Dateien hochladen.', 'danger')
            return redirect(request.referrer or url_for('finances.incomes_overview'))
    except Exception as exc:
        flash(f'Import fehlgeschlagen: {exc}', 'danger')
        return redirect(request.referrer or url_for('finances.incomes_overview'))

    created = 0
    unmatched = 0
    for txn in transactions:
        txn['source'] = f'import:{ext}'
        income = _persist_income_entry(txn, tenants, default_contract_id, mark_advance)
        if income:
            created += 1
        else:
            unmatched += 1

    try:
        db.session.commit()
        flash(f'{created} Zahlungen importiert. {unmatched} Einträge ohne Vertrag wurden übersprungen.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Import konnte nicht gespeichert werden: {exc}', 'danger')

    return redirect(url_for('finances.incomes_overview'))


@finances_bp.route('/finances/incomes', methods=['POST'])
@login_required
def create_income():
    contract = Contract.query.get(request.form.get('contract_id'))
    if not contract:
        flash('Bitte Vertrag auswählen.', 'danger')
        return redirect(request.referrer or url_for('finances.incomes_overview'))

    category = request.form.get('income_category') or 'rent'
    amount = float(request.form.get('amount') or 0)
    if amount <= 0:
        flash('Betrag muss größer 0 sein.', 'danger')
        return redirect(request.referrer or url_for('finances.incomes_overview'))

    rent = service_charge = special = 0.0
    income_type = 'rent'
    if category == 'service':
        service_charge = amount
        income_type = 'service_charge'
    elif category == 'special':
        special = amount
        income_type = 'extra'
    elif category == 'deposit':
        special = amount
        income_type = 'deposit'
    else:
        rent = amount

    income_date_raw = request.form.get('received_on')
    income_date = datetime.strptime(income_date_raw, '%Y-%m-%d').date() if income_date_raw else date.today()

    income = Income(
        id=str(uuid.uuid4()),
        contract_id=contract.id,
        tenant_id=request.form.get('tenant_id') or contract.tenant_id,
        income_type=income_type,
        amount=amount,
        rent_portion=rent,
        service_charge_portion=service_charge,
        special_portion=special,
        is_advance_payment=bool(request.form.get('is_advance_payment')),
        reference=request.form.get('reference'),
        source=request.form.get('source') or 'manuell',
        received_on=income_date,
        notes=request.form.get('notes'),
    )
    db.session.add(income)
    db.session.commit()
    flash('Einnahme gespeichert.', 'success')
    return redirect(url_for('finances.incomes_overview'))


@finances_bp.route('/finances/incomes/<income_id>/update', methods=['POST'])
@login_required
def update_income(income_id):
    income = Income.query.get_or_404(income_id)
    contract = Contract.query.get(request.form.get('contract_id')) or income.contract

    category = request.form.get('income_category') or request.form.get('income_type') or 'rent'
    amount = float(request.form.get('amount') or 0)
    rent = service_charge = special = 0.0
    income_type = income.income_type or 'rent'
    if category == 'service' or category == 'service_charge':
        service_charge = amount
        income_type = 'service_charge'
    elif category == 'special' or category == 'extra':
        special = amount
        income_type = 'extra'
    elif category == 'deposit':
        special = amount
        income_type = 'deposit'
    else:
        rent = amount
        income_type = 'rent'

    income.amount = amount
    income.rent_portion = rent
    income.service_charge_portion = service_charge
    income.special_portion = special
    income.is_advance_payment = bool(request.form.get('is_advance_payment'))
    income.reference = request.form.get('reference')
    income.source = request.form.get('source') or income.source
    income.income_type = income_type
    income.received_on = datetime.strptime(request.form.get('received_on'), '%Y-%m-%d').date()
    income.notes = request.form.get('notes')
    income.contract_id = contract.id if contract else income.contract_id
    income.tenant_id = request.form.get('tenant_id') or (contract.tenant_id if contract else income.tenant_id)

    db.session.commit()
    flash('Einnahme aktualisiert.', 'success')
    return redirect(request.referrer or url_for('finances.incomes_overview'))


@finances_bp.route('/finances/incomes/<income_id>/delete', methods=['POST'])
@login_required
def delete_income_entry(income_id):
    income = Income.query.get_or_404(income_id)
    try:
        db.session.delete(income)
        db.session.commit()
        flash('Eintrag gelöscht.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Löschen fehlgeschlagen: {exc}', 'danger')
    return redirect(request.referrer or url_for('finances.incomes_overview'))
