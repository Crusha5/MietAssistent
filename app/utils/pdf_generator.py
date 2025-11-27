from xhtml2pdf import pisa
from flask import current_app
from datetime import datetime
import os
import json


def generate_pdf_from_html(html_content: str, output_path: str) -> bool:
    """
    Generiert ein PDF aus HTML-Inhalt mit xhtml2pdf.

    :param html_content: Vollständiger HTML-String
    :param output_path: Zielpfad für die PDF-Datei
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        # Zielverzeichnis sicherstellen
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w+b") as output_file:
            pdf = pisa.CreatePDF(html_content, dest=output_file)

        if pdf.err:
            current_app.logger.error(f"PDF Generation Error: {pdf.err}")
            return False

        return True

    except Exception as e:
        current_app.logger.error(f"PDF Generation Exception: {str(e)}", exc_info=True)
        return False


def save_contract_pdf(contract, html_content: str) -> bool:
    """
    Speichert ein Vertrags-PDF im uploads/contracts-Verzeichnis
    und setzt contract.pdf_path auf den Dateinamen.
    """
    filename = f"contract_{contract.contract_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.abspath('uploads')
    upload_dir = os.path.join(upload_root, 'contracts')
    output_path = os.path.join(upload_dir, filename)

    if generate_pdf_from_html(html_content, output_path):
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

    if generate_pdf_from_html(html_content, output_path):
        protocol.pdf_path = filename
        return True

    return False


from datetime import datetime

def generate_professional_contract_html(contract, clauses=None, paragraph_tree=None, inventory_items=None) -> str:
    """
    Schlichtes, stabiles, professionelles Mietvertrags-HTML für xhtml2pdf.
    - Times New Roman / DejaVu Serif
    - Großer Seitenrand
    - Mittige, fette Überschriften
    - Footer mit Datum + Seite X/Y
    - Unterschriftslinien für Vermieter und Mieter
    """
    if clauses is None:
        clauses = []
    if paragraph_tree is None:
        paragraph_tree = []
    if inventory_items is None:
        inventory_items = []

    # ---------- Stammdaten ----------
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

    # ---------- Unterklauseln rendern ----------
    def render_children(children, prefix: str) -> str:
        html_parts = []
        for idx, child in enumerate(children or [], start=1):
            num = f"{prefix}.{idx}"
            title = child.get("title") or ""
            content = child.get("content") or ""
            html_parts.append(f"""
    <div class="subclause">
        <div class="subclause-title">§ {num} {title}</div>
        <div class="clause-body">{content}</div>
    </div>
""")
            if child.get("children"):
                html_parts.append(render_children(child["children"], num))
        return "".join(html_parts)

    # ---------- HTML + CSS (sauber escapte f-String-Variante) ----------
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 2.5cm;
    }}

    body {{
        font-family: "Times New Roman", "DejaVu Serif", serif;
        font-size: 11pt;
        line-height: 1.45;
        color: #000;
    }}

    h1.main-title {{
        text-align: center;
        font-size: 20pt;
        font-weight: bold;
        margin: 0 0 1.5cm 0;
    }}

    .meta-block {{
        margin-bottom: 0.45cm;
    }}

    .meta-label {{
        font-weight: bold;
    }}

    .clause {{
        margin-top: 0.9cm;
        page-break-inside: avoid;
    }}

    .clause-title {{
        font-size: 13pt;
        font-weight: bold;
        text-align: center;
        margin-bottom: 0.25cm;
    }}

    .clause-body {{
        text-align: justify;
    }}

    .subclause {{
        margin-left: 1.0cm;
        margin-top: 0.3cm;
        page-break-inside: avoid;
    }}

    .subclause-title {{
        font-weight: bold;
        margin-bottom: 0.15cm;
    }}

    .signature-block {{
        margin-top: 2.0cm;
    }}

    .signature-table {{
        width: 100%;
        margin-top: 1.0cm;
    }}

    .sig-cell {{
        width: 48%;
        text-align: center;
        vertical-align: bottom;
    }}

    .sig-line {{
        border-top: 1px solid #000;
        width: 90%;
        margin: 0.8cm auto 0.3cm auto;
    }}

    .footer-text {{
        font-size: 9pt;
        text-align: center;
        color: #444;
    }}
</style>
</head>
<body>

<pdf:pagefooter>
    <div class="footer-text">
        Dieses Dokument wurde am {created_str} generiert und ist rechtlich bindend – 
        Seite <pdf:pagenumber /> / <pdf:pagecount />
    </div>
</pdf:pagefooter>

<h1 class="main-title">Mietvertrag</h1>

<div class="meta-block">
    <span class="meta-label">Vermieter:</span><br/>
    {landlord_name}
</div>

<div class="meta-block">
    <span class="meta-label">Mieter:</span><br/>
    {tenant_name}
</div>

<div class="meta-block">
    <span class="meta-label">Mietobjekt:</span><br/>
    {apartment_info}
</div>

<div class="meta-block">
    <span class="meta-label">Vertragsnummer:</span>
    {contract_number}
</div>

<div class="meta-block">
    <span class="meta-label">Vertragsbeginn:</span>
    {start_str}
</div>

<pdf:pagebreak/>
"""

    # ---------- Paragraphen aus dem Tree ----------
    parts = [html]
    for idx, node in enumerate(paragraph_tree or [], start=1):
        number = node.get("number") or str(idx)
        title = node.get("title") or ""
        content = node.get("content") or ""

        parts.append(f"""
<div class="clause">
    <div class="clause-title">§ {number} {title}</div>
    <div class="clause-body">{content}</div>
</div>
""")

        if node.get("children"):
            parts.append(render_children(node["children"], str(number)))

    # ---------- Unterschriftenblock ----------
    parts.append(f"""
<div class="signature-block">
    <p><strong>Ort, Datum:</strong> ________________________________</p>

    <table class="signature-table">
        <tr>
            <td class="sig-cell">
                <div class="sig-line"></div>
                <strong>Unterschrift Vermieter</strong><br/>
                {landlord_name}
            </td>
            <td class="sig-cell">
                <div class="sig-line"></div>
                <strong>Unterschrift Mieter</strong><br/>
                {tenant_name}
            </td>
        </tr>
    </table>
</div>

</body>
</html>
""")

    return "".join(parts)
