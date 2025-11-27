from app import db
from app.models import MeterType
import uuid

def init_default_data():
    """Initialize default meter types and other essential data"""
    
    # Check if meter types already exist
    if MeterType.query.count() == 0:
        print("📊 Creating default meter types...")
        
        meter_types = [
            # Strom
            {'name': 'Strom Hauptzähler', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
            {'name': 'Strom Wohnung', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
            {'name': 'Strom Allgemeinstrom', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
            {'name': 'Strom Wallbox', 'category': 'electricity', 'unit': 'kWh', 'decimal_places': 2},
            
            # Wasser
            {'name': 'Wasser Hauptzähler', 'category': 'water', 'unit': 'm³', 'decimal_places': 3},
            {'name': 'Wasser Wohnung Kalt', 'category': 'water', 'unit': 'm³', 'decimal_places': 3},
            {'name': 'Wasser Wohnung Warm', 'category': 'water', 'unit': 'm³', 'decimal_places': 3},
            
            # Heizung
            {'name': 'Heizung Hauptzähler', 'category': 'heating', 'unit': 'kWh', 'decimal_places': 2},
            {'name': 'Heizung Wohnung', 'category': 'heating', 'unit': 'kWh', 'decimal_places': 2},
            
            # Gas
            {'name': 'Gas Hauptzähler', 'category': 'gas', 'unit': 'm³', 'decimal_places': 3},
            {'name': 'Gas Wohnung', 'category': 'gas', 'unit': 'm³', 'decimal_places': 3},
        ]
        
        for mt_data in meter_types:
            meter_type = MeterType(
                id=str(uuid.uuid4()),
                name=mt_data['name'],
                category=mt_data['category'],
                unit=mt_data['unit'],
                decimal_places=mt_data['decimal_places']
            )
            db.session.add(meter_type)
        
        db.session.commit()
        print("✅ Default meter types created")