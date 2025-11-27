from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime

from app.extensions import db
from app.models import (
    User,
    UserPreference,
    Landlord,
    RevisionLog,
    get_revision_table_label,
)
import json
from app.routes.main import login_required
from app.utils.schema_helpers import ensure_user_landlord_flag
from app.utils.project_profile import load_project_profile
from io import BytesIO
import pandas as pd
from flask import send_file
from xhtml2pdf import pisa
from flask import render_template_string

settings_bp = Blueprint('settings_web', __name__, url_prefix='/settings')


@settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def settings_home():
    """Einfache Einstellungsübersicht mit Darkmode- und Passwort-Optionen."""
    ensure_user_landlord_flag()
    user = User.query.get(session.get('user_id'))
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('auth.web_login'))

    prefs = UserPreference.query.filter_by(user_id=user.id).first()
    if not prefs:
        prefs = UserPreference(user_id=user.id, preferences=json.dumps({}))
        db.session.add(prefs)
        db.session.commit()

    preference_data = json.loads(prefs.preferences or '{}')

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'toggle_theme':
            preference_data['dark_mode'] = request.form.get('dark_mode') == 'on'
            prefs.preferences = json.dumps(preference_data)
            db.session.commit()
            flash('Theme-Einstellung gespeichert und benutzerbezogen hinterlegt.', 'success')
            return redirect(url_for('settings_web.settings_home'))

        if action == 'change_password':
            current_pw = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')

            if not user.check_password(current_pw):
                flash('Aktuelles Passwort ist falsch.', 'danger')
            elif not new_pw or len(new_pw) < 8:
                flash('Neues Passwort muss mindestens 8 Zeichen lang sein.', 'warning')
            elif new_pw != confirm_pw:
                flash('Passwörter stimmen nicht überein.', 'danger')
            else:
                user.set_password(new_pw)
                db.session.add(user)
                db.session.commit()
                flash('Passwort aktualisiert.', 'success')

            return redirect(url_for('settings_web.settings_home'))

    return render_template(
        'settings/index.html',
        user_preferences=preference_data,
        landlords=[],
        user=user,
        project_profile=load_project_profile(),
    )


@settings_bp.route('/landlords')
@login_required
def landlord_management():
    ensure_user_landlord_flag()
    user = User.query.get(session.get('user_id'))
    landlords = Landlord.query.order_by(Landlord.company_name.asc(), Landlord.last_name.asc()).all()
    return render_template('settings/landlords.html', landlords=landlords, user=user)


@settings_bp.route('/revisions')
@login_required
def revisions_overview():
    user = User.query.get(session.get('user_id'))
    if not user or user.role != 'admin':
        flash('Nur Administratoren dürfen Revisionen einsehen.', 'danger')
        return redirect(url_for('settings_web.settings_home'))

    page = max(int(request.args.get('page', 1)), 1)
    search = (request.args.get('search') or '').strip()
    action_filter = (request.args.get('action') or '').strip()
    table_filter = (request.args.get('table') or '').strip()

    query = RevisionLog.query.outerjoin(User).order_by(RevisionLog.created_at.desc())

    if action_filter:
        query = query.filter(RevisionLog.action == action_filter)

    if table_filter:
        query = query.filter(RevisionLog.table_name == table_filter)

    if search:
        term = f"%{search}%"
        query = query.filter(
            db.or_(
                RevisionLog.table_name.ilike(term),
                RevisionLog.record_id.ilike(term),
                RevisionLog.action.ilike(term),
                RevisionLog.changes.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
            )
        )

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    available_tables = [row[0] for row in db.session.query(RevisionLog.table_name).distinct().order_by(RevisionLog.table_name).all()]
    available_table_labels = {tbl: get_revision_table_label(tbl) for tbl in available_tables}

    return render_template(
        'settings/revisions.html',
        logs=pagination.items,
        pagination=pagination,
        search=search,
        action_filter=action_filter,
        table_filter=table_filter,
        available_tables=available_tables,
        table_labels=available_table_labels,
    )


@settings_bp.route('/revisions/export')
@login_required
def export_revisions():
    user = User.query.get(session.get('user_id'))
    if not user or user.role != 'admin':
        flash('Nur Administratoren dürfen Revisionen exportieren.', 'danger')
        return redirect(url_for('settings_web.revisions_overview'))

    fmt = (request.args.get('format') or 'csv').lower()
    logs = RevisionLog.query.order_by(RevisionLog.created_at.desc()).all()
    data = [
        {
            'Datum': log.created_at.strftime('%d.%m.%Y %H:%M'),
            'Tabelle': get_revision_table_label(log.table_name),
            'Datensatz': log.record_id,
            'Aktion': log.action,
            'Benutzer': f"{log.user.first_name} {log.user.last_name}" if log.user else 'System',
            'Details': log.short_summary,
            'IP': log.ip_address,
        }
        for log in logs
    ]

    df = pd.DataFrame(data)
    filename = f"revisions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if fmt == 'xlsx':
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name=f"{filename}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if fmt == 'pdf':
        html_table = df.to_html(index=False, classes='table table-sm table-striped')
        html = render_template_string(
            """
            <html><head><style>
            body { font-family: DejaVu Sans, Arial, sans-serif; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 6px; font-size: 11px; border: 1px solid #ccc; }
            </style></head><body>
            <h2>Revisionsprotokoll</h2>
            {{ table|safe }}
            </body></html>
            """,
            table=html_table
        )
        pdf_buffer = BytesIO()
        pisa.CreatePDF(html, dest=pdf_buffer)
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True, download_name=f"{filename}.pdf", mimetype='application/pdf')

    # default CSV
    output = BytesIO()
    output.write(df.to_csv(index=False, sep=';').encode('utf-8-sig'))
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"{filename}.csv", mimetype='text/csv')
