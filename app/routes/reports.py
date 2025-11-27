from flask import Blueprint, render_template, current_app, flash
from sqlalchemy import inspect
from app.routes.main import login_required
from app.extensions import db
from app.models import Contract, Tenant, Apartment, OperatingCost, Settlement

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
def reports_home():
    """Einfache Auswertungen mit Kennzahlen."""
    stats = {
        'contracts': 0,
        'tenants': 0,
        'apartments': 0,
        'operating_costs': 0,
        'settlements': 0,
    }
    latest_settlements = []

    inspector = inspect(db.engine)

    try:
        if inspector.has_table('contracts'):
            stats['contracts'] = Contract.query.count()
        if inspector.has_table('tenants'):
            stats['tenants'] = Tenant.query.count()
        if inspector.has_table('apartments'):
            stats['apartments'] = Apartment.query.count()
        if inspector.has_table('operating_costs'):
            stats['operating_costs'] = OperatingCost.query.count()
        if inspector.has_table('settlements'):
            stats['settlements'] = Settlement.query.count()
            latest_settlements = Settlement.query.order_by(Settlement.created_at.desc()).limit(5).all()
    except Exception as exc:
        current_app.logger.error('Konnte Reports-Daten nicht laden: %s', exc, exc_info=True)
        flash('Die Auswertungen konnten nicht geladen werden. Bitte versuchen Sie es erneut.', 'danger')

    return render_template('reports/index.html', stats=stats, settlements=latest_settlements)


@reports_bp.route('/profitability')
@login_required
def profitability():
    apartments = Apartment.query.all()
    buildings = {a.building.id: a.building for a in apartments if a.building}
    total_rent = sum((a.rent_net or 0) + (a.rent_additional or 0) for a in apartments)
    total_costs = sum((c.amount_gross or 0) for c in OperatingCost.query.all())
    margin = total_rent - total_costs
    return render_template('reports/profitability.html',
                           apartments=apartments,
                           buildings=buildings,
                           summary={'income': total_rent, 'costs': total_costs, 'margin': margin})
