from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from datetime import datetime
import os
import tempfile
import uuid
from threading import Thread, Lock

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
from app.utils.pdf_generator import generate_pdf_bytes
from app.utils.backup_manager import (
    create_backup_zip,
    import_backup_zip,
    safe_docker_restart,
    validate_backup_zip,
)
from flask import render_template_string

settings_bp = Blueprint('settings_web', __name__, url_prefix='/settings')

backup_jobs = {}
backup_lock = Lock()


def _require_admin(user):
    return user and user.role == 'admin'


def _update_job(job_id, **kwargs):
    with backup_lock:
        if job_id not in backup_jobs:
            return
        backup_jobs[job_id].update(kwargs)


def _start_background_task(target):
    worker = Thread(target=target, daemon=True)
    worker.start()
    return worker


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

        if action == 'toggle_meter_debug' and _require_admin(user):
            preference_data['meter_debug_mode'] = request.form.get('meter_debug_mode') == 'on'
            prefs.preferences = json.dumps(preference_data)
            db.session.commit()
            status = 'aktiviert' if preference_data['meter_debug_mode'] else 'deaktiviert'
            flash(f'Messwert-Debugmodus wurde {status}.', 'info')
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
        pdf_bytes = generate_pdf_bytes(html)
        pdf_buffer = BytesIO(pdf_bytes)
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True, download_name=f"{filename}.pdf", mimetype='application/pdf')

    # default CSV
    output = BytesIO()
    output.write(df.to_csv(index=False, sep=';').encode('utf-8-sig'))
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"{filename}.csv", mimetype='text/csv')


@settings_bp.route('/backup')
@login_required
def backup_overview():
    ensure_user_landlord_flag()
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        flash('Nur Administratoren dürfen Backups verwalten.', 'danger')
        return redirect(url_for('settings_web.settings_home'))

    return render_template('settings/backup.html', user=user)


@settings_bp.route('/backup/export', methods=['POST'])
@login_required
def start_backup_export():
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    job_id = str(uuid.uuid4())
    with backup_lock:
        backup_jobs[job_id] = {
            'type': 'export',
            'status': 'running',
            'progress': 0,
            'file_path': None,
            'error': None,
            'message': 'Backup wird erstellt...'
        }

    app_ctx = current_app._get_current_object()

    def runner():
        with app_ctx.app_context():
            try:
                file_path = create_backup_zip(lambda pct: _update_job(job_id, progress=pct))
                _update_job(job_id, progress=100, status='completed', file_path=file_path, message='Backup erfolgreich erstellt')
                current_app.logger.info('Backup-Export abgeschlossen: %s', file_path)
            except Exception as exc:
                current_app.logger.exception('Fehler beim Backup-Export: %s', exc)
                _update_job(job_id, status='error', error=str(exc))

    _start_background_task(runner)
    return jsonify({'job_id': job_id})


@settings_bp.route('/backup/export/status')
@login_required
def backup_export_status():
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    job_id = request.args.get('job_id')
    job = backup_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Unbekannter Job'}), 404
    return jsonify(job)


@settings_bp.route('/backup/export/download/<job_id>')
@login_required
def backup_export_download(job_id):
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        flash('Nicht autorisiert.', 'danger')
        return redirect(url_for('settings_web.backup_overview'))

    job = backup_jobs.get(job_id)
    if not job or job.get('status') != 'completed' or not job.get('file_path'):
        flash('Backup steht nicht zum Download bereit.', 'warning')
        return redirect(url_for('settings_web.backup_overview'))

    if not os.path.exists(job['file_path']):
        flash('Backup-Datei nicht gefunden.', 'danger')
        return redirect(url_for('settings_web.backup_overview'))

    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(job['file_path'], as_attachment=True, download_name=filename, mimetype='application/zip')


@settings_bp.route('/backup/import', methods=['POST'])
@login_required
def start_backup_import():
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    upload = request.files.get('file')
    if not upload:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    upload.save(tmp_file.name)

    valid, message = validate_backup_zip(tmp_file.name)
    if not valid:
        os.remove(tmp_file.name)
        return jsonify({'error': message}), 400

    job_id = str(uuid.uuid4())
    with backup_lock:
        backup_jobs[job_id] = {
            'type': 'import',
            'status': 'running',
            'progress': 0,
            'error': None,
            'message': 'Backup wird importiert...',
            'restart_required': False
        }

    app_ctx = current_app._get_current_object()

    def runner():
        with app_ctx.app_context():
            try:
                emergency_backup = import_backup_zip(tmp_file.name, lambda pct: _update_job(job_id, progress=pct))
                _update_job(
                    job_id,
                    progress=100,
                    status='completed',
                    message='Backup erfolgreich importiert',
                    restart_required=True,
                    emergency_backup=emergency_backup,
                )
                current_app.logger.info('Backup-Import abgeschlossen: %s', tmp_file.name)
            except Exception as exc:
                current_app.logger.exception('Fehler beim Backup-Import: %s', exc)
                _update_job(job_id, status='error', error=str(exc))
            finally:
                try:
                    os.remove(tmp_file.name)
                except OSError:
                    pass

    _start_background_task(runner)
    return jsonify({'job_id': job_id})


@settings_bp.route('/backup/import/status')
@login_required
def backup_import_status():
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    job_id = request.args.get('job_id')
    job = backup_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Unbekannter Job'}), 404
    return jsonify(job)


@settings_bp.route('/backup/restart', methods=['POST'])
@login_required
def trigger_backup_restart():
    user = User.query.get(session.get('user_id'))
    if not _require_admin(user):
        return jsonify({'error': 'Nicht autorisiert'}), 403

    safe_docker_restart()
    return jsonify({'status': 'restart_scheduled'})
