"""Einfache Benutzerverwaltung mit Admin-Rollenprüfung."""

from flask import Blueprint, abort, session, render_template, request, redirect, url_for, flash

from app.extensions import db
from app.models import User, Landlord
from app.routes.main import login_required
from app.utils.schema_helpers import ensure_user_landlord_flag


users_bp = Blueprint('users', __name__, url_prefix='/users')


def require_admin():
    """Abort, falls kein Admin angemeldet ist."""
    if session.get('role') == 'admin':
        return

    user_id = session.get('user_id')
    if not user_id:
        abort(403)

    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        abort(403)


@users_bp.route('/')
@login_required
def list_users():
    ensure_user_landlord_flag()
    require_admin()
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('users/list.html', users=users)


@users_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_user():
    require_admin()
    ensure_user_landlord_flag()
    landlords = Landlord.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        try:
            user = User(
                username=request.form['username'],
                email=request.form.get('email'),
                role=request.form.get('role') or 'user',
                first_name=request.form.get('first_name'),
                last_name=request.form.get('last_name'),
                phone=request.form.get('phone'),
                is_active=bool(request.form.get('is_active')),
                is_landlord=bool(request.form.get('is_landlord')),
                landlord_id=request.form.get('landlord_id') or None,
            )
            user.set_password(request.form['password'])
            db.session.add(user)
            db.session.commit()
            flash('Benutzer angelegt.', 'success')
            return redirect(url_for('users.list_users'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Benutzer konnte nicht angelegt werden: {exc}', 'danger')
    return render_template('users/edit.html', user=None, landlords=landlords)


@users_bp.route('/<user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    require_admin()
    ensure_user_landlord_flag()
    user = User.query.get_or_404(user_id)
    landlords = Landlord.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        try:
            user.username = request.form.get('username', user.username)
            user.email = request.form.get('email', user.email)
            user.role = request.form.get('role', user.role)
            user.first_name = request.form.get('first_name')
            user.last_name = request.form.get('last_name')
            user.phone = request.form.get('phone')
            user.is_active = bool(request.form.get('is_active'))
            user.is_landlord = bool(request.form.get('is_landlord'))
            user.landlord_id = request.form.get('landlord_id') or None
            new_password = request.form.get('password')
            if new_password:
                user.set_password(new_password)
            db.session.commit()
            flash('Benutzerdaten aktualisiert.', 'success')
            return redirect(url_for('users.list_users'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Daten konnten nicht gespeichert werden: {exc}', 'danger')
    return render_template('users/edit.html', user=user, landlords=landlords)


@users_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def own_profile():
    if 'user_id' not in session:
        abort(403)
    user = User.query.get_or_404(session['user_id'])
    if request.method == 'POST':
        user.first_name = request.form.get('first_name')
        user.last_name = request.form.get('last_name')
        user.phone = request.form.get('phone')
        user.email = request.form.get('email')
        db.session.commit()
        flash('Profil aktualisiert.', 'success')
        return redirect(url_for('users.own_profile'))
    return render_template('users/profile.html', user=user)
