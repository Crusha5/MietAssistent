from app.extensions import db  # Statt: from app import db
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from flask import url_for
import json

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='manager')  # admin, manager, tenant
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    is_landlord = db.Column(db.Boolean, default=False)
    landlord_id = db.Column(db.String(36), db.ForeignKey('landlords.id'))
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    landlord = db.relationship('Landlord', backref=db.backref('users', lazy=True))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, unique=True)
    preferences = db.Column(db.Text, default=json.dumps({}))

    user = db.relationship('User', backref=db.backref('preferences', uselist=False))

class Building(db.Model):
    __tablename__ = 'buildings'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    street = db.Column(db.String(100))
    street_number = db.Column(db.String(10))
    zip_code = db.Column(db.String(10))
    city = db.Column(db.String(50))
    country = db.Column(db.String(50), default='Deutschland')
    year_built = db.Column(db.Integer)
    total_area_sqm = db.Column(db.Float)
    energy_efficiency_class = db.Column(db.String(2))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - NUR HIER backref definieren
    apartments = db.relationship('Apartment', backref='building', lazy=True, cascade='all, delete-orphan')
    meters = db.relationship('Meter', backref='building', lazy=True, cascade='all, delete-orphan')
    operating_costs = db.relationship('OperatingCost', backref='building', lazy=True, cascade='all, delete-orphan')

class Apartment(db.Model):
    __tablename__ = 'apartments'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id = db.Column(db.String(36), db.ForeignKey('buildings.id'), nullable=False)
    apartment_number = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.String(10))
    area_sqm = db.Column(db.Float)
    room_count = db.Column(db.Integer)
    # ENTFERNEN: building = db.relationship('Building', backref=db.backref('apartments', lazy=True))
    
    # Erweiterte Felder für verschiedene Einheitentypen
    unit_type = db.Column(db.String(20), default='wohnung')  # wohnung, gewerbe, garage, keller, lager, abstellraum
    has_balcony = db.Column(db.Boolean, default=False)
    has_terrace = db.Column(db.Boolean, default=False)
    has_garage = db.Column(db.Boolean, default=False)
    
    # Mietdaten
    rent_net = db.Column(db.Float)
    rent_additional = db.Column(db.Float)
    deposit = db.Column(db.Float)
    rent_start_date = db.Column(db.Date)
    rent_end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='vacant')  # vacant, occupied, reserved, maintenance
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - Hier KEINE backref zu Building mehr
    tenants = db.relationship('Tenant', back_populates='apartment', lazy=True, cascade='all, delete-orphan')
    meters = db.relationship('Meter', backref='apartment', lazy=True, cascade='all, delete-orphan')
    settlements = db.relationship('Settlement', back_populates='apartment', lazy=True, cascade='all, delete-orphan')
    cost_distributions = db.relationship('CostDistribution', backref='apartment', lazy=True, cascade='all, delete-orphan')
    
    def get_full_identifier(self):
        """Gibt einen vollständigen Identifikator für die Einheit zurück"""
        base = f"{self.building.name} - {self.apartment_number}"
        if self.unit_type != 'wohnung':
            type_names = {
                'wohnung': 'Wohnung',
                'gewerbe': 'Gewerbe',
                'garage': 'Garage',
                'keller': 'Keller',
                'kellerraum': 'Kellerraum',
                'lager': 'Lager',
                'abstellraum': 'Abstellraum',
                'terrasse': 'Terrasse',
                'balkon': 'Balkon',
                'garten': 'Garten',
                'dachboden': 'Dachboden',
                'technikraum': 'Technikraum',
                'waschkueche': 'Waschküche',
                'gemeinschaftsraum': 'Gemeinschaftsraum'
            }
            base = f"{base} ({type_names.get(self.unit_type, self.unit_type)})"
        return base
    
    def get_parent_apartment(self):
        """Findet die übergeordnete Wohnung für Nebeneinheiten"""
        if self.unit_type in ['garage', 'keller', 'kellerraum', 'abstellraum', 'balkon', 'terrasse']:
            # Suche nach einer Wohnung im selben Gebäude mit ähnlicher Nummer
            main_apartment = Apartment.query.filter(
                Apartment.building_id == self.building_id,
                Apartment.unit_type == 'wohnung',
                Apartment.apartment_number == self.apartment_number.split('-')[0]  # Nimmt den Basis-Teil
            ).first()
            return main_apartment
        return None
    
    def update_occupancy_status(self):
            """Aktualisiert den Status der Wohnung basierend auf aktiven Mietern"""
            active_tenants = [tenant for tenant in self.tenants if tenant.status == 'active']
            if active_tenants:
                self.status = 'occupied'
            else:
                self.status = 'vacant'
            db.session.commit()
            return self.status

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'))
    
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)
    move_in_date = db.Column(db.Date, nullable=False)
    move_out_date = db.Column(db.Date)
    is_primary_tenant = db.Column(db.Boolean, default=True)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))

    # NEU: Status-Feld für Mieter
    status = db.Column(db.String(20), default='active')  # active, moved_out
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - KORRIGIERT: Keine direkte Beziehung zu MeterReading mehr
    apartment = db.relationship('Apartment', back_populates='tenants')
    settlements = db.relationship('Settlement', back_populates='tenant', lazy=True, cascade='all, delete-orphan')

    def move_out(self, move_out_date=None):
        """Markiert Mieter als ausgezogen und aktualisiert Wohnungsstatus"""
        self.move_out_date = move_out_date or datetime.utcnow().date()
        self.status = 'moved_out'
        db.session.commit()
        
        # Wohnungsstatus aktualisieren
        if self.apartment:
            self.apartment.update_occupancy_status()

    def reactivate(self, move_in_date=None):
        """Reaktiviert einen Mieter"""
        self.move_out_date = None
        self.status = 'active'
        if move_in_date:
            self.move_in_date = move_in_date
        db.session.commit()
        
        # Wohnungsstatus aktualisieren
        if self.apartment:
            self.apartment.update_occupancy_status()
   
    # Revision für Mieter --> logt alle vorgänge
    def create_audit_log(self, user_id, action, field_changed=None, old_value=None, new_value=None, description=None, request=None):
        """Erstellt einen Audit-Log Eintrag für diesen Mieter"""
        from flask import request as flask_request
        
        audit_log = TenantAuditLog(
            id=str(uuid.uuid4()),
            tenant_id=self.id,
            user_id=user_id,
            action=action,
            field_changed=field_changed,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            description=description,
            ip_address=flask_request.remote_addr if flask_request else None,
            user_agent=flask_request.headers.get('User-Agent') if flask_request else None
        )
        
        db.session.add(audit_log)
        return audit_log
    
    def log_creation(self, user_id, request=None):
        """Protokolliert die Erstellung des Mieters"""
        return self.create_audit_log(
            user_id=user_id,
            action='created',
            description=f'Mieter {self.first_name} {self.last_name} angelegt',
            request=request
        )
    
    def log_move_out(self, user_id, request=None):
        """Protokolliert den Auszug"""
        return self.create_audit_log(
            user_id=user_id,
            action='moved_out',
            description=f'Auszug erfasst am {datetime.utcnow().strftime("%d.%m.%Y")}',
            request=request
        )
    
    def log_reactivation(self, user_id, request=None):
        """Protokolliert die Reaktivierung"""
        return self.create_audit_log(
            user_id=user_id,
            action='reactivated',
            description='Mieter reaktiviert',
            request=request
        )
    
    def log_field_change(self, user_id, field_name, old_value, new_value, request=None):
        """Protokolliert die Änderung eines Feldes"""
        field_display_names = {
            'first_name': 'Vorname',
            'last_name': 'Nachname',
            'email': 'E-Mail',
            'phone': 'Telefon',
            'date_of_birth': 'Geburtsdatum',
            'move_in_date': 'Einzugsdatum',
            'move_out_date': 'Auszugsdatum',
            'apartment_id': 'Wohnung',
            'is_primary_tenant': 'Hauptmieter Status',
            'emergency_contact_name': 'Notfallkontakt Name',
            'emergency_contact_phone': 'Notfallkontakt Telefon',
            'status': 'Status'
        }
        
        display_name = field_display_names.get(field_name, field_name)
        
        return self.create_audit_log(
            user_id=user_id,
            action='updated',
            field_changed=display_name,
            old_value=old_value,
            new_value=new_value,
            description=f'{display_name} geändert',
            request=request
        )

class MeterType(db.Model):
    __tablename__ = 'meter_types'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(20))  # electricity, water, gas, heating, renewable, special
    unit = db.Column(db.String(10))
    decimal_places = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    meters = db.relationship('Meter', backref='meter_type', lazy=True, cascade='all, delete-orphan')

class Meter(db.Model):
    __tablename__ = 'meters'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id = db.Column(db.String(36), db.ForeignKey('buildings.id'), nullable=False)
    # ENTFERNEN: building = db.relationship('Building', backref=db.backref('meters', lazy=True))
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'))
    # ENTFERNEN: apartment = db.relationship('Apartment', backref=db.backref('meters', lazy=True))
    parent_meter_id = db.Column(db.String(36), db.ForeignKey('meters.id'))
    meter_type_id = db.Column(db.String(36), db.ForeignKey('meter_types.id'), nullable=False)
    
    meter_number = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    manufacturer = db.Column(db.String(100))
    model = db.Column(db.String(100))
    installation_date = db.Column(db.Date)
    last_calibration = db.Column(db.Date)
    next_calibration = db.Column(db.Date)
    
    # Zählerkonfiguration
    is_main_meter = db.Column(db.Boolean, default=False)
    is_virtual_meter = db.Column(db.Boolean, default=False)
    multiplier = db.Column(db.Float, default=1.0)
    location_description = db.Column(db.String(255))
    notes = db.Column(db.Text)
    price_per_unit = db.Column(db.Float)
    is_archived = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - NUR EINE parent_meter Beziehung
    parent_meter = db.relationship('Meter', remote_side=[id], backref=db.backref('sub_meters', lazy=True))
    readings = db.relationship('MeterReading', backref='meter', lazy=True, cascade='all, delete-orphan')
    # Bidirektionale Verknüpfung zu Betriebskosten ohne doppelte Backref-Namen
    operating_costs = db.relationship(
        'OperatingCost',
        back_populates='meter',
        lazy=True,
        cascade='all, delete-orphan'
    )

class MeterReading(db.Model):
    __tablename__ = 'meter_readings'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meter_id = db.Column(db.String(36), db.ForeignKey('meters.id'), nullable=False)
    reading_value = db.Column(db.Float, nullable=False)
    reading_date = db.Column(db.Date, nullable=False)
    reading_type = db.Column(db.String(20), default='actual')  # actual, estimated, correction
    photo_path = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    is_manual_entry = db.Column(db.Boolean, default=True)
    
    # NEU: Felder für Korrekturen
    correction_of_id = db.Column(db.String(36), db.ForeignKey('meter_readings.id'), nullable=True)
    correction_reason = db.Column(db.Text)  # Grund der Korrektur
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[created_by], backref='created_meter_readings')
    
    # NEU: Beziehung für Korrekturen
    correction_of = db.relationship('MeterReading',
                                   remote_side=[id],
                                   backref=db.backref('corrections', lazy=True),
                                   foreign_keys=[correction_of_id])

    is_archived = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<MeterReading {self.reading_value} {self.reading_date}>'

class OperatingCost(db.Model):
    __tablename__ = 'operating_costs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id = db.Column(db.String(36), db.ForeignKey('buildings.id'), nullable=False)
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'))
    meter_id = db.Column(db.String(36), db.ForeignKey('meters.id'))
    cost_category_id = db.Column(db.String(36), db.ForeignKey('cost_categories.id'))
    
    description = db.Column(db.String(255))
    amount_net = db.Column(db.Float)
    tax_rate = db.Column(db.Float, default=19.0)
    amount_gross = db.Column(db.Float)
    billing_period_start = db.Column(db.Date)
    billing_period_end = db.Column(db.Date)
    invoice_date = db.Column(db.Date)
    invoice_number = db.Column(db.String(100))
    vendor_invoice_number = db.Column(db.String(120))
    system_invoice_number = db.Column(db.String(120), unique=True)
    document_path = db.Column(db.String(255))
    distribution_method = db.Column(db.String(20))  # by_meter, by_area, by_units, by_usage, manual
    is_distributed = db.Column(db.Boolean, default=False)
    allocation_percent = db.Column(db.Float, default=0.0)
    # Anteilige Verteilung über mehrere Jahre sowie optionaler Auf-/Abschlag
    spread_years = db.Column(db.Integer, default=1)
    distribution_factor = db.Column(db.Float, default=0.0)
    until_consumed = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    cost_category = db.relationship('CostCategory', backref='operating_costs')
    distributions = db.relationship('CostDistribution', backref='operating_cost', lazy=True, cascade='all, delete-orphan')
    apartment = db.relationship('Apartment', backref=db.backref('operating_costs', lazy=True))
    meter = db.relationship('Meter', back_populates='operating_costs')

class CostCategory(db.Model):
    __tablename__ = 'cost_categories'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    default_distribution_method = db.Column(db.String(20))  # by_meter, by_area, by_units, by_usage
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

class CostDistribution(db.Model):
    __tablename__ = 'cost_distributions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operating_cost_id = db.Column(db.String(36), db.ForeignKey('operating_costs.id'), nullable=False)
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'), nullable=False)
    meter_id = db.Column(db.String(36), db.ForeignKey('meters.id'))
    
    distributed_amount = db.Column(db.Float)
    distribution_type = db.Column(db.String(50))
    calculation_basis = db.Column(db.Float)
    calculation_note = db.Column(db.String(255))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Settlement(db.Model):
    __tablename__ = 'settlements'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'), nullable=False)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'))
    
    settlement_year = db.Column(db.Integer, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    total_costs = db.Column(db.Float)
    advance_payments = db.Column(db.Float)
    balance = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='draft')  # draft, calculated, approved, sent, paid, disputed
    pdf_path = db.Column(db.String(255))
    sent_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    tenant_notes = db.Column(db.Text)
    cost_breakdown = db.Column(db.JSON)
    consumption_details = db.Column(db.JSON)
    total_area = db.Column(db.Float)
    apartment_area = db.Column(db.Float)
    contract_snapshot = db.Column(db.JSON)
    created_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    is_archived = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='settlements')
    apartment = db.relationship('Apartment', back_populates='settlements')
    tenant = db.relationship('Tenant', back_populates='settlements')
    contract = db.relationship('Contract', backref='settlements')

    def to_dict(self):
        return {
            'id': self.id,
            'apartment_id': self.apartment_id,
            'tenant_id': self.tenant_id,
            'settlement_year': self.settlement_year,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'total_costs': self.total_costs,
            'advance_payments': self.advance_payments,
            'balance': self.balance,
            'total_amount': self.total_amount,
            'status': self.status,
            'pdf_path': self.pdf_path,
            'notes': self.notes,
            'tenant_notes': self.tenant_notes,
            'cost_breakdown': self.cost_breakdown,
            'consumption_details': self.consumption_details,
            'total_area': self.total_area,
            'apartment_area': self.apartment_area,
            'contract_id': self.contract_id,
            'contract_snapshot': self.contract_snapshot,
            'is_archived': self.is_archived,
        }

class Document(db.Model):
    __tablename__ = 'documents'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    documentable_type = db.Column(db.String(50))  # building, apartment, tenant, meter, settlement
    documentable_id = db.Column(db.String(36))
    document_type = db.Column(db.String(20))  # contract, meter_reading, invoice, settlement, photo, other
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    description = db.Column(db.Text)
    uploaded_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    is_archived = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='documents')

    def get_download_url(self):
        return url_for('documents.download_document', document_id=self.id)
    
# Revision für Mieter --> Logt alle änderungen von der erstellung an.
class TenantAuditLog(db.Model):
    __tablename__ = 'tenant_audit_logs'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    
    # Änderungsinformationen
    action = db.Column(db.String(50), nullable=False)  # created, updated, moved_out, reactivated, deleted
    field_changed = db.Column(db.String(100))  # Welches Feld wurde geändert
    old_value = db.Column(db.Text)  # Alter Wert
    new_value = db.Column(db.Text)  # Neuer Wert
    description = db.Column(db.Text)  # Beschreibung der Änderung
    
    ip_address = db.Column(db.String(45))  # IP-Adresse des Users
    user_agent = db.Column(db.Text)  # Browser-Informationen
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('Tenant', backref=db.backref('audit_logs', lazy=True, order_by='TenantAuditLog.created_at.desc()'))
    user = db.relationship('User', backref='tenant_audit_logs')
    
    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'field_changed': self.field_changed,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'user_name': f"{self.user.first_name} {self.user.last_name}" if self.user else 'Unbekannt',
            'ip_address': self.ip_address
        }


REVISION_TABLE_LABELS = {
    'tenants': 'Mieter',
    'users': 'Benutzer',
    'contracts': 'Mietvertrag',
    'apartments': 'Wohnung',
    'buildings': 'Gebäude',
    'protocols': 'Protokoll',
    'landlords': 'Vermieter',
    'meters': 'Zähler',
    'meter_readings': 'Zählerstand',
    'settlements': 'Abrechnung',
    'operating_costs': 'Betriebskosten',
}


def get_revision_table_label(table_name: str) -> str:
    """Gibt eine deutschsprachige Bezeichnung für den Tabellennamen zurück."""
    if not table_name:
        return 'Eintrag'
    return REVISION_TABLE_LABELS.get(table_name, table_name.replace('_', ' ').title())


class RevisionLog(db.Model):
    __tablename__ = 'revision_logs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    table_name = db.Column(db.String(80), nullable=False)
    record_id = db.Column(db.String(64))
    action = db.Column(db.String(20), nullable=False)  # insert, update, delete
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'))
    changes = db.Column(db.Text)  # JSON Snapshot / Delta
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='revision_logs')

    def as_dict(self):
        return {
            'id': self.id,
            'table_name': self.table_name,
            'record_id': self.record_id,
            'action': self.action,
            'user': f"{self.user.first_name} {self.user.last_name}" if self.user else 'System',
            'changes': self.changes,
            'created_at': self.created_at.isoformat(),
            'ip_address': self.ip_address,
        }

    @property
    def parsed_changes(self):
        """Gibt die gespeicherten Änderungen als Dictionary zurück."""
        try:
            return json.loads(self.changes or "{}")
        except Exception:
            return {'raw': self.changes or ''}

    @property
    def human_changes(self):
        """Bereitet Änderungen menschenlesbar auf."""
        data = self.parsed_changes or {}
        lines = []

        def _fmt(value):
            return '—' if value in [None, '', []] else value

        if self.action == 'insert':
            snapshot = data.get('data') if isinstance(data, dict) else None
            snapshot = snapshot if isinstance(snapshot, dict) else data
            for field, val in (snapshot or {}).items():
                lines.append(f"{field}: {_fmt(val)}")
            if not lines:
                lines.append('Datensatz erstellt')
        elif self.action == 'delete':
            snapshot = data.get('before') if isinstance(data, dict) else data
            for field, val in (snapshot or {}).items():
                lines.append(f"{field}: {_fmt(val)}")
            if not lines:
                lines.append('Datensatz gelöscht')
        else:
            for field, change in (data or {}).items():
                if isinstance(change, dict) and 'old' in change and 'new' in change:
                    old_val = _fmt(change.get('old'))
                    new_val = _fmt(change.get('new'))
                    lines.append(f"{field}: {old_val} → {new_val}")
                else:
                    lines.append(f"{field}: {_fmt(change)}")

        return lines or ['Keine Details verfügbar']

    @property
    def table_label(self):
        """Deutschsprachige Bezeichnung des betroffenen Bereichs."""
        return get_revision_table_label(self.table_name)

    @property
    def short_summary(self):
        """Gibt eine kurze deutschsprachige Zusammenfassung der Änderung zurück."""
        action_labels = {
            'insert': 'angelegt',
            'update': 'aktualisiert',
            'delete': 'gelöscht',
        }

        base_label = self.table_label
        action_label = action_labels.get(self.action, 'geändert')

        data = self.parsed_changes if isinstance(self.parsed_changes, dict) else {}
        summary_text = None

        if isinstance(data, dict):
            summary_text = data.get('summary') or data.get('message')

        if not summary_text and self.action == 'update' and data:
            changed_fields = ', '.join(list(data.keys())[:3])
            if len(data.keys()) > 3:
                changed_fields += ' …'
            summary_text = f"Geänderte Felder: {changed_fields}" if changed_fields else None

        if not summary_text:
            summary_text = f"{base_label} {action_label}"

        return summary_text
    
# Zusätzliche Modelle in models.py hinzufügen

class Contract(db.Model):
    __tablename__ = 'contracts'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = db.Column(db.String(36), db.ForeignKey('contract_templates.id'))
    apartment_id = db.Column(db.String(36), db.ForeignKey('apartments.id'), nullable=False)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False)
    landlord_id = db.Column(db.String(36), db.ForeignKey('landlords.id'))  # Vermieter-Referenz
    
    # Vertragsdaten
    contract_number = db.Column(db.String(50), unique=True, nullable=False)
    contract_type = db.Column(db.String(20), default='hauptmietvertrag')
    status = db.Column(db.String(20), default='draft')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    contract_start = db.Column(db.Date)
    contract_end = db.Column(db.Date)
    move_out_date = db.Column(db.Date)
    is_locked = db.Column(db.Boolean, default=False)
    notice_period = db.Column(db.Integer, default=3)
    rent_net = db.Column(db.Float, nullable=False)
    rent_additional = db.Column(db.Float, default=0.0)
    cold_rent = db.Column(db.Float, default=0.0)
    operating_cost_advance = db.Column(db.Float, default=0.0)
    heating_advance = db.Column(db.Float, default=0.0)
    floor_space = db.Column(db.Float)
    deposit = db.Column(db.Float)

    created_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    
    # Erweiterte Vertragsdaten
    rental_purpose = db.Column(db.String(100))
    rental_unit_description = db.Column(db.Text)
    furnishings = db.Column(db.Text)
    house_rules = db.Column(db.Text)
    payment_terms = db.Column(db.Text)
    rent_adjustment_clause = db.Column(db.Text)
    subletting_allowed = db.Column(db.Boolean, default=False)
    pet_regulations = db.Column(db.Text)
    maintenance_responsibilities = db.Column(db.Text)
    cosmetic_repairs = db.Column(db.Text)
    insurance_requirements = db.Column(db.Text)
    termination_terms = db.Column(db.Text)
    handover_terms = db.Column(db.Text)
    additional_agreements = db.Column(db.Text)
    
    # Energiekosten-Regelungen
    heating_costs_regulation = db.Column(db.Text)
    water_costs_regulation = db.Column(db.Text)
    electricity_costs_regulation = db.Column(db.Text)
    ev_charging_regulation = db.Column(db.Text)
    pv_electricity_regulation = db.Column(db.Text)
    
    # Vertragsinhalt
    contract_data = db.Column(db.Text)
    final_content = db.Column(db.Text)
    
    # Unterschriften
    landlord_signed = db.Column(db.Boolean, default=False)
    landlord_signature_date = db.Column(db.Date)
    tenant_signed = db.Column(db.Boolean, default=False)
    tenant_signature_date = db.Column(db.Date)
    
    # Dokumente
    pdf_path = db.Column(db.String(255))
    final_document = db.Column(db.String(255))
    is_archived = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # KORREKTUR: Alle relationships hier definieren mit eindeutigen backref-Namen
    creator = db.relationship('User', foreign_keys=[created_by], backref='user_created_contracts')
    apartment = db.relationship('Apartment', backref='apartment_contracts')
    tenant = db.relationship('Tenant', backref='tenant_contracts')
    template = db.relationship('ContractTemplate', backref='template_contracts')
    landlord = db.relationship('Landlord', backref='landlord_contracts')  # Eindeutiger backref-Name
    protocols = db.relationship('Protocol', backref='protocol_contract', lazy=True)
    revisions = db.relationship('ContractRevision', backref='revision_contract', lazy=True)
    inventory_items = db.relationship('InventoryItem', backref='inventory_contract', lazy=True, cascade='all, delete-orphan')
    blocks = db.relationship('ContractBlock', backref='block_contract', lazy=True, cascade='all, delete-orphan')

    def get_monthly_operating_prepayment(self) -> float:
        """Hilfsfunktion für Nebenkostenabrechnungen."""
        return (
            float(self.rent_additional or 0)
            + float(self.operating_cost_advance or 0)
            + float(self.heating_advance or 0)
        )
    
    
# In models.py - Neue Models
class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    room = db.Column(db.String(50))  # Raum
    item_name = db.Column(db.String(100), nullable=False)  # Gegenstand
    description = db.Column(db.Text)  # Beschreibung/Zustand
    quantity = db.Column(db.Integer, default=1)  # Anzahl
    condition = db.Column(db.String(20))  # neu, gut, abgenutzt, beschädigt
    notes = db.Column(db.Text)  # Bemerkungen
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='info')
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime)
    last_shown_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))


class SettlementAuditLog(db.Model):
    __tablename__ = 'settlement_audit_logs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    settlement_id = db.Column(db.String(36), db.ForeignKey('settlements.id'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'))
    action = db.Column(db.String(120), nullable=False)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    settlement = db.relationship('Settlement', backref=db.backref('audit_logs', lazy=True, order_by='SettlementAuditLog.created_at.desc()'))
    user = db.relationship('User', backref='settlement_audit_logs')

class ContractTemplate(db.Model):
    __tablename__ = 'contract_templates'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    template_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    variables = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='contract_templates')

class ClauseTemplate(db.Model):
    __tablename__ = 'clause_templates'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))  # mietrecht, hauspolitik, besondere_vereinbarungen
    title = db.Column(db.String(200), nullable=False)  # NEU: Titel für Anzeige
    content = db.Column(db.Text, nullable=False)
    variables = db.Column(db.Text)  # JSON mit verfügbaren Variablen
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    is_mandatory = db.Column(db.Boolean, default=False)  # NEU: Pflichtklausel
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Protocol(db.Model):
    __tablename__ = 'protocols'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    protocol_type = db.Column(db.String(20), nullable=False)  # uebergabe, uebernahme, schlussuebergabe
    protocol_date = db.Column(db.Date, nullable=False)
    is_closed = db.Column(db.Boolean, default=False)
    manual_pdf_path = db.Column(db.String(255))
    
    # Protokolldaten
    protocol_data = db.Column(db.Text)  # JSON mit Protokolldaten (Raumzustände, Mängel, etc.)
    final_content = db.Column(db.Text)  # Finaler HTML Inhalt
    
    # Unterschriften
    landlord_signed = db.Column(db.Boolean, default=False)
    landlord_signature_date = db.Column(db.Date)
    tenant_signed = db.Column(db.Boolean, default=False)
    tenant_signature_date = db.Column(db.Date)
    witness_signed = db.Column(db.Boolean, default=False)
    witness_name = db.Column(db.String(100))
    
    # Dokumente
    pdf_path = db.Column(db.String(255))
    is_archived = db.Column(db.Boolean, default=False)

    created_by = db.Column(db.String(36), db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='protocols')
    revisions = db.relationship('ProtocolRevision', backref='protocol', lazy=True)

class ContractRevision(db.Model):
    __tablename__ = 'contract_revisions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    revision_number = db.Column(db.Integer, nullable=False)
    
    # Änderungsdaten - KORRIGIERT: Namensänderung
    changed_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    change_description = db.Column(db.Text, nullable=False)
    old_data = db.Column(db.Text)
    new_data = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - KORRIGIERT
    user = db.relationship('User', backref='contract_revisions')

class ProtocolRevision(db.Model):
    __tablename__ = 'protocol_revisions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    protocol_id = db.Column(db.String(36), db.ForeignKey('protocols.id'), nullable=False)
    revision_number = db.Column(db.Integer, nullable=False)
    
    # Änderungsdaten
    changed_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    change_description = db.Column(db.Text, nullable=False)
    old_data = db.Column(db.Text)
    new_data = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='protocol_revisions')

# RSS Feed Modelle
class RSSFeed(db.Model):
    __tablename__ = 'rss_feeds'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(50), default='general')
    is_active = db.Column(db.Boolean, default=True)
    update_interval = db.Column(db.Integer, default=60)
    last_updated = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('RSSItem', backref='feed', lazy=True, cascade='all, delete-orphan')

class RSSItem(db.Model):
    __tablename__ = 'rss_items'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feed_id = db.Column(db.String(36), db.ForeignKey('rss_feeds.id'), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(500))
    published_date = db.Column(db.DateTime, nullable=False)
    guid = db.Column(db.String(500), unique=True)
    author = db.Column(db.String(200))
    categories = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False)
    is_starred = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'link': self.link,
            'published_date': self.published_date.isoformat() if self.published_date else None,
            'author': self.author,
            'categories': self.categories,
            'feed_name': self.feed.name,
            'is_read': self.is_read,
            'is_starred': self.is_starred
        }
    
# Zusätzliche Modelle in models.py hinzufügen

class Landlord(db.Model):
    __tablename__ = 'landlords'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    type = db.Column(db.String(20), nullable=False)  # natural, company
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    company_name = db.Column(db.String(100))
    legal_form = db.Column(db.String(50))
    commercial_register = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))
    vat_id = db.Column(db.String(50))
    
    # Address
    street = db.Column(db.String(100))
    street_number = db.Column(db.String(10))
    zip_code = db.Column(db.String(10))
    city = db.Column(db.String(50))
    country = db.Column(db.String(50), default='Deutschland')
    
    # Contact
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    website = db.Column(db.String(200))
    
    # Bank details
    bank_name = db.Column(db.String(100))
    iban = db.Column(db.String(34))
    bic = db.Column(db.String(11))
    account_holder = db.Column(db.String(100))
    
    # Legal
    representative = db.Column(db.String(100))
    birth_date = db.Column(db.Date)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # KORREKTUR: Keine relationships hier definieren - wird in Contract gemacht

class ContractBlock(db.Model):
    __tablename__ = 'contract_blocks'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    block_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_required = db.Column(db.Boolean, default=False)
    is_visible = db.Column(db.Boolean, default=True)
    variables = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ContractTemplateBlock(db.Model):
    __tablename__ = 'contract_template_blocks'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = db.Column(db.String(36), db.ForeignKey('contract_templates.id'), nullable=False)
    block_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_required = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50))
    variables = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # KORREKTUR: Eindeutiger backref-Name
    template = db.relationship('ContractTemplate', backref=db.backref('template_blocks_assoc', lazy=True, order_by='ContractTemplateBlock.sort_order'))

# In models.py - Nach den bestehenden Modellen hinzufügen

class ContractClause(db.Model):
    __tablename__ = 'contract_clauses'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    clause_template_id = db.Column(db.String(36), db.ForeignKey('clause_templates.id'))
    
    # Angepasste Werte
    custom_title = db.Column(db.String(200))
    custom_content = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    contract = db.relationship('Contract', backref=db.backref('clauses', lazy=True, order_by='ContractClause.sort_order'))
    template = db.relationship('ClauseTemplate', backref='contract_clauses')


class Income(db.Model):
    __tablename__ = 'incomes'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'), nullable=False)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'))
    income_type = db.Column(db.String(50), default='rent')
    amount = db.Column(db.Float, nullable=False)
    rent_portion = db.Column(db.Float, default=0.0)
    service_charge_portion = db.Column(db.Float, default=0.0)
    special_portion = db.Column(db.Float, default=0.0)
    is_advance_payment = db.Column(db.Boolean, default=False)
    reference = db.Column(db.String(255))
    source = db.Column(db.String(50))
    import_metadata = db.Column(db.Text)
    received_on = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = db.relationship('Contract', backref=db.backref('incomes', lazy=True, cascade='all, delete-orphan'))
    tenant = db.relationship('Tenant', backref=db.backref('incomes', lazy=True))


class DueDate(db.Model):
    __tablename__ = 'due_dates'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(200), nullable=False)
    due_on = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='open')
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = db.relationship('Contract', backref=db.backref('due_dates', lazy=True, cascade='all, delete-orphan'))


class MaintenanceTask(db.Model):
    __tablename__ = 'maintenance_tasks'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    scheduled_on = db.Column(db.Date, nullable=False)
    reminder_days_before = db.Column(db.Integer, default=7)
    status = db.Column(db.String(20), default='open')
    notes = db.Column(db.Text)
    protocol_required = db.Column(db.Boolean, default=True)
    reminder_sent = db.Column(db.Boolean, default=False)
    contract_id = db.Column(db.String(36), db.ForeignKey('contracts.id'))
    building_id = db.Column(db.String(36), db.ForeignKey('buildings.id'))

    contract = db.relationship('Contract', backref=db.backref('maintenance_tasks', lazy=True, cascade='all, delete-orphan'))
    building = db.relationship('Building', backref=db.backref('maintenance_tasks', lazy=True, cascade='all, delete-orphan'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def reminder_date(self):
        if not self.scheduled_on:
            return None
        return self.scheduled_on - timedelta(days=self.reminder_days_before or 0)