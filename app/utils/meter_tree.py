"""Hilfsfunktionen für hierarchische Zählerbäume und Sortierreihenfolgen."""
from typing import Optional

from sqlalchemy import or_

from app.extensions import db
from app.models import Meter


def _meter_query(include_archived: bool = False):
    query = Meter.query.options(
        db.joinedload(Meter.building),
        db.joinedload(Meter.meter_type),
        db.joinedload(Meter.apartment),
        db.joinedload(Meter.sub_meters),
    ).order_by(Meter.sort_order.asc(), Meter.meter_number.asc())

    if not include_archived:
        query = query.filter(
            or_(
                Meter.is_archived.is_(False),
                Meter.is_archived.is_(None),
                Meter.is_archived == 0,
                Meter.is_archived == '0',
                Meter.is_archived == 'false',
                Meter.is_archived == 'False',
            )
        )
    return query


def load_meter_tree(include_archived: bool = False):
    """Lädt alle Zähler frisch aus der DB und baut eine Baumstruktur pro Gebäude."""
    db.session.expire_all()  # immer frische Daten
    meters = _meter_query(include_archived).all()

    meter_map = {m.id: m for m in meters}
    children_map = {m_id: [] for m_id in meter_map.keys()}
    roots_by_building = {}

    for meter in meter_map.values():
        if meter.parent_meter_id and meter.parent_meter_id in meter_map:
            children_map[meter.parent_meter_id].append(meter)
        else:
            roots_by_building.setdefault(meter.building_id, []).append(meter)

    def attach_children(current_meter):
        current_meter._children = sorted(
            children_map.get(current_meter.id, []),
            key=lambda m: (m.sort_order or 0, m.meter_number or ''),
        )
        for child in current_meter._children:
            attach_children(child)

    for building_id, building_roots in roots_by_building.items():
        roots_by_building[building_id] = sorted(
            building_roots, key=lambda m: (m.sort_order or 0, m.meter_number or '')
        )
        for root in roots_by_building[building_id]:
            attach_children(root)

    buildings = {m.building_id: m.building for m in meter_map.values() if m.building}
    return roots_by_building, buildings


def next_sort_order(building_id: str, parent_id: Optional[str] = None) -> int:
    """Berechnet die nächste sort_order für einen neuen Zähler."""
    query = Meter.query.filter_by(building_id=building_id)
    if parent_id:
        query = query.filter_by(parent_meter_id=parent_id)
    else:
        query = query.filter(Meter.parent_meter_id.is_(None))

    max_order = query.with_entities(db.func.max(Meter.sort_order)).scalar()
    return int(max_order or 0) + 1
