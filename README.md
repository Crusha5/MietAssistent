# MietAssistent
MietAssistent - Professionelles Mietverwaltungssystem

📋 Übersicht
MietAssistent ist ein komplettes Mietverwaltungssystem mit erweiterter Zählerhierarchie und umfassender Dokumentenverwaltung, entwickelt für deutsche Vermieter und Hausverwaltungen. Die Anwendung vereinfacht die professionelle Mietverwaltung von der Vertragserstellung bis zur Rücknahmeabrechnung.

Einfach. Sicher. Deutsch.

✨ Hauptfunktionen
📑 Umfassende Dokumentenverwaltung
📝 Mietvertragsmanagement
Digitale Vertragserstellung mit Vorlagensystem

Automatische Vertragsgenerierung basierend auf Wohnungsdaten

Vertragshistorie mit Versionierung

Fristenüberwachung für Kündigungen und Verlängerungen

Digitale Signatur-Unterstützung

Vertragsarchivierung mit DSGVO-konformer Aufbewahrung

🏠 Übergabeprotokoll-Management
Strukturierte Protokollerstellung beim Einzug

Foto-Dokumentation aller Räume und Mängel

Inventarlisten-Integration mit Zustandsbewertung

Digitale Unterschriften von Mieter und Vermieter

Automatische Protokoll-Generierung mit Standardtextbausteinen

Mängelverwaltung mit Nachverfolgung und Fristen

🔙 Rücknahmeprotokoll-Management
Vergleich mit Übergabeprotokoll beim Auszug

Schadensdokumentation mit Foto-Nachweisen

Kautionabrechnungs-Vorbereitung

Reinigungs- und Reparaturkosten-Zuordnung

Automatische Berechnung von Rückstellungen

Digitale Abnahmequittungen

🛋️ Inventar- und Ausstattungsverwaltung
Detailierte Inventarlisten pro Wohnung

Kategorisierung nach Möbeln, Elektrogeräten, Küchenausstattung

Zustandsbewertung mit Foto-Dokumentation

Wertberechnung und Abschreibungsverwaltung

Wartungsintervalle und Service-Historie

Beschaffungsmanagement für Ersatzbeschaffungen

🏢 Gebäude- und Wohnungsverwaltung
Komplette Hierarchie von Gebäuden bis zu einzelnen Mieteinheiten

Flexible Zuweisung von Mietern und Berechtigungen

Dokumentenmanagement für Verträge und Abrechnungen

🔄 Erweiterte Zählerhierarchie
Vollständige Zählerstruktur mit Haupt- und Unterzählern

Unbegrenzte Verschachtelungstiefe für komplexe Gebäudestrukturen

Virtuelle Zähler für Berechnungen ohne physisches Gerät

Multiplikationsfaktoren für Umrechnungen

Unterstützung für alle Zählertypen:

⚡ Strom (Hauptzähler, Unterzähler, Sonderzähler)

💧 Wasser (Kalt, Warm, Zirkulation)

🔥 Heizung (Wärmemengenzähler, Wohnungszähler)

🔵 Gas

🌱 Erneuerbare Energien (PV, Wärmepumpe, BHKW)

📊 Abrechnungsmanagement
Automatische Betriebskostenverteilung

Flexible Verteilerschlüssel (nach Verbrauch, Fläche, Einheiten)

PDF-Generierung für Abrechnungen

Echtzeit-Berechnungen und Vorschau

📱 Mobile Erfassung
Foto-Erfassung von Zählerständen und Protokollen

QR-Code-Scannen für Inventargegenstände

Offline-Modus mit Synchronisation

Biometrische Anmeldung

🚀 Schnellstart
Voraussetzungen
Docker 20.10+

Docker Compose 2.12+

2GB RAM, 2 CPU Kerne

2GB freier Speicher

Installation
Option 1: One-Click Docker Installation (Empfohlen)
bash
# Klonen des Repositorys
git clone https://github.com/your-username/mietassistent.git
cd mietassistent

# Starten mit Docker Compose
docker-compose up -d
Option 2: Script-basierte Installation
bash
# Linux/macOS
./setup.sh

# Windows
setup.bat
Ersteinrichtung
Öffnen Sie http://localhost:5000/setup im Browser

Folgen Sie dem web-basierten Installationsassistenten:

Systemvoraussetzungen prüfen

Datenbank initialisieren

Admin-Benutzer anlegen

Erstes Gebäude konfigurieren

Zählerstruktur einrichten

Dokumentenvorlagen einrichten

🏗️ Systemarchitektur
Erweiterte Datenmodelle
Dokumentenmanagement
python
RentalContract:
- Vertragsnummer, Laufzeit, Kündigungsfristen
- Mietparteien, Kaution, Nebenkostenabrechnung
- Digitale Signatur-Felder, Anhänge

HandoverProtocol:
- Übergabedatum, Beteiligte Personen
- Raumprotokolle mit Zustandsbeschreibungen
- Foto-Galerien pro Raum, Mängelliste
- Inventarliste mit Zustandsbewertung

TakebackProtocol:
- Rückgabedatum, Schadensdokumentation
- Vergleich mit Übergabeprotokoll
- Kautionabrechnungs-Vorlage
- Reparatur- und Reinigungskosten

Inventory:
- Kategorien: Möbel, Elektrogeräte, Küche, Bad
- Zustandsbewertung, Anschaffungswert, Abschreibung
- Wartungshistorie, Foto-Dokumentation
- Zugeordnete Räume, Seriennummern
Technologie-Stack
Backend: Python Flask

Datenbank: SQLite (produktionsbereit)

Frontend: Bootstrap 5.3 + Custom CSS

Container: Docker & Docker Compose

API: RESTful mit JWT-Authentifizierung

PDF-Generierung: WeasyPrint

Bildverarbeitung: Pillow

📁 Projektstruktur
text
mietassistent/
├── app/
│   ├── models.py             # Erweiterte Datenmodelle
│   ├── routes/               # API-Routen
│   │   ├── apartments.py     # Wohnungsverwaltung
│   │   ├── auth.py           # Authentifizierung
│   │   ├── buildings.py      # Gebäudeverwaltung
│   │   ├── meters.py         # Zählerverwaltung
│   │   ├── settlements.py    # Abrechnungen
│   │   ├── contracts.py      # Mietverträge
│   │   ├── protocols.py      # Übergabe/Rücknahme
│   │   └── inventory.py      # Inventarverwaltung
│   ├── static/               # CSS, JS, Bilder
│   └── templates/            # HTML-Templates
│       ├── contracts/        # Vertragsmanagement
│       ├── protocols/        # Protokoll-Templates
│       └── inventory/        # Inventar-Verwaltung
├── data/                     # Datenbank und Konfiguration
├── uploads/                  # Hochgeladene Dokumente und Fotos
│   ├── contracts/            # Mietverträge
│   ├── protocols/            # Übergabe/Rücknahme-Protokolle
│   ├── inventory/            # Inventarfotos
│   └── documents/            # Sonstige Dokumente
├── backups/                  # Automatische Sicherungen
├── templates/                # Dokumentenvorlagen
│   ├── contracts/            # Vertragsvorlagen
│   ├── protocols/            # Protokollvorlagen
│   └── reports/              # Berichtsvorlagen
├── docker-compose.yml        # Docker Konfiguration
├── Dockerfile                # Container Definition
└── requirements.txt          # Python Abhängigkeiten
🔧 Konfiguration
Umgebungsvariablen
bash
FLASK_ENV=production
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:////app/data/mietassistent.db
UPLOAD_FOLDER=/app/uploads
MAX_FILE_SIZE=16777216
DOCUMENT_TEMPLATES_PATH=/app/templates
Ports
5000: Web-Oberfläche

5432: Datenbank (optional)

📚 API Dokumentation
Die vollständige API-Dokumentation ist verfügbar unter:

Swagger UI: http://localhost:5000/api/docs

API Base Path: /api/v1

Erweiterte Endpoints für Dokumentenmanagement
Mietverträge
GET /api/v1/contracts - Verträge auflisten

POST /api/v1/contracts - Neuen Vertrag erstellen

POST /api/v1/contracts/{id}/generate-pdf - Vertrag als PDF generieren

POST /api/v1/contracts/{id}/sign - Vertrag digital signieren

Protokoll-Management
GET /api/v1/protocols/handover - Übergabeprotokolle

POST /api/v1/protocols/handover - Übergabe protokollieren

GET /api/v1/protocols/takeback - Rücknahmeprotokolle

POST /api/v1/protocols/takeback - Rücknahme protokollieren

POST /api/v1/protocols/{id}/upload-photo - Fotos hochladen

Inventarverwaltung
GET /api/v1/inventory - Inventar auflisten

POST /api/v1/inventory - Inventargegenstand anlegen

POST /api/v1/inventory/{id}/maintenance - Wartung dokumentieren

GET /api/v1/inventory/categories - Kategorien verwalten

🔒 Sicherheit
Authentifizierung & Autorisierung
BCrypt Password Hashing

JWT Bearer Tokens

Rollenbasierte Berechtigungen (Admin, Manager, Tenant)

Automatischer Logout nach 60 Minuten

Datenschutz
DSGVO-konform

Verschlüsselung sensibler Daten

HTTPS/TLS für alle Verbindungen

GoBD-konforme Buchführung

Berechtigungskonzept für dokumentenbezogene Daten

💾 Backup & Wiederherstellung
Automatische Backups: Täglich um 02:00 Uhr

Retention: 30 Tage

Backup-Typen: Vollständig, Inkrementell, Datenbank-only

Wiederherstellung: Über Web-Oberfläche oder Script

Dokumenten-Archivierung: Langzeitarchivierung gemäß gesetzlicher Aufbewahrungsfristen

🎯 Workflow-Unterstützung
Mieter-Einzug
Vertragserstellung mit digitaler Signatur

Übergabeprotokoll mit Raum-für-Raum Dokumentation

Inventarerfassung mit Foto-Nachweisen

Zählerstandserfassung zum Einzugszeitpunkt

Laufende Verwaltung
Regelmäßige Zählerstandsablesung

Wartungsmanagement für Inventar

Vertragsverwaltung mit Fristenüberwachung

Dokumentenarchivierung aller relevanter Unterlagen

Mieter-Auszug
Rücknahmeprotokoll mit Schadensdokumentation

Endabrechnung der Nebenkosten

Kautionabrechnung mit Belegzuordnung

Protokoll-Archivierung für gesetzliche Aufbewahrung

🐛 Fehlerbehebung
Häufige Probleme
Port 5000 belegt: Ändern Sie den Port in docker-compose.yml

Berechtigungsfehler: Stellen Sie sicher, dass Docker ausreichend Rechte hat

Datenbank-Fehler: Prüfen Sie die Schreibrechte im data/ Verzeichnis

Upload-Fehler: Prüfen Sie verfügbaren Speicherplatz und Dateiberechtigungen

Logs anzeigen
bash
docker-compose logs mietassistent_app
