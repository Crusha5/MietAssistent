import uuid
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app

from app.extensions import db
from app.models import ClauseTemplate
from app.routes.main import login_required


templates_bp = Blueprint('contract_templates', __name__)


def _clean_title(title: str) -> str:
    cleaned = (title or '').lstrip('§').strip()
    if cleaned.startswith(('§', '.')):
        cleaned = cleaned.lstrip('§').lstrip('.').strip()
    return cleaned


def _sanitize_subclauses(raw_subclauses, depth=0, max_depth=6, visited=None):
    """Stellt sicher, dass rekursive Bäume nicht zu Endlosschleifen führen."""
    if not isinstance(raw_subclauses, list) or depth > max_depth:
        return []

    visited = visited or set()
    sanitized = []
    for item in raw_subclauses:
        if not isinstance(item, dict):
            continue

        marker = id(item)
        if marker in visited:
            continue
        visited.add(marker)

        children = item.get('children') if isinstance(item.get('children'), list) else []
        sanitized.append({
            'title': item.get('title') or '',
            'content': item.get('content') or '',
            'children': _sanitize_subclauses(children, depth + 1, max_depth, visited)
        })

    return sanitized


@templates_bp.route('/')
@login_required
def templates_list():
    """Liste aller Klausel-Templates für den Tree-Editor."""
    templates = ClauseTemplate.query.order_by(ClauseTemplate.sort_order, ClauseTemplate.title).all()
    parsed_subclauses = {}
    for tpl in templates:
        try:
            if tpl.variables:
                data = json.loads(tpl.variables)
                parsed_subclauses[tpl.id] = data.get('subclauses', [])
            else:
                parsed_subclauses[tpl.id] = []
        except Exception:
            parsed_subclauses[tpl.id] = []

    return render_template('contract_templates/list.html', templates=templates, subclauses=parsed_subclauses)


@templates_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_template():
    """Neues Klausel-Template erstellen."""
    if request.method == 'POST':
        try:
            title = _clean_title(request.form.get('title'))
            subclauses_raw = request.form.get('subclauses')
            subclauses = []
            if subclauses_raw:
                try:
                    subclauses = json.loads(subclauses_raw)
                except Exception:
                    subclauses = []
            template = ClauseTemplate(
                id=str(uuid.uuid4()),
                name=request.form['name'],
                category=request.form.get('category') or 'allgemein',
                title=title,
                content=request.form.get('content', ''),
                sort_order=int(request.form.get('sort_order') or 0),
                is_active=request.form.get('is_active') == 'on',
                is_mandatory=request.form.get('is_mandatory') == 'on',
                variables=json.dumps({'subclauses': subclauses}, ensure_ascii=False) if subclauses else None,
            )
            db.session.add(template)
            db.session.commit()
            flash('Klausel-Template erstellt und im Tree verfügbar.', 'success')
            return redirect(url_for('contract_templates.templates_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Erstellen: {str(e)}', 'danger')

    return render_template('contract_templates/create.html')


@templates_bp.route('/<template_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_template(template_id):
    template = ClauseTemplate.query.get_or_404(template_id)

    existing_subclauses = []
    if template.variables:
        try:
            existing_subclauses = json.loads(template.variables).get('subclauses', [])
        except Exception:
            existing_subclauses = []

    if request.method == 'POST':
        try:
            template.name = request.form['name']
            template.category = request.form.get('category') or 'allgemein'
            template.title = _clean_title(request.form.get('title'))
            template.content = request.form.get('content', '')
            template.sort_order = int(request.form.get('sort_order') or template.sort_order or 0)
            template.is_active = request.form.get('is_active') == 'on'
            template.is_mandatory = request.form.get('is_mandatory') == 'on'

            subclauses_raw = request.form.get('subclauses')
            if subclauses_raw:
                try:
                    subclauses = json.loads(subclauses_raw)
                except Exception:
                    subclauses = existing_subclauses
            else:
                subclauses = []

            try:
                existing_data = json.loads(template.variables) if template.variables else {}
            except Exception:
                existing_data = {}
            existing_data['subclauses'] = subclauses
            template.variables = json.dumps(existing_data, ensure_ascii=False) if subclauses or existing_data else None
            db.session.commit()
            flash('Template aktualisiert.', 'success')
            return redirect(url_for('contract_templates.templates_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren: {str(e)}', 'danger')

    return render_template('contract_templates/edit.html', template=template, subclauses=existing_subclauses)


@templates_bp.route('/<template_id>/delete', methods=['POST'])
@login_required
def delete_template(template_id):
    template = ClauseTemplate.query.get_or_404(template_id)
    try:
        db.session.delete(template)
        db.session.commit()
        flash('Template gelöscht.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen: {str(e)}', 'danger')
    return redirect(url_for('contract_templates.templates_list'))


@templates_bp.route('/<template_id>/preview')
@login_required
def preview_template(template_id):
    template = ClauseTemplate.query.get_or_404(template_id)
    subclauses = []
    try:
        if template.variables:
            raw = json.loads(template.variables)
            subclauses = _sanitize_subclauses(raw.get('subclauses', []))
    except Exception as exc:
        current_app.logger.error('Fehler in preview_template für %s: %s', template_id, exc, exc_info=True)
        flash('Klausel konnte wegen fehlerhafter Baumstruktur nur teilweise geladen werden.', 'warning')
    return render_template('contract_templates/preview.html', template=template, subclauses=subclauses)
