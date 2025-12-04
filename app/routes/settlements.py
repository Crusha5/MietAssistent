import os
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, current_app, send_file
from flask_jwt_extended import jwt_required
from app.extensions import db
from sqlalchemy import or_
from app.models import (
    Settlement,
    Apartment,
    Tenant,
    OperatingCost,
    Contract,
    Meter,
    MeterReading,
    Landlord,
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


def _get_consumption(meter, start_date, end_date):
    """Berechnet den Verbrauch eines Zählers im Zeitraum anhand der letzten Stände vor Start/Ende."""
    if not meter:
        return None, None, None

    start_reading = (
        MeterReading.query.filter(
            MeterReading.meter_id == meter.id, MeterReading.reading_date <= start_date
        )
        .order_by(MeterReading.reading_date.desc())
        .first()
    )
    end_reading = (
        MeterReading.query.filter(
            MeterReading.meter_id == meter.id, MeterReading.reading_date <= end_date
        )
        .order_by(MeterReading.reading_date.desc())
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


def _calculate_cost_share(cost, apartment, meter_consumptions, total_area, apartment_area):
    category_name = cost.cost_category.name if cost.cost_category else (cost.description or 'Sonstige Kosten')
    method = cost.distribution_method or (
        cost.cost_category.default_distribution_method if cost.cost_category else 'by_area'
    )
    amount = cost.amount_gross if cost.amount_gross is not None else (cost.amount_net or 0.0)
    method = method or 'by_area'

    share = 0.0
    basis = ''
    note = ''

    if method == 'by_area':
        if total_area and apartment_area:
            fraction = apartment_area / total_area
            share = amount * fraction
            basis = f"Wohnfläche {apartment_area:.2f} m² / {total_area:.2f} m² ({fraction:.2%})"
        else:
            note = 'Keine Flächendaten vorhanden'
    elif method in ['by_units', 'by_apartments', 'by_unit']:
        total_units = len(apartment.building.apartments) if apartment.building else 0
        if total_units:
            share = amount / total_units
            basis = f"1 von {total_units} Einheiten"
        else:
            note = 'Keine Einheiten für Umlage vorhanden'
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

        if total_consumption > 0:
            fraction = tenant_consumption / total_consumption
            share = amount * fraction
            unit = cost.meter.meter_type.unit if cost.meter and cost.meter.meter_type else 'Einheiten'
            basis = f"Verbrauch {tenant_consumption:.2f} / {total_consumption:.2f} {unit}"
        elif total_area and apartment_area:
            # Fallback auf Flächenverteilung
            fraction = apartment_area / total_area
            share = amount * fraction
            basis = f"Fallback Fläche {apartment_area:.2f} m² / {total_area:.2f} m²"
            note = 'Kein Verbrauch ermittelbar, Flächenumlage verwendet'
        else:
            note = 'Weder Verbrauch noch Fläche für Umlage verfügbar'
    else:
        if total_area and apartment_area:
            fraction = apartment_area / total_area
            share = amount * fraction
            basis = f"Standard Fläche {apartment_area:.2f} m² / {total_area:.2f} m²"
        else:
            note = 'Standardverteilung nicht möglich (keine Fläche)'

    return {
        'cost_id': cost.id,
        'cost_description': cost.description,
        'billing_period': f"{cost.billing_period_start} – {cost.billing_period_end}" if cost.billing_period_start or cost.billing_period_end else '',
        'invoice_number': cost.invoice_number or cost.vendor_invoice_number,
        'apartment_specific': bool(cost.apartment_id),
        'category': category_name,
        'method': method,
        'amount_total': round(amount, 2),
        'share': round(share, 2),
        'basis': basis,
        'note': note,
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
    advances = contract.get_monthly_operating_prepayment() * months

    costs = OperatingCost.query.filter(
        OperatingCost.building_id == apartment.building_id,
        or_(OperatingCost.apartment_id == None, OperatingCost.apartment_id == apartment.id),
        or_(OperatingCost.billing_period_start == None, OperatingCost.billing_period_start <= period_end),
        or_(OperatingCost.billing_period_end == None, OperatingCost.billing_period_end >= period_start),
        or_(OperatingCost.is_archived == False, OperatingCost.is_archived == None),
    ).all()

    # Zählerverbräuche vorbereiten
    meters = Meter.query.filter_by(building_id=apartment.building_id).all()
    meter_consumptions = {}
    for meter in meters:
        consumption, start_read, end_read = _get_consumption(meter, period_start, period_end)
        meter_consumptions[meter] = {
            'consumption': consumption,
            'start': start_read.reading_value if start_read else None,
            'start_date': start_read.reading_date.isoformat() if start_read else None,
            'end': end_read.reading_value if end_read else None,
            'end_date': end_read.reading_date.isoformat() if end_read else None,
            'unit': meter.meter_type.unit if meter.meter_type else '',
        }

    breakdown = []
    for cost in costs:
        breakdown.append(
            _calculate_cost_share(
                cost=cost,
                apartment=apartment,
                meter_consumptions=meter_consumptions,
                total_area=total_area,
                apartment_area=apartment_area,
            )
        )

    total_share = sum(item['share'] for item in breakdown)
    balance = round(total_share - advances, 2)

    contract_snapshot = {
        'id': contract.id,
        'contract_number': contract.contract_number,
        'start_date': contract.start_date.isoformat() if contract.start_date else None,
        'end_date': contract.end_date.isoformat() if contract.end_date else None,
        'cold_rent': contract.cold_rent,
        'operating_cost_advance': contract.operating_cost_advance,
        'heating_advance': contract.heating_advance,
        'floor_space': contract.floor_space or apartment.area_sqm,
        'apartment_number': apartment.apartment_number,
        'building_name': apartment.building.name if apartment.building else None,
        'building_address': f"{apartment.building.street} {apartment.building.street_number}, {apartment.building.zip_code} {apartment.building.city}" if apartment.building else None,
        'tenant_name': f"{tenant.first_name} {tenant.last_name}",
        'landlord_name': f"{contract.landlord.first_name} {contract.landlord.last_name}" if contract.landlord else None,
    }

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
    if not contract:
        contract = settlement.contract
    building = apartment.building if apartment else None
    landlord = None
    if contract and contract.landlord:
        landlord = contract.landlord
    else:
        landlord = Landlord.query.filter_by(is_active=True).first()

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
    settlements = Settlement.query.order_by(Settlement.period_end.desc()).all()
    return render_template('settlements/list.html', settlements=settlements)


@settlements_bp.route('/settlements/calculate', methods=['GET', 'POST'])
@login_required
def calculate_settlement():
    apartments = Apartment.query.all()

    if request.method == 'POST':
        try:
            apartment_id = request.form['apartment_id']
            period_start = datetime.strptime(request.form['period_start'], '%Y-%m-%d').date()
            period_end = datetime.strptime(request.form['period_end'], '%Y-%m-%d').date()

            if period_end < period_start:
                flash('Das Ende des Abrechnungszeitraums muss nach dem Start liegen.', 'danger')
                return redirect(request.url)

            settlement, apartment, tenant, contract = _calculate_settlement(apartment_id, period_start, period_end)

            db.session.add(settlement)
            db.session.commit()

            _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()

            flash('Abrechnung erfolgreich erstellt!', 'success')
            return redirect(url_for('settlements.settlement_detail', settlement_id=settlement.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Erstellen der Abrechnung: {str(e)}', 'danger')

    return render_template('settlements/calculate.html', apartments=apartments)

@settlements_bp.route('/settlements/<settlement_id>')
@login_required
def settlement_detail(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    return render_template('settlements/detail.html', settlement=settlement)

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
        _generate_settlement_pdf(settlement, apartment, tenant, contract)
        db.session.commit()

    upload_root = _resolve_upload_root()
    pdf_path = settlement.pdf_path if os.path.isabs(settlement.pdf_path) else os.path.join(upload_root, settlement.pdf_path)

    if not os.path.exists(pdf_path):
        try:
            pdf_path = _generate_settlement_pdf(settlement, apartment, tenant, contract)
            db.session.commit()
        except Exception:
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

        db.session.add(settlement)
        db.session.commit()

        _generate_settlement_pdf(settlement, apartment, tenant, contract)
        db.session.commit()

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
