import os
from datetime import datetime, date

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, current_app, send_file
from flask_jwt_extended import jwt_required
from app.extensions import db
from sqlalchemy import or_, inspect
from app.models import (
    Settlement,
    Apartment,
    Tenant,
    OperatingCost,
    Contract,
    Meter,
    MeterReading,
    Landlord,
    Income,
)
import uuid
from dateutil.relativedelta import relativedelta
from app.routes.main import login_required
from app.utils.pdf_generator import generate_pdf_from_html_weasyprint


def _safe_months_between(start_date, end_date):
    """Ermittelt die Anzahl Monate (mindestens 1) im Zeitraum."""
    if not start_date or not end_date:
        return 1
    if end_date < start_date:
        return 1
    diff = relativedelta(end_date, start_date)
    return max(1, diff.years * 12 + diff.months + 1)


def _contract_snapshot_from(contract, apartment):
    if not contract:
        return None

    return {
        'id': contract.id,
        'contract_number': contract.contract_number,
        'start_date': contract.start_date.isoformat() if contract.start_date else None,
        'end_date': contract.end_date.isoformat() if contract.end_date else None,
        'cold_rent': contract.cold_rent,
        'operating_cost_advance': contract.operating_cost_advance,
        'heating_advance': contract.heating_advance,
        'monthly_advance': contract.get_monthly_operating_prepayment(),
        'floor_space': contract.floor_space or (apartment.area_sqm if apartment else None),
        'apartment_number': apartment.apartment_number if apartment else None,
        'building_name': apartment.building.name if apartment and apartment.building else None,
        'building_address': f"{apartment.building.street} {apartment.building.street_number}, {apartment.building.zip_code} {apartment.building.city}" if apartment and apartment.building else None,
        'tenant_name': f"{contract.tenant.first_name} {contract.tenant.last_name}" if contract.tenant else None,
        'landlord': _serialize_landlord(contract.landlord) if contract.landlord else None,
    }


def _collect_advance_payments(contract, period_start, period_end, months):
    if not contract:
        return 0.0

    try:
        inspector = inspect(db.engine)
        if not inspector.has_table('incomes'):
            raise RuntimeError('no income table')

        advance_incomes = Income.query.filter(
            Income.contract_id == contract.id,
            Income.is_advance_payment.is_(True),
            Income.received_on >= period_start,
            Income.received_on <= period_end,
        ).all()
        total_from_incomes = sum((inc.service_charge_portion or inc.amount or 0) for inc in advance_incomes)
    except Exception:
        total_from_incomes = 0

    if total_from_incomes > 0:
        return round(total_from_incomes, 2)

    return round(contract.get_monthly_operating_prepayment() * months, 2)


def _ensure_settlement_snapshot(settlement):
    if settlement.contract_snapshot:
        return
    snapshot = _contract_snapshot_from(settlement.contract, settlement.apartment)
    if snapshot:
        settlement.contract_snapshot = snapshot
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _default_period_for_contract(contract):
    """Schlägt den abrechnungsrelevanten Jahreszeitraum gemäß Vertrag vor."""
    today = date.today()
    year_start = date(today.year - 1 if today.month < 7 else today.year, 1, 1)
    year_end = date(year_start.year, 12, 31)

    if not contract:
        return year_start, year_end

    start = contract.start_date or contract.contract_start or year_start
    end = contract.end_date or contract.contract_end or year_end

    # Auf den Jahreszeitraum beschränken, aber Auszugs-/Enddatum respektieren
    start = max(start, year_start)
    end = min(end, year_end)
    return start, end


def _get_consumption(meter, start_date, end_date):
    """Berechnet den Verbrauch eines Zählers robust innerhalb des Zeitraums.

    Falls vor dem Startdatum kein Zählerstand vorliegt, wird der erste Stand
    nach Start genutzt. Analog wird für das Enddatum verfahren, um möglichst
    immer einen verwertbaren Verbrauch zu liefern.
    """
    if not meter:
        return None, None, None

    start_reading = (
        MeterReading.query.filter(
            MeterReading.meter_id == meter.id, MeterReading.reading_date <= start_date
        )
        .order_by(MeterReading.reading_date.desc())
        .first()
    )
    if not start_reading:
        start_reading = (
            MeterReading.query.filter(
                MeterReading.meter_id == meter.id, MeterReading.reading_date >= start_date
            )
            .order_by(MeterReading.reading_date.asc())
            .first()
        )

    end_reading = (
        MeterReading.query.filter(
            MeterReading.meter_id == meter.id, MeterReading.reading_date <= end_date
        )
        .order_by(MeterReading.reading_date.desc())
        .first()
    )
    if not end_reading:
        end_reading = (
            MeterReading.query.filter(
                MeterReading.meter_id == meter.id, MeterReading.reading_date >= end_date
            )
            .order_by(MeterReading.reading_date.asc())
            .first()
        )

    if not start_reading or not end_reading:
        return None, start_reading, end_reading

    consumption = (end_reading.reading_value - start_reading.reading_value) * (meter.multiplier or 1)
    if consumption < 0:
        return None, start_reading, end_reading
    return consumption, start_reading, end_reading


def _resolve_upload_root():
    upload_root = current_app.config.get('UPLOAD_ROOT') if current_app else None
    if not upload_root:
        upload_root = os.environ.get('UPLOAD_ROOT')
    if not upload_root:
        upload_root = '/uploads'
    return os.path.abspath(upload_root)


def _serialize_landlord(landlord: Landlord):
    if not landlord:
        return None
    return {
        'id': landlord.id,
        'company_name': landlord.company_name,
        'company': landlord.company_name,
        'first_name': landlord.first_name,
        'last_name': landlord.last_name,
        'name': f"{landlord.first_name or ''} {landlord.last_name or ''}".strip(),
        'street': landlord.street,
        'street_number': landlord.street_number,
        'zip_code': landlord.zip_code,
        'city': landlord.city,
        'email': landlord.email,
        'phone': landlord.phone,
        'iban': landlord.iban,
        'bic': landlord.bic,
        'bank_name': landlord.bank_name,
        'account_holder': landlord.account_holder,
    }


def _determine_active_contract(apartment_id, period_start, period_end):
    return (
        Contract.query.filter(
            Contract.apartment_id == apartment_id,
            Contract.start_date <= period_end,
            (Contract.end_date == None) | (Contract.end_date >= period_start),
            Contract.status.in_(['active', 'approved', 'draft']),
        )
        .order_by(Contract.start_date.desc())
        .first()
    )


def _collect_building_area(apartment):
    building = apartment.building
    if not building:
        return 0.0
    return sum((apt.area_sqm or 0.0) for apt in building.apartments)


def _calculate_cost_share(cost, apartment, contract, meter_consumptions, total_area, apartment_area, period_start, period_end):
    category_name = cost.cost_category.name if cost.cost_category else (cost.description or 'Sonstige Kosten')
    method = cost.distribution_method or (
        cost.cost_category.default_distribution_method if cost.cost_category else 'by_area'
    )
    gross_amount = cost.amount_gross if cost.amount_gross is not None else (cost.amount_net or 0.0)
    amount = gross_amount
    method = method or 'by_area'

    note_parts = []

    # Zeitraum anteilig berücksichtigen
    period_factor = 1.0
    if cost.billing_period_start and cost.billing_period_end:
        overlap_start = max(cost.billing_period_start, period_start)
        overlap_end = min(cost.billing_period_end, period_end)
        overlap_days = (overlap_end - overlap_start).days + 1 if overlap_end >= overlap_start else 0
        full_days = (cost.billing_period_end - cost.billing_period_start).days + 1
        if full_days > 0 and overlap_days > 0:
            period_factor = overlap_days / full_days
            note_parts.append(f"Anteiliger Zeitraum: {overlap_days} / {full_days} Tage")
        else:
            period_factor = 0.0

    amount = amount * period_factor

    # Mehrjahresverteilung und Auf-/Abschlag berücksichtigen
    spread_years = cost.spread_years or 1
    if spread_years > 1:
        amount = amount / spread_years
        note_parts.append(f"Verteilung auf {spread_years} Jahre")

    if cost.distribution_factor not in (None, 0):
        amount = amount * (1 + cost.distribution_factor / 100.0)
        note_parts.append(f"Auf-/Abschlag {cost.distribution_factor:.1f}%")

    amount_total = amount
    tenant_percent = cost.allocation_percent if cost.allocation_percent not in (None, 0) else None

    share_base = 0.0
    basis = ''
    tenant_consumption = None
    total_consumption = None
    unit = None

    if method == 'by_area':
        if total_area and apartment_area:
            fraction = apartment_area / total_area
            share_base = amount_total * fraction
            basis = f"Wohnfläche {apartment_area:.2f} m² / {total_area:.2f} m² ({fraction:.2%})"
        else:
            note_parts.append('Keine Flächendaten vorhanden')
    elif method in ['by_units', 'by_apartments', 'by_unit']:
        total_units = len(apartment.building.apartments) if apartment.building else 0
        if total_units:
            share_base = amount_total / total_units
            basis = f"1 von {total_units} Einheiten"
        else:
            note_parts.append('Keine Einheiten für Umlage vorhanden')
    elif method in ['by_usage', 'by_meter']:
        meter_type_id = cost.meter.meter_type_id if cost.meter else None
        relevant_consumptions = [
            (m, data)
            for m, data in meter_consumptions.items()
            if (meter_type_id is None or m.meter_type_id == meter_type_id)
        ]
        total_consumption = sum(data['consumption'] for _, data in relevant_consumptions if data['consumption'] is not None)
        tenant_consumption = sum(
            data['consumption']
            for m, data in relevant_consumptions
            if m.apartment_id == apartment.id and data['consumption'] is not None
        )
        if cost.meter and cost.meter.meter_type:
            unit = cost.meter.meter_type.unit
        elif relevant_consumptions:
            m0 = relevant_consumptions[0][0]
            unit = m0.meter_type.unit if m0.meter_type else 'Einheiten'
        else:
            unit = 'Einheiten'

        if total_consumption > 0:
            fraction = tenant_consumption / total_consumption
            share_base = amount_total * fraction
            basis = f"Verbrauch {tenant_consumption:.2f} / {total_consumption:.2f} {unit}"
        elif total_area and apartment_area:
            # Fallback auf Flächenverteilung
            fraction = apartment_area / total_area
            share_base = amount_total * fraction
            basis = f"Fallback Fläche {apartment_area:.2f} m² / {total_area:.2f} m²"
            note_parts.append('Kein Verbrauch ermittelbar, Flächenumlage verwendet')
        else:
            note_parts.append('Weder Verbrauch noch Fläche für Umlage verfügbar')
    else:
        if total_area and apartment_area:
            fraction = apartment_area / total_area
            share_base = amount_total * fraction
            basis = f"Standard Fläche {apartment_area:.2f} m² / {total_area:.2f} m²"
        else:
            note_parts.append('Standardverteilung nicht möglich (keine Fläche)')

    share = share_base
    if tenant_percent is not None:
        share = gross_amount * (tenant_percent / 100.0)
        basis = basis or f"{tenant_percent:.1f}% von Gesamtkosten"
        note_parts.append(f"Mieteranteil {tenant_percent:.1f}% der Gesamtkosten")

    max_share = max(0.0, gross_amount)
    if share > max_share:
        share = max_share
    if share < 0:
        share = 0.0

    return {
        'cost_id': cost.id,
        'cost_description': cost.description,
        'billing_period': f"{cost.billing_period_start} – {cost.billing_period_end}" if cost.billing_period_start or cost.billing_period_end else '',
        'invoice_number': cost.invoice_number or cost.vendor_invoice_number,
        'apartment_specific': bool(cost.apartment_id),
        'category': category_name,
        'method': method,
        'amount_total': round(gross_amount, 2),
        'adjusted_amount': round(amount_total, 2),
        'period_factor': round(period_factor, 4),
        'allocation_percent': cost.allocation_percent,
        'share': round(share, 2),
        'basis': basis,
        'note': '; '.join([p for p in note_parts if p]),
        'tenant_consumption': tenant_consumption,
        'total_consumption': total_consumption,
        'unit': unit,
    }


def _calculate_settlement(apartment_id, period_start, period_end):
    apartment = Apartment.query.get(apartment_id)
    if not apartment:
        raise ValueError('Wohnung nicht gefunden')

    contract = _determine_active_contract(apartment_id, period_start, period_end)
    if not contract:
        raise ValueError('Kein aktiver Vertrag gefunden')

    tenant = contract.tenant or Tenant.query.filter_by(apartment_id=apartment_id, move_out_date=None).first()
    if not tenant:
        raise ValueError('Kein aktiver Mieter gefunden')

    apartment_area = contract.floor_space or apartment.area_sqm or 0.0
    total_area = _collect_building_area(apartment)

    months = _safe_months_between(period_start, period_end)
    advances = _collect_advance_payments(contract, period_start, period_end, months)

    raw_costs = OperatingCost.query.filter(
        OperatingCost.building_id == apartment.building_id,
        or_(OperatingCost.apartment_id == None, OperatingCost.apartment_id == apartment.id),
        or_(OperatingCost.billing_period_start == None, OperatingCost.billing_period_start <= period_end),
        or_(OperatingCost.billing_period_end == None, OperatingCost.billing_period_end >= period_start),
        or_(OperatingCost.is_archived == False, OperatingCost.is_archived == None),
    ).all()

    costs = []
    for cost in raw_costs:
        # Kosten außerhalb des Abrechnungszeitraums werden ignoriert
        if cost.billing_period_start and cost.billing_period_start > period_end:
            continue
        if cost.billing_period_end and cost.billing_period_end < period_start:
            continue
        if not cost.billing_period_start and not cost.billing_period_end:
            if cost.invoice_date and (cost.invoice_date < period_start or cost.invoice_date > period_end):
                continue
        costs.append(cost)

    # Zählerverbräuche vorbereiten
    meters = Meter.query.filter_by(building_id=apartment.building_id).all()
    meter_consumptions = {}
    for meter in meters:
        consumption, start_read, end_read = _get_consumption(meter, period_start, period_end)
        price_per_unit = meter.price_per_unit if meter.price_per_unit not in (None, '') else None
        tenant_share = None
        if consumption is not None and price_per_unit is not None:
            tenant_share = round(consumption * price_per_unit, 2)
        meter_consumptions[meter] = {
            'consumption': consumption,
            'start': start_read.reading_value if start_read else None,
            'start_date': start_read.reading_date.isoformat() if start_read else None,
            'end': end_read.reading_value if end_read else None,
            'end_date': end_read.reading_date.isoformat() if end_read else None,
            'unit': meter.meter_type.unit if meter.meter_type else '',
            'price_per_unit': price_per_unit,
            'tenant_share': tenant_share,
        }

    breakdown = []
    for cost in costs:
        breakdown.append(
            _calculate_cost_share(
                cost=cost,
                apartment=apartment,
                contract=contract,
                meter_consumptions=meter_consumptions,
                total_area=total_area,
                apartment_area=apartment_area,
                period_start=period_start,
                period_end=period_end,
            )
        )

    total_share = sum(item['share'] for item in breakdown)
    balance = round(total_share - advances, 2)

    landlord_addr = _serialize_landlord(contract.landlord) if contract and contract.landlord else None

    contract_snapshot = _contract_snapshot_from(contract, apartment)
    if contract_snapshot:
        contract_snapshot['tenant_name'] = f"{tenant.first_name} {tenant.last_name}"
        contract_snapshot['landlord'] = landlord_addr

    settlement = Settlement(
        id=str(uuid.uuid4()),
        apartment_id=apartment_id,
        tenant_id=tenant.id,
        contract_id=contract.id,
        settlement_year=period_end.year,
        period_start=period_start,
        period_end=period_end,
        total_costs=round(total_share, 2),
        total_amount=round(total_share, 2),
        advance_payments=round(advances, 2),
        balance=balance,
        status='calculated',
        notes='Automatisch berechnete Nebenkostenabrechnung gemäß BetrKV.',
        tenant_notes=None,
        cost_breakdown=breakdown,
        consumption_details=[
            {
                'meter_number': meter.meter_number,
                'meter_type': meter.meter_type.name if meter.meter_type else '',
                'unit': data['unit'],
                'apartment_id': meter.apartment_id,
                'apartment_number': meter.apartment.apartment_number if meter.apartment else None,
                'consumption': data['consumption'],
                'start_value': data['start'],
                'start_date': data['start_date'],
                'end_value': data['end'],
                'end_date': data['end_date'],
                'price_per_unit': data.get('price_per_unit'),
                'tenant_share': data.get('tenant_share'),
            }
            for meter, data in meter_consumptions.items()
        ],
        total_area=total_area,
        apartment_area=apartment_area,
        contract_snapshot=contract_snapshot,
    )

    return settlement, apartment, tenant, contract


def _generate_settlement_pdf(settlement, apartment, tenant, contract):
    """Erzeugt und speichert das PDF der Nebenkostenabrechnung."""
    _ensure_settlement_snapshot(settlement)
    if not contract:
        contract = settlement.contract
    building = apartment.building if apartment else None
    landlord = None
    if contract and contract.landlord:
        landlord = _serialize_landlord(contract.landlord)
    else:
        landlord = _serialize_landlord(Landlord.query.filter_by(is_active=True).first())

    html = render_template(
        'settlements/pdf.html',
        settlement=settlement,
        apartment=apartment,
        tenant=tenant,
        contract=contract,
        building=building,
        landlord=landlord,
        generated_at=datetime.utcnow().date(),
    )

    upload_root = _resolve_upload_root()
    upload_dir = os.path.join(upload_root, 'settlements')
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"settlement_{settlement.settlement_year}_{settlement.id}.pdf"
    output_path = os.path.join(upload_dir, filename)

    if generate_pdf_from_html_weasyprint(html, output_path):
        settlement.pdf_path = os.path.relpath(output_path, upload_root)
        return output_path

    raise RuntimeError('PDF konnte nicht erzeugt werden')

settlements_bp = Blueprint('settlements', __name__)


@settlements_bp.route('/settlements')
@login_required
def settlements_list():
    settlements = (
        Settlement.query.filter(
            (Settlement.is_archived == False) | (Settlement.is_archived.is_(None))
        )
        .order_by(Settlement.period_end.desc())
        .all()
    )
    return render_template('settlements/list.html', settlements=settlements)


@settlements_bp.route('/settlements/calculate', methods=['GET', 'POST'])
@login_required
def calculate_settlement():
    apartments = Apartment.query.all()
    selected_apartment_id = request.args.get('apartment_id') or (apartments[0].id if apartments else None)
    selected_apartment = Apartment.query.get(selected_apartment_id) if selected_apartment_id else None
    active_contract = None
    default_start = None
    default_end = None
    preview = None

    building_area = 0
    requested_start = request.args.get('period_start')
    requested_end = request.args.get('period_end')

    if selected_apartment:
        active_contract = _determine_active_contract(selected_apartment.id, date.today(), date.today())
        default_start, default_end = _default_period_for_contract(active_contract)
        building_area = _collect_building_area(selected_apartment)

        # Falls der Nutzer den Zeitraum vorgibt, diese Werte verwenden
        if requested_start and requested_end:
            try:
                default_start = datetime.strptime(requested_start, '%Y-%m-%d').date()
                default_end = datetime.strptime(requested_end, '%Y-%m-%d').date()
            except ValueError:
                flash('Datumsformat ungültig, Vorschlag aus Vertrag verwendet.', 'warning')

        try:
            preview, _, _, _ = _calculate_settlement(selected_apartment.id, default_start, default_end)
        except Exception as preview_exc:
            preview = None
            flash(f'Keine Vorschau möglich: {preview_exc}', 'warning')

    if request.method == 'POST':
        try:
            apartment_id = request.form['apartment_id']
            period_start = datetime.strptime(request.form['period_start'], '%Y-%m-%d').date()
            period_end = datetime.strptime(request.form['period_end'], '%Y-%m-%d').date()

            if period_end < period_start:
                flash('Das Ende des Abrechnungszeitraums muss nach dem Start liegen.', 'danger')
                return redirect(request.url)

            settlement, apartment, tenant, contract = _calculate_settlement(apartment_id, period_start, period_end)
            settlement.tenant_notes = request.form.get('tenant_notes', '').strip() or None

            db.session.add(settlement)
            db.session.commit()

            try:
                _generate_settlement_pdf(settlement, apartment, tenant, contract)
                db.session.commit()
            except Exception as pdf_exc:
                current_app.logger.exception("PDF-Erstellung fehlgeschlagen", exc_info=pdf_exc)
                flash(f'Abrechnung gespeichert, PDF-Generierung fehlgeschlagen: {pdf_exc}', 'warning')

            flash('Abrechnung erfolgreich erstellt!', 'success')
            return redirect(url_for('settlements.settlement_detail', settlement_id=settlement.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Erstellen der Abrechnung: {str(e)}', 'danger')

    return render_template(
        'settlements/calculate.html',
        apartments=apartments,
        selected_apartment=selected_apartment,
        contract=active_contract,
        preview=preview,
        default_start=default_start,
        default_end=default_end,
        building_area=building_area,
    )

@settlements_bp.route('/settlements/<settlement_id>')
@login_required
def settlement_detail(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    _ensure_settlement_snapshot(settlement)

    return render_template('settlements/detail.html', settlement=settlement)


@settlements_bp.route('/settlements/<settlement_id>/edit', methods=['GET', 'POST'])
@login_required
def settlement_edit(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    apartments = Apartment.query.all()

    if request.method == 'POST':
        try:
            apartment_id = request.form['apartment_id']
            period_start = datetime.strptime(request.form['period_start'], '%Y-%m-%d').date()
            period_end = datetime.strptime(request.form['period_end'], '%Y-%m-%d').date()

            if period_end < period_start:
                flash('Das Ende des Abrechnungszeitraums muss nach dem Start liegen.', 'danger')
                return redirect(request.url)

            recalculated, apartment, tenant, contract = _calculate_settlement(apartment_id, period_start, period_end)

            # vorhandenen Datensatz aktualisieren
            settlement.apartment_id = recalculated.apartment_id
            settlement.tenant_id = recalculated.tenant_id
            settlement.contract_id = recalculated.contract_id
            settlement.settlement_year = recalculated.settlement_year
            settlement.period_start = recalculated.period_start
            settlement.period_end = recalculated.period_end
            settlement.total_costs = recalculated.total_costs
            settlement.total_amount = recalculated.total_amount
            settlement.advance_payments = recalculated.advance_payments
            settlement.balance = recalculated.balance
            settlement.cost_breakdown = recalculated.cost_breakdown
            settlement.consumption_details = recalculated.consumption_details
            settlement.total_area = recalculated.total_area
            settlement.apartment_area = recalculated.apartment_area
            settlement.contract_snapshot = recalculated.contract_snapshot
            settlement.status = request.form.get('status', settlement.status)
            settlement.notes = request.form.get('notes', '').strip()
            settlement.tenant_notes = request.form.get('tenant_notes', '').strip() or None

            db.session.commit()

            try:
                _generate_settlement_pdf(settlement, apartment, tenant, contract)
                db.session.commit()
            except Exception as pdf_exc:
                current_app.logger.exception("PDF-Erstellung fehlgeschlagen", exc_info=pdf_exc)
                flash(f'Abrechnung aktualisiert, PDF-Generierung fehlgeschlagen: {pdf_exc}', 'warning')

            flash('Abrechnung erfolgreich aktualisiert.', 'success')
            return redirect(url_for('settlements.settlement_detail', settlement_id=settlement.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren der Abrechnung: {str(e)}', 'danger')

    return render_template('settlements/edit.html', settlement=settlement, apartments=apartments)


@settlements_bp.route('/settlements/<settlement_id>/archive', methods=['POST'])
@login_required
def settlement_archive(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    action = request.form.get('action', 'archive')
    settlement.is_archived = action != 'restore'
    if action == 'archive':
        settlement.status = settlement.status or 'draft'
    db.session.commit()
    flash('Abrechnung archiviert.' if settlement.is_archived else 'Abrechnung reaktiviert.', 'success')
    return redirect(url_for('settlements.settlement_detail', settlement_id=settlement.id))

@settlements_bp.route('/settlements/<settlement_id>/pdf')
@login_required
def download_settlement_pdf(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    apartment = settlement.apartment
    contract = settlement.contract
    if not contract and apartment:
        contract = _determine_active_contract(
            apartment.id, settlement.period_start, settlement.period_end
        )
    tenant = settlement.tenant

    if not settlement.pdf_path:
        try:
            _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()
        except Exception as pdf_exc:
            current_app.logger.exception("PDF-Erstellung fehlgeschlagen", exc_info=pdf_exc)
            flash(f'PDF konnte nicht erzeugt werden: {pdf_exc}', 'danger')
            return redirect(url_for('settlements.settlement_detail', settlement_id=settlement_id))

    upload_root = _resolve_upload_root()
    pdf_path = settlement.pdf_path if os.path.isabs(settlement.pdf_path) else os.path.join(upload_root, settlement.pdf_path)

    if not os.path.exists(pdf_path):
        try:
            pdf_path = _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()
        except Exception as pdf_exc:
            current_app.logger.exception("PDF-Erstellung fehlgeschlagen", exc_info=pdf_exc)
            flash('PDF konnte nicht gefunden oder erzeugt werden.', 'danger')
            return redirect(url_for('settlements.settlement_detail', settlement_id=settlement_id))

    return send_file(pdf_path, as_attachment=True, download_name=os.path.basename(pdf_path))

# API Routes
@settlements_bp.route('/api/settlements/calculate', methods=['POST'])
@jwt_required()
def calculate_settlement_api():
    data = request.get_json()
    try:
        period_start = datetime.strptime(data['period_start'], '%Y-%m-%d').date()
        period_end = datetime.strptime(data['period_end'], '%Y-%m-%d').date()
        settlement, apartment, tenant, contract = _calculate_settlement(data['apartment_id'], period_start, period_end)

        settlement.tenant_notes = (data.get('tenant_notes') or '').strip() or None

        db.session.add(settlement)
        db.session.commit()

        try:
            _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()
        except Exception as pdf_exc:
            current_app.logger.exception("PDF-Erstellung fehlgeschlagen", exc_info=pdf_exc)
            return jsonify({'error': f'Abrechnung gespeichert, PDF-Generierung fehlgeschlagen: {pdf_exc}'}), 500

        return jsonify({
            'message': 'Abrechnung erfolgreich erstellt',
            'id': settlement.id,
            'settlement': settlement.to_dict(),
        }), 201
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400

@settlements_bp.route('/api/settlements/<settlement_id>', methods=['GET'])
@jwt_required()
def get_settlement_api(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    return jsonify(settlement.to_dict())

@settlements_bp.route('/api/settlements/<settlement_id>/pdf', methods=['GET'])
@jwt_required()
def get_settlement_pdf_api(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    apartment = settlement.apartment
    contract = settlement.contract
    if not contract and apartment:
        contract = _determine_active_contract(
            apartment.id, settlement.period_start, settlement.period_end
        )
    tenant = settlement.tenant

    if not settlement.pdf_path:
        _generate_settlement_pdf(settlement, apartment, tenant, contract)
        db.session.commit()

    upload_root = _resolve_upload_root()
    pdf_path = settlement.pdf_path if os.path.isabs(settlement.pdf_path) else os.path.join(upload_root, settlement.pdf_path)
    if not os.path.exists(pdf_path):
        try:
            pdf_path = _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()
        except Exception:
            return jsonify({'error': 'PDF konnte nicht erzeugt werden'}), 500

    return send_file(pdf_path, as_attachment=True, download_name=os.path.basename(pdf_path))
