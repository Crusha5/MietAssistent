# MietAssistent 2.0

Professionelle Nebenkostenabrechnung mit flexibler Zählerstruktur. Dieses Repository enthält die Web-Anwendung inklusive Setup-Wizard, Zählerhierarchie und Vertragseditor.

## Projektvision
- **Name:** MietAssistent (v2.0.0)
- **Tagline:** Komplettes Mietverwaltungssystem mit erweiterter Zählerhierarchie – Einfach. Sicher. Deutsch.
- **Branding:** Primärfarbe `#1e40af`, Sekundärfarbe `#0f766e`, Akzent `#dc2626`, Schriftarten Inter & Open Sans.

## Kernarchitektur
- Gebäude → Wohnungen/Gewerbe → Zählerstruktur → Mieter/Berechtigungen
- Unbegrenzte Zähler-Verschachtelung inkl. Haupt‑, Unter‑ und Sonderzählern
- JWT-geschützte API mit Swagger UI unter `/api/docs`

## Installation (Docker One-Click)
1. Voraussetzungen: Docker ≥20.10, Docker Compose ≥2.12, 2 GB RAM, 2 CPU, Ports 5000/5432 frei
2. Starten: `docker-compose up -d`
3. Aufruf: http://localhost:5000/setup führt durch Systemcheck, DB-Initialisierung, Admin-Anlage und Erstkonfiguration

## Backup & Betrieb
- Automatische Backups täglich um 02:00 Uhr nach `./backups` (30 Tage Aufbewahrung)
- Healthcheck unter `/health`, Log-Level per `LOG_LEVEL` variierbar
- Uploads und Datenbank werden in `./uploads` bzw. `./data` persistiert

## Sicherheit
- Passwort-Hashing mit BCrypt, Sitzungen als HTTPOnly + CSRF-Schutz
- Rollen: admin, manager, tenant mit feingranularen Berechtigungen
- DSGVO-konforme Aufbewahrungsfristen für Zählerstände, Abrechnungen und Verträge
