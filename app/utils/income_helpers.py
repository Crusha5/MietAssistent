from typing import Optional

from app.models import Contract, Tenant


def parse_amount(value) -> float:
    """Konvertiert unterschiedliche Betragsformate in float."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    normalized = text.replace('€', '').replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def allocate_income_components(
    total_amount: Optional[float] = None,
    rent_portion: Optional[float] = None,
    service_charge_portion: Optional[float] = None,
    special_portion: Optional[float] = None,
    contract: Optional[Contract] = None,
):
    """
    Teilt Zahlungen in Bestandteile auf. Ist nichts angegeben, wird anhand des Vertrags verteilt.
    Gibt (rent, service_charge, special, total) zurück.
    """
    rent = parse_amount(rent_portion)
    service = parse_amount(service_charge_portion)
    special = parse_amount(special_portion)

    provided_components = any(val for val in [rent, service, special])
    total = parse_amount(total_amount)

    if provided_components and not total:
        total = rent + service + special

    if not provided_components:
        if contract:
            expected_rent = parse_amount(contract.rent_net or contract.cold_rent)
            expected_service = parse_amount(contract.rent_additional) + parse_amount(contract.operating_cost_advance) + parse_amount(contract.heating_advance)
            rent = min(total, expected_rent) if expected_rent else total
            remaining = total - rent
            service = min(remaining, expected_service)
            special = max(remaining - service, 0)
        else:
            rent = total
            service = 0.0
            special = 0.0

    total = total if total else rent + service + special
    return round(rent, 2), round(service, 2), round(special, 2), round(total, 2)


def pick_contract_for_tenant(tenant: Optional[Tenant]):
    if not tenant:
        return None
    contract = (
        Contract.query.filter(Contract.tenant_id == tenant.id)
        .filter((Contract.is_archived.is_(False)) | (Contract.is_archived.is_(None)))
        .order_by(Contract.start_date.desc())
        .first()
    )
    return contract
