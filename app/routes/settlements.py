from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from flask_jwt_extended import jwt_required
from app.extensions import db
from app.models import Settlement, Apartment, Tenant, OperatingCost, Contract
from datetime import datetime
import uuid
from dateutil.relativedelta import relativedelta
from app.routes.main import login_required

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

            apartment = Apartment.query.get(apartment_id)
            tenant = Tenant.query.filter_by(apartment_id=apartment_id, move_out_date=None).first()
            active_contract = Contract.query.filter_by(apartment_id=apartment_id, status='active').order_by(Contract.start_date.desc()).first()

            if not apartment or not tenant or not active_contract:
                flash('Wohnung, aktiver Mieter oder Vertrag fehlt.', 'danger')
                return redirect(request.url)

            # Vorschüsse aus dem Vertrag ermitteln
            months = max(1, relativedelta(period_end, period_start).months + relativedelta(period_end, period_start).years * 12 + 1)
            advance_payments = (active_contract.rent_additional or 0) * months

            # Umlagefähige Kosten sammeln
            costs = OperatingCost.query.filter(
                OperatingCost.building_id == apartment.building_id,
                OperatingCost.billing_period_start <= period_end,
                OperatingCost.billing_period_end >= period_start
            ).all()
            total_costs = sum((c.amount_gross or c.amount_net or 0) for c in costs)

            balance = round(total_costs - advance_payments, 2)

            settlement = Settlement(
                id=str(uuid.uuid4()),
                apartment_id=apartment_id,
                tenant_id=tenant.id,
                settlement_year=period_end.year,
                period_start=period_start,
                period_end=period_end,
                total_costs=total_costs,
                advance_payments=advance_payments,
                balance=balance,
                status='calculated',
                notes='Automatisch berechnete Nebenkostenabrechnung basierend auf Vertrag und Betriebskosten.'
            )

            db.session.add(settlement)
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
    # Hier würde die PDF-Generierung implementiert werden
    flash('PDF-Generierung wird in Kürze verfügbar sein', 'info')
    return redirect(url_for('settlements.settlement_detail', settlement_id=settlement_id))

# API Routes
@settlements_bp.route('/settlements/calculate', methods=['POST'])
@jwt_required()
def calculate_settlement_api():
    data = request.get_json()
    
    # Vereinfachte Berechnung (wie oben)
    apartment = Apartment.query.get(data['apartment_id'])
    tenant = Tenant.query.filter_by(apartment_id=data['apartment_id'], move_out_date=None).first()
    
    if not tenant:
        return jsonify({'error': 'No active tenant found'}), 400
    
    settlement = Settlement(
        period_start=datetime.strptime(data['period_start'], '%Y-%m-%d').date(),
        period_end=datetime.strptime(data['period_end'], '%Y-%m-%d').date(),
        total_rent=tenant.rent * 12,
        additional_costs=apartment.additional_costs * 12,
        total_amount=(tenant.rent + apartment.additional_costs) * 12,
        apartment_id=data['apartment_id'],
        tenant_id=tenant.id
    )
    
    db.session.add(settlement)
    db.session.commit()
    
    return jsonify({
        'message': 'Abrechnung erfolgreich erstellt',
        'id': settlement.id,
        'settlement': settlement.to_dict()
    }), 201

@settlements_bp.route('/settlements/<settlement_id>', methods=['GET'])
@jwt_required()
def get_settlement_api(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    return jsonify(settlement.to_dict())

@settlements_bp.route('/settlements/<settlement_id>/pdf', methods=['GET'])
@jwt_required()
def get_settlement_pdf_api(settlement_id):
    settlement = Settlement.query.get_or_404(settlement_id)
    # PDF-Generierung würde hier implementiert werden
    return jsonify({'message': 'PDF generation not yet implemented'})