from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session
from app.extensions import db
from app.models import RSSFeed, RSSItem, User
import uuid
from datetime import datetime
import feedparser
import html
import ssl
import time

rss_bp = Blueprint('rss', __name__)

# SSL Kontext für Feed-Parsing
if hasattr(ssl, '_create_unverified_context'):
    ssl._create_default_https_context = ssl._create_unverified_context

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Bitte melden Sie sich an.', 'warning')
            return redirect(url_for('auth.web_login'))
        return f(*args, **kwargs)
    return decorated_function

def fetch_feed(feed_url):
    """Holt einen RSS-Feed und gibt die Einträge zurück"""
    try:
        # User-Agent setzen um Blockierung zu vermeiden
        headers = {
            'User-Agent': 'MietAssistent/2.0 (+http://localhost:5000)'
        }
        
        # Feed mit Timeout parsen
        feed = feedparser.parse(feed_url, request_headers=headers)
        
        if feed.bozo:
            print(f"⚠️  Feed parsing error for {feed_url}: {feed.bozo_exception}")
            
        return feed
    except Exception as e:
        print(f"❌ Error fetching feed {feed_url}: {str(e)}")
        return None

def sanitize_html(html_content):
    """Entfernt unsichere HTML-Tags"""
    if not html_content:
        return ""

    # Einfache Entfernung von Script-Tags
    sanitized = html_content.replace('<script', '&lt;script')
    sanitized = sanitized.replace('</script>', '&lt;/script&gt;')
    return sanitized

# ROUTEN MIT /rss PRÄFIX
@rss_bp.route('/')
@login_required
def rss_dashboard():
    """Hauptseite für RSS-Feeds - Jetzt unter /rss erreichbar"""
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        print(f"🔍 DEBUG: Loading RSS dashboard for user {user_id}")
        
        feeds = RSSFeed.query.filter_by(is_active=True).order_by(RSSFeed.name).all()
        print(f"🔍 DEBUG: Found {len(feeds)} active feeds")
        
        # Ungelesene Items zählen
        for feed in feeds:
            feed.unread_count = RSSItem.query.filter_by(feed_id=feed.id, is_read=False).count()
            print(f"🔍 DEBUG: Feed {feed.name} has {feed.unread_count} unread items")
        
        # Letzte Items für Vorschau
        recent_items = RSSItem.query.order_by(RSSItem.published_date.desc()).limit(10).all()
        print(f"🔍 DEBUG: Found {len(recent_items)} recent items")
        
        # VERWENDE DAS RICHTIGE TEMPLATE - main/rss.html
        return render_template('main/rss.html', 
                             user=user,
                             feeds=feeds, 
                             recent_items=recent_items)
    except Exception as e:
        print(f"❌ Error in rss_dashboard: {str(e)}")
        import traceback
        traceback.print_exc()
        flash('Fehler beim Laden der RSS-Feeds', 'danger')
        return render_template('main/rss.html', feeds=[], recent_items=[])

@rss_bp.route('/items')
@login_required
def rss_items():
    """Alle RSS-Items anzeigen - Jetzt unter /rss/items erreichbar"""
    category = request.args.get('category', 'all')
    feed_id = request.args.get('feed_id', 'all')
    show_read = request.args.get('show_read', 'false') == 'true'
    
    # Filter erstellen
    query = RSSItem.query.join(RSSFeed)
    
    if category != 'all':
        query = query.filter(RSSFeed.category == category)
    
    if feed_id != 'all':
        query = query.filter(RSSItem.feed_id == feed_id)
    
    if not show_read:
        query = query.filter(RSSItem.is_read == False)
    
    items = query.order_by(RSSItem.published_date.desc()).all()
    feeds = RSSFeed.query.filter_by(is_active=True).all()
    
    return render_template('rss/items.html', 
                         items=items, 
                         feeds=feeds,
                         selected_category=category,
                         selected_feed=feed_id,
                         show_read=show_read)

@rss_bp.route('/feeds')
@login_required
def manage_feeds():
    """Feed-Verwaltung - Jetzt unter /rss/feeds erreichbar"""
    feeds = RSSFeed.query.order_by(RSSFeed.name).all()
    return render_template('rss/feeds.html', feeds=feeds)

@rss_bp.route('/feeds/add', methods=['GET', 'POST'])
@login_required
def add_feed():
    """Neuen Feed hinzufügen - Jetzt unter /rss/feeds/add erreichbar"""
    if request.method == 'POST':
        try:
            name = request.form['name']
            url = request.form['url']
            category = request.form.get('category', 'general')
            
            # Prüfen ob Feed bereits existiert
            existing_feed = RSSFeed.query.filter_by(url=url).first()
            if existing_feed:
                flash('Dieser Feed existiert bereits!', 'danger')
                return redirect(url_for('rss.manage_feeds'))
            
            # Feed testen
            feed_data = fetch_feed(url)
            if not feed_data or not hasattr(feed_data, 'entries'):
                flash('Ungültiger RSS-Feed oder keine Einträge gefunden!', 'danger')
                return redirect(url_for('rss.manage_feeds'))
            
            # Neuen Feed erstellen
            new_feed = RSSFeed(
                id=str(uuid.uuid4()),
                name=name,
                url=url,
                category=category,
                last_updated=datetime.utcnow()
            )
            
            db.session.add(new_feed)
            db.session.commit()
            
            # Feed-Einträge sofort abrufen
            update_feed_items(new_feed)
            
            flash(f'Feed "{name}" erfolgreich hinzugefügt!', 'success')
            return redirect(url_for('rss.manage_feeds'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Hinzufügen des Feeds: {str(e)}', 'danger')
    
    return render_template('rss/add_feed.html')

@rss_bp.route('/feeds/<feed_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_feed(feed_id):
    """Feed bearbeiten - Jetzt unter /rss/feeds/<feed_id>/edit erreichbar"""
    feed = RSSFeed.query.get_or_404(feed_id)
    
    if request.method == 'POST':
        try:
            feed.name = request.form['name']
            feed.url = request.form['url']
            feed.category = request.form.get('category', 'general')
            feed.is_active = request.form.get('is_active') == 'true'
            feed.update_interval = int(request.form.get('update_interval', 60))
            
            db.session.commit()
            flash('Feed erfolgreich aktualisiert!', 'success')
            return redirect(url_for('rss.manage_feeds'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren: {str(e)}', 'danger')
    
    return render_template('rss/edit_feed.html', feed=feed)

@rss_bp.route('/feeds/<feed_id>/delete', methods=['POST'])
@login_required
def delete_feed(feed_id):
    """Feed löschen - Jetzt unter /rss/feeds/<feed_id>/delete erreichbar"""
    feed = RSSFeed.query.get_or_404(feed_id)
    
    try:
        # Zugehörige Items löschen
        RSSItem.query.filter_by(feed_id=feed_id).delete()
        
        # Feed löschen
        db.session.delete(feed)
        db.session.commit()
        
        flash(f'Feed "{feed.name}" erfolgreich gelöscht!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Löschen: {str(e)}', 'danger')
    
    return redirect(url_for('rss.manage_feeds'))

@rss_bp.route('/feeds/<feed_id>/update', methods=['POST'])
@login_required
def update_feed(feed_id):
    """Feed manuell aktualisieren - Jetzt unter /rss/feeds/<feed_id>/update erreichbar"""
    feed = RSSFeed.query.get_or_404(feed_id)
    
    try:
        success = update_feed_items(feed)
        if success:
            flash(f'Feed "{feed.name}" erfolgreich aktualisiert!', 'success')
        else:
            flash(f'Fehler beim Aktualisieren von "{feed.name}"', 'warning')
    except Exception as e:
        flash(f'Fehler beim Aktualisieren: {str(e)}', 'danger')
    
    return redirect(url_for('rss.manage_feeds'))

@rss_bp.route('/items/<item_id>/mark-read', methods=['POST'])
@login_required
def mark_item_read(item_id):
    """Item als gelesen markieren - Jetzt unter /rss/items/<item_id>/mark-read erreichbar"""
    item = RSSItem.query.get_or_404(item_id)
    
    try:
        item.is_read = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@rss_bp.route('/items/<item_id>/toggle-star', methods=['POST'])
@login_required
def toggle_item_star(item_id):
    """Item als Favorit markieren/entfernen - Jetzt unter /rss/items/<item_id>/toggle-star erreichbar"""
    item = RSSItem.query.get_or_404(item_id)
    
    try:
        item.is_starred = not item.is_starred
        db.session.commit()
        return jsonify({'success': True, 'is_starred': item.is_starred})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@rss_bp.route('/items/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Alle Items als gelesen markieren - Jetzt unter /rss/items/mark-all-read erreichbar"""
    try:
        RSSItem.query.update({'is_read': True})
        db.session.commit()
        flash('Alle Einträge als gelesen markiert!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler: {str(e)}', 'danger')
    
    return redirect(url_for('rss.rss_items'))

@rss_bp.route('/api/items')
@login_required
def api_rss_items():
    """API für RSS-Items (für AJAX) - Jetzt unter /rss/api/items erreichbar"""
    limit = request.args.get('limit', 20, type=int)
    feed_id = request.args.get('feed_id')
    
    query = RSSItem.query
    
    if feed_id and feed_id != 'all':
        query = query.filter_by(feed_id=feed_id)
    
    items = query.order_by(RSSItem.published_date.desc()).limit(limit).all()
    
    return jsonify({
        'items': [item.to_dict() for item in items]
    })

def update_feed_items(feed):
    """Aktualisiert die Items eines Feeds"""
    try:
        feed_data = fetch_feed(feed.url)
        if not feed_data or not hasattr(feed_data, 'entries'):
            return False
        
        new_items_count = 0
        
        for entry in feed_data.entries:
            # Prüfen ob Item bereits existiert
            existing_item = RSSItem.query.filter_by(guid=entry.get('id', entry.link)).first()
            if existing_item:
                continue
            
            # Published date verarbeiten
            published_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                published_date = datetime.fromtimestamp(time.mktime(entry.updated_parsed))
            else:
                published_date = datetime.utcnow()
            
            # Neues Item erstellen
            new_item = RSSItem(
                id=str(uuid.uuid4()),
                feed_id=feed.id,
                title=html.escape(entry.title) if hasattr(entry, 'title') else 'Ohne Titel',
                description=sanitize_html(entry.description) if hasattr(entry, 'description') else '',
                link=entry.link if hasattr(entry, 'link') else '',
                published_date=published_date,
                guid=entry.get('id', entry.link),
                author=entry.get('author', ''),
                categories=','.join([tag.term for tag in entry.tags]) if hasattr(entry, 'tags') else ''
            )
            
            db.session.add(new_item)
            new_items_count += 1
        
        # Feed aktualisieren
        feed.last_updated = datetime.utcnow()
        db.session.commit()
        
        print(f"✅ Updated feed {feed.name}: {new_items_count} new items")
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error updating feed {feed.name}: {str(e)}")
        return False

def update_all_feeds():
    """Aktualisiert alle aktiven Feeds"""
    active_feeds = RSSFeed.query.filter_by(is_active=True).all()
    
    for feed in active_feeds:
        try:
            # Prüfen ob Update notwendig
            if feed.last_updated:
                time_since_update = (datetime.utcnow() - feed.last_updated).total_seconds() / 60
                if time_since_update < feed.update_interval:
                    continue
            
            update_feed_items(feed)
            
        except Exception as e:
            print(f"❌ Error updating feed {feed.name}: {str(e)}")
            continue

def initialize_default_feeds():
    """Initialisiert die Standard-Feeds bei der Installation"""
    # Prüfen ob bereits Feeds existieren
    if RSSFeed.query.count() > 0:
        print("📰 RSS-Feeds bereits initialisiert")
        return
        
    default_feeds = [
        {
            'name': 'BMJ - Mietrecht',
            'url': 'https://www.bmj.de/SiteGlobals/Functions/RSSFeed/RSSNewsfeed/RSSNewsfeed.xml',
            'category': 'mietrecht'
        },
        {
            'name': 'JuraForum - Nachrichten',
            'url': 'https://www.juraforum.de/rss/nachrichten', 
            'category': 'recht'
        },
        {
            'name': 'Haufe Immobilien',
            'url': 'https://feeds.haufe.de/haufe-immobilien',
            'category': 'immobilien'
        },
        {
            'name': 'Haufe Recht',
            'url': 'https://feeds.haufe.de/haufe-recht',
            'category': 'recht'
        },
        {
            'name': 'Mieterbund Presse',
            'url': 'https://www.mieterbund.de/presse/rss.xml',
            'category': 'mietrecht'
        },
        {
            'name': 'Anwalt.de Mietrecht',
            'url': 'https://www.anwalt.de/rss/mietrecht.xml',
            'category': 'mietrecht'
        }
    ]
    
    for feed_data in default_feeds:
        # Prüfen ob Feed bereits existiert
        existing = RSSFeed.query.filter_by(url=feed_data['url']).first()
        if not existing:
            feed = RSSFeed(
                id=str(uuid.uuid4()),
                name=feed_data['name'],
                url=feed_data['url'],
                category=feed_data['category'],
                last_updated=datetime.utcnow()
            )
            db.session.add(feed)
            print(f"✅ Added default feed: {feed_data['name']}")
    
    db.session.commit()
    print("✅ Standard-RSS-Feeds initialisiert")

@rss_bp.route('/debug/db-status')
@login_required
def debug_db_status():
    """Debug-Route um Datenbank-Status anzuzeigen"""
    try:
        feed_count = RSSFeed.query.count()
        item_count = RSSItem.query.count()
        
        return jsonify({
            'feeds_count': feed_count,
            'items_count': item_count,
            'feeds': [{'id': f.id, 'name': f.name, 'url': f.url} for f in RSSFeed.query.all()],
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})
    
@rss_bp.route('/debug/update-all-feeds')
@login_required
def debug_update_all_feeds():
    """Debug-Route um alle Feeds manuell zu aktualisieren"""
    try:
        update_all_feeds()
        flash('Alle Feeds wurden aktualisiert', 'success')
    except Exception as e:
        flash(f'Fehler beim Aktualisieren: {str(e)}', 'danger')
    
    return redirect(url_for('rss.rss_dashboard'))