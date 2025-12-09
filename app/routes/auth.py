from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, flash, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy import func, or_
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])  # ✅ BEIDE METHODEN FÜR WEB LOGIN
def web_login():
    if request.method == 'POST':
        username_input = (request.form.get('username') or '').strip()
        password = request.form.get('password')

        user = None
        if username_input:
            lowered = username_input.lower()
            user = User.query.filter(
                or_(
                    func.lower(User.username) == lowered,
                    func.lower(User.email) == lowered,
                )
            ).first()

        if user and user.is_active is False:
            flash('Dieser Benutzer ist inaktiv und kann sich nicht anmelden. Bitte wenden Sie sich an einen Administrator.', 'danger')
            return render_template('auth/login.html', error='Ihr Konto ist inaktiv.')

        if user and password and user.check_password(password):
            # Session-basierte Authentifizierung für Web
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role or 'user'
            current_app.logger.info(
                f"LOGIN SUCCESS for user {user.id}, session keys: {list(session.keys())}"
            )
            return redirect(url_for('main.dashboard'))
        
        return render_template('auth/login.html', error='Ungültige Anmeldedaten')
    
    return render_template('auth/login.html')

# API Login (für mobile Apps etc.)
@auth_bp.route('/api-login', methods=['POST'])  # ✅ UMGEBENNT FÜR KLARHEIT
def api_login():
    data = request.get_json() or {}

    username_input = (data.get('username') or '').strip()
    password = data.get('password')

    user = None
    if username_input:
        lowered = username_input.lower()
        user = User.query.filter(
            or_(
                func.lower(User.username) == lowered,
                func.lower(User.email) == lowered,
            )
        ).first()

    if user and user.is_active is False:
        return jsonify({'error': 'Konto ist inaktiv. Bitte Administrator kontaktieren.'}), 403

    if user and password and user.check_password(password):
        access_token = create_access_token(identity=str(user.id))
        return jsonify({
            'access_token': access_token,
            'user': {'id': user.id, 'username': user.username}
        })
    
    return jsonify({'error': 'Ungültige Anmeldedaten'}), 401

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.index'))


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    """API-Logout-Endpunkt mit klarer Erfolgsantwort."""
    session.clear()
    return jsonify({'message': 'Successfully logged out'}), 200

@auth_bp.route('/protected')
@jwt_required()
def protected():
    current_user_id = get_jwt_identity()
    user = User.query.get(int(current_user_id))
    return jsonify({'message': f'Hallo {user.username}'})

@auth_bp.route('/status')
def status():
    return jsonify({'status': 'OK', 'service': 'Rental Management API'})