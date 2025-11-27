import uuid
from app.extensions import db
from app.models import StandardClauseTemplate


def _strip_paragraph_prefix(title: str) -> str:
    if not title:
        return title
    cleaned = title.lstrip('§').strip()
    if cleaned.startswith(('§', '.')):
        cleaned = cleaned.lstrip('§').lstrip('.').strip()
    return cleaned


def initialize_standard_clauses():
    """Initialisiert Standardklauseln und entfernt redundante Paragraphenzeichen."""

    standard_clauses = [
        {
            'category': 'parties',
            'title': 'Vertragsparteien',
            'content': (
                "Dieser Mietvertrag wird zwischen dem Vermieter §vermieter_vorname§ §vermieter_nachname§ "
                "und dem Mieter §mieter_vorname§ §mieter_nachname§ geschlossen. Beide Parteien sind "
                "voll geschäftsfähig und treten mit den in diesem Vertrag genannten Rechten und Pflichten auf."),
            'description': 'Definition der Vertragsparteien',
            'is_mandatory': True,
            'sort_order': 1
        },
        {
            'category': 'rental_object',
            'title': 'Mietobjekt',
            'content': (
                "Der Vermieter vermietet die Einheit §wohnung_nummer§ in §wohnung_adresse§ mit einer Fläche von §wohnung_flaeche§ m². "
                "Mitvermietet sind alle in der Übergabeliste aufgeführten Räume und Ausstattungsgegenstände. Änderungen am Umfang bedürfen "
                "der Schriftform."),
            'description': 'Beschreibung des Mietobjekts',
            'is_mandatory': True,
            'sort_order': 2
        },
        {
            'category': 'rental_term',
            'title': 'Mietdauer',
            'content': (
                "Das Mietverhältnis beginnt am §vertragsbeginn§ und läuft auf unbestimmte Zeit, sofern kein Enddatum vereinbart ist. "
                "Eine ordentliche Kündigung ist mit einer Frist von §kuendigungsfrist§ Monaten zum Monatsende möglich. Abweichende Fristen "
                "bedürfen der schriftlichen Vereinbarung."),
            'description': 'Beginn, Laufzeit und Kündigung',
            'is_mandatory': True,
            'sort_order': 3
        },
        {
            'category': 'rent',
            'title': 'Miete und Nebenkosten',
            'content': (
                "Die monatliche Nettomiete beträgt §miete_netto§ EUR, die monatlichen Betriebskostenvorauszahlungen §miete_nebenkosten§ EUR. "
                "Die Miete ist monatlich im Voraus, spätestens am dritten Werktag eines Monats, auf das vom Vermieter benannte Konto zu zahlen. "
                "Nebenkosten werden jährlich abgerechnet; Nachzahlungen oder Guthaben werden innerhalb von 30 Tagen ausgeglichen."),
            'description': 'Miethöhe, Fälligkeit und Betriebskosten',
            'is_mandatory': True,
            'sort_order': 4
        },
        {
            'category': 'deposit',
            'title': 'Kaution',
            'content': (
                "Der Mieter leistet eine Mietkaution in Höhe von §kaution§ EUR. Die Kaution wird verzinslich gemäß § 551 BGB angelegt. "
                "Eine Verrechnung mit laufenden Mieten ist ausgeschlossen. Die Rückzahlung erfolgt nach Beendigung des Mietverhältnisses "
                "und ordnungsgemäßer Rückgabe der Mietsache abzüglich berechtigter Forderungen des Vermieters."),
            'description': 'Sicherheitsleistung',
            'is_mandatory': True,
            'sort_order': 5
        },
        {
            'category': 'maintenance',
            'title': 'Schönheitsreparaturen und Instandhaltung',
            'content': (
                "Der Vermieter trägt die Instandhaltung der Mietsache. Übliche Schönheitsreparaturen während der Mietzeit (z. B. Streichen "
                "von Wänden und Decken) trägt der Mieter im Rahmen der gesetzlichen Vorgaben. Mängel sind unverzüglich anzuzeigen; "
                "eigenmächtige Mangelbeseitigung bedarf der Abstimmung mit dem Vermieter."),
            'description': 'Pflichten zu Reparaturen und Pflege',
            'is_mandatory': False,
            'sort_order': 10
        },
        {
            'category': 'operating_costs',
            'title': 'Betriebskostenabrechnung',
            'content': (
                "Der Vermieter erstellt jährlich eine Betriebskostenabrechnung gemäß § 556 BGB und der Betriebskostenverordnung. "
                "Grundlage sind die tatsächlichen Kosten sowie die vereinbarten Verteilerschlüssel (Fläche, Verbrauch oder Einheiten). "
                "Einwendungen gegen die Abrechnung sind innerhalb von 12 Monaten nach Zugang schriftlich geltend zu machen."),
            'description': 'Regelung zur Abrechnung',
            'is_mandatory': False,
            'sort_order': 11
        },
        {
            'category': 'house_rules',
            'title': 'Hausordnung und Gebrauch',
            'content': (
                "Die Hausordnung ist Bestandteil dieses Vertrages. Der Mieter verpflichtet sich zu einem rücksichtsvollen Umgang mit Nachbarn, "
                "zur Einhaltung von Ruhezeiten und zum sachgemäßen Gebrauch von gemeinschaftlichen Einrichtungen. Haustiere bedürfen der Zustimmung, "
                "sofern sie über Kleintierhaltung hinausgehen."),
            'description': 'Hausordnung und Verhalten',
            'is_mandatory': False,
            'sort_order': 12
        },
        {
            'category': 'handover',
            'title': 'Übergabe und Rückgabe',
            'content': (
                "Bei Einzug wird ein Übergabeprotokoll erstellt, das Zählerstände, Schlüsselanzahl und Zustand dokumentiert. Bei Auszug ist die Wohnung "
                "geräumt, gereinigt und mit allen Schlüsseln zurückzugeben; Schäden und fehlende Schlüssel werden nach tatsächlichem Aufwand berechnet."),
            'description': 'Regeln für Übergabeprotokolle',
            'is_mandatory': False,
            'sort_order': 13
        }
    ]

    for clause_data in standard_clauses:
        clause_data['title'] = _strip_paragraph_prefix(clause_data['title'])
        existing = StandardClauseTemplate.query.filter_by(
            title=clause_data['title'],
            category=clause_data['category']
        ).first()

        if existing:
            existing.title = _strip_paragraph_prefix(existing.title)
            existing.content = clause_data['content']
            existing.description = clause_data['description']
            existing.is_mandatory = clause_data['is_mandatory']
            existing.sort_order = clause_data['sort_order']
            existing.is_active = True
        else:
            clause = StandardClauseTemplate(
                id=str(uuid.uuid4()),
                **clause_data
            )
            db.session.add(clause)

    db.session.commit()
