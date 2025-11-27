import os
from datetime import datetime

from flask import current_app
from weasyprint import CSS, HTML


def _get_base_path() -> str:
    try:
        return current_app.root_path
    except Exception:
        return os.getcwd()


def _get_stylesheets():
    """Builds the stylesheet list for WeasyPrint with a stable path."""
    base_path = _get_base_path()
    css_path = os.path.join(base_path, 'static', 'css', 'contract_pdf.css')
    if not os.path.exists(css_path):
        try:
            current_app.logger.warning("contract_pdf.css not found at %s", css_path)
        except Exception:
            pass
    return [CSS(filename=css_path)]


def generate_pdf_from_html_weasyprint(html_content: str, output_path: str) -> bool:
    """Generiert ein PDF aus HTML-Inhalt mit WeasyPrint und speichert es auf dem Dateisystem."""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        HTML(string=html_content, base_url=_get_base_path()).write_pdf(
            output_path, stylesheets=_get_stylesheets()
        )
        return True
    except Exception as e:
        current_app.logger.error(f"WeasyPrint PDF Generation Exception: {str(e)}", exc_info=True)
        return False


def generate_pdf_weasyprint(html_content: str, output_path: str) -> bool:
    """Alias für generate_pdf_from_html_weasyprint für Rückwärtskompatibilität."""
    return generate_pdf_from_html_weasyprint(html_content, output_path)


def generate_pdf_bytes(html_content: str) -> bytes:
    """Rendert HTML zu PDF-Bytes (für In-Memory-Downloads)."""
    try:
        return HTML(string=html_content, base_url=_get_base_path()).write_pdf(
            stylesheets=_get_stylesheets()
        )
    except Exception as e:
        current_app.logger.error(f"WeasyPrint PDF Bytes Generation Exception: {str(e)}", exc_info=True)
        return b""


def save_contract_pdf(contract, html_content: str) -> bool:
    """
    Speichert ein Vertrags-PDF im uploads/contracts-Verzeichnis
    und setzt contract.pdf_path auf den Dateinamen.
    """
    filename = f"contract_{contract.contract_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.abspath('uploads')
    upload_dir = os.path.join(upload_root, 'contracts')
    output_path = os.path.join(upload_dir, filename)

    if generate_pdf_from_html_weasyprint(html_content, output_path):
        contract.pdf_path = filename
        return True

    return False


def save_protocol_pdf(protocol, html_content: str) -> bool:
    """
    Speichert ein Protokoll-PDF im uploads/protocols-Verzeichnis.
    """
    filename = f"protocol_{protocol.protocol_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.abspath('uploads')
    upload_dir = os.path.join(upload_root, 'protocols')
    output_path = os.path.join(upload_dir, filename)

    if generate_pdf_from_html_weasyprint(html_content, output_path):
        protocol.pdf_path = filename
        return True

    return False


def generate_professional_contract_html(contract, clauses=None, paragraph_tree=None, inventory_items=None) -> str:
    """
    Professionelles Mietvertrags-HTML optimiert für WeasyPrint.
    - DejaVu Sans als Standardschrift
    - Große Seitenränder
    - Mittige, fette §-Überschriften
    - Footer mit Seitenzahlen via CSS-Counter
    - Unterschriftslinien für Vermieter und Mieter
    """
    if clauses is None:
        clauses = []
    if paragraph_tree is None:
        paragraph_tree = []
    if inventory_items is None:
        inventory_items = []

    tenant_name = ""
    if getattr(contract, "tenant", None):
        first = getattr(contract.tenant, "first_name", "") or ""
        last = getattr(contract.tenant, "last_name", "") or ""
        tenant_name = f"{first} {last}".strip()

    landlord_name = ""
    if getattr(contract, "landlord", None):
        company = getattr(contract.landlord, "company_name", None)
        if company:
            landlord_name = company
        else:
            lfirst = getattr(contract.landlord, "first_name", "") or ""
            llast = getattr(contract.landlord, "last_name", "") or ""
            landlord_name = f"{lfirst} {llast}".strip()

    apartment_info = ""
    if getattr(contract, "apartment", None) and getattr(contract.apartment, "building", None):
        apt = contract.apartment
        b = apt.building
        parts = []
        ap_no = getattr(apt, "apartment_number", None)
        if ap_no:
            parts.append(str(ap_no))
        street = getattr(b, "street", "") or ""
        street_no = getattr(b, "street_number", "") or ""
        if street or street_no:
            parts.append(f"{street} {street_no}".strip())
        zip_code = getattr(b, "zip_code", "") or ""
        city = getattr(b, "city", "") or ""
        if zip_code or city:
            parts.append(f"{zip_code} {city}".strip())
        apartment_info = ", ".join(p for p in parts if p)

    created_at = getattr(contract, "created_at", None) or datetime.now()
    created_str = created_at.strftime("%d.%m.%Y")

    start_date = getattr(contract, "start_date", None)
    start_str = start_date.strftime("%d.%m.%Y") if start_date else "-"

    contract_number = getattr(contract, "contract_number", "") or ""

    def render_children(children, prefix: str) -> str:
        html_parts = []
        for idx, child in enumerate(children or [], start=1):
            num = f"{prefix}.{idx}"
            title = child.get("title") or ""
            content = child.get("content") or ""
            html_parts.append(
                f"""
    <div class="clause clause--sub">
        <div class="clause-title">§ {num} {title}</div>
        <div class="clause-body">{content}</div>
    </div>
"""
            )
            if child.get("children"):
                html_parts.append(render_children(child["children"], num))
        return "".join(html_parts)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
<link rel=\"stylesheet\" href=\"static/css/contract_pdf.css\">
</head>
<body class=\"contract-body\">
<section class=\"cover-page\">
    <div>
        <div class=\"cover-badge\">Rechtssicherer Mietvertrag</div>
        <div class=\"cover-title\">Wohnraummietvertrag</div>
        <div class=\"cover-subtitle\">zwischen {landlord_name or '________________'} (Vermieter) und {tenant_name or '________________'} (Mieter)</div>
    </div>
    <div class=\"cover-meta\">
        <div>
            <div class=\"label\">Vertragsnummer</div>
            <div class=\"value\">{contract_number}</div>
        </div>
        <div>
            <div class=\"label\">Mietbeginn</div>
            <div class=\"value\">{start_str}</div>
        </div>
        <div>
            <div class=\"label\">Mietobjekt</div>
            <div class=\"value\">{apartment_info}</div>
        </div>
        <div>
            <div class=\"label\">Erstellt am</div>
            <div class=\"value\">{created_str}</div>
        </div>
    </div>
    <div class=\"legal-box\">
        Dieser Vertrag stellt die maßgebliche Vereinbarung zwischen Vermieter und Mieter dar. Bitte prüfen Sie alle Daten auf Vollständigkeit und Richtigkeit. 
        Änderungen oder Ergänzungen bedürfen der Schriftform. Angaben zu Miete, Nebenkosten, Kaution und Kündigungsfristen sind den folgenden Paragraphen zu entnehmen.
    </div>
    <div class=\"cover-footer\">
        <div>Ort der Immobilie: {apartment_info or '________________'}</div>
        <div>Ausfertigung für beide Vertragsparteien</div>
    </div>
</section>
<header class=\"contract-header\">
    <div>
        <div class=\"label\">Vertragsnummer</div>
        <div class=\"value\">{contract_number}</div>
    </div>
    <div>
        <div class=\"label\">Erstellt am</div>
        <div class=\"value\">{created_str}</div>
    </div>
</header>
<h1 class=\"main-title\">Mietvertrag</h1>
<section class=\"meta-grid\">
    <div>
        <div class=\"label\">Vermieter</div>
        <div class=\"value\">{landlord_name}</div>
    </div>
    <div>
        <div class=\"label\">Mieter</div>
        <div class=\"value\">{tenant_name}</div>
    </div>
    <div>
        <div class=\"label\">Mietobjekt</div>
        <div class=\"value\">{apartment_info}</div>
    </div>
    <div>
        <div class=\"label\">Vertragsbeginn</div>
        <div class=\"value\">{start_str}</div>
    </div>
</section>
<div class=\"divider\"></div>
<div class=\"key-points\">
    <div class=\"key-point\"><strong>Vertragspartner:</strong> {landlord_name} ↔ {tenant_name}</div>
    <div class=\"key-point\"><strong>Objekt:</strong> {apartment_info or 'gemäß Mietgegenstand'}</div>
    <div class=\"key-point\"><strong>Beginn:</strong> {start_str}</div>
    <div class=\"key-point\"><strong>Rechtsgrundlage:</strong> BGB §§ 535 ff.; individuelle Regelungen siehe nachfolgende Paragraphen.</div>
</div>
<div class=\"legal-box\">
    Dieser Vertrag basiert auf den gesetzlichen Bestimmungen der §§ 535 ff. BGB. Die folgenden Klauseln regeln insbesondere Mietgegenstand, Höhe und Fälligkeit der Miete, Nebenkosten, Kaution, Gebrauch des Mietobjekts, Schönheitsreparaturen sowie Kündigungsfristen. Unwirksame Klauseln berühren die Wirksamkeit des übrigen Vertrags nicht (Salvatorische Klausel).
</div>
"""

    parts = [html]
    for idx, node in enumerate(paragraph_tree or [], start=1):
        number = node.get("number") or str(idx)
        title = node.get("title") or ""
        content = node.get("content") or ""

        parts.append(
            f"""
<section class=\"clause\">
    <div class=\"clause-title\">§ {number} {title}</div>
    <div class=\"clause-body\">{content}</div>
</section>
"""
        )

        if node.get("children"):
            parts.append(render_children(node["children"], str(number)))

    parts.append(
        f"""
<section class=\"signature-block\">
    <p class=\"label\">Ort, Datum</p>
    <div class=\"signature-date\">____________________________</div>
    <div class=\"signature-row\">
        <div class=\"sig-cell\">
            <div class=\"sig-line\"></div>
            <div class=\"sig-label\">Unterschrift Vermieter</div>
            <div class=\"sig-name\">{landlord_name}</div>
        </div>
        <div class=\"sig-cell\">
            <div class=\"sig-line\"></div>
            <div class=\"sig-label\">Unterschrift Mieter</div>
            <div class=\"sig-name\">{tenant_name}</div>
        </div>
    </div>
</section>
</body>
</html>
"""
    )

    return "".join(parts)
