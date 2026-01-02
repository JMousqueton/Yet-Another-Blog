from flask import Flask, render_template, request, make_response, redirect, url_for, g, Response, session, flash, abort, jsonify
import sqlite3
from datetime import datetime
from feedgen.feed import FeedGenerator
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import pytz
import os
from dotenv import load_dotenv
from functools import wraps
from PIL import Image
import io
import markdown
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask_wtf.csrf import CSRFProtect
import re
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-this')
app.config['APP_ID'] = os.getenv('APP_ID', 'multilingual-blog')
app.config['APP_NAME'] = os.getenv('APP_NAME', 'My Multilingual Blog')
app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF tokens don't expire

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Initialize Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Add security headers to all responses
@app.after_request
def add_security_headers(response):
    """Add security headers to prevent XSS, clickjacking, etc."""
    # Content Security Policy
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://platform.twitter.com https://stats.mousqueton.io; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdnjs.cloudflare.com https://maxcdn.bootstrapcdn.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://cdn.jsdelivr.net https://platform.twitter.com https://stats.mousqueton.io; "
        "frame-src https://platform.twitter.com; "
        "frame-ancestors 'none';"
    )
    # Prevent MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    # Enable XSS filter
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Force HTTPS (when in production)
    if not app.debug:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# Markdown filter for Jinja2 templates
@app.template_filter('markdown')
def markdown_filter(text):
    """Convert markdown text to HTML with embed support."""
    if not text:
        return ''
    
    # Process YouTube embeds: [youtube:VIDEO_ID] or full YouTube URLs
    text = re.sub(
        r'\[youtube:([\w-]+)\]',
        r'<div class="embed-responsive embed-responsive-16by9 my-4"><iframe class="embed-responsive-item" src="https://www.youtube.com/embed/\1" allowfullscreen loading="lazy"></iframe></div>',
        text
    )
    text = re.sub(
        r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)',
        r'<div class="embed-responsive embed-responsive-16by9 my-4"><iframe class="embed-responsive-item" src="https://www.youtube.com/embed/\1" allowfullscreen loading="lazy"></iframe></div>',
        text
    )
    
    # Process Twitter/X embeds: [twitter:TWEET_ID] or [x:TWEET_ID]
    text = re.sub(
        r'\[(?:twitter|x):([\w]+)\]',
        r'<blockquote class="twitter-tweet" data-theme="light"><a href="https://twitter.com/x/status/\1"></a></blockquote>',
        text
    )
    # Twitter URLs
    text = re.sub(
        r'https?://(?:twitter\.com|x\.com)/\w+/status/(\d+)',
        r'<blockquote class="twitter-tweet" data-theme="light"><a href="https://twitter.com/x/status/\1"></a></blockquote>',
        text
    )
    
    # Convert markdown to HTML with syntax highlighting
    html = markdown.markdown(text, extensions=[
        'extra',
        'codehilite',
        'nl2br',
        'sane_lists',
        'fenced_code'
    ], extension_configs={
        'codehilite': {
            'css_class': 'highlight',
            'linenums': False
        }
    })
    
    # Add target="_blank" and rel="noopener noreferrer" to all links
    html = re.sub(
        r'<a href=',
        r'<a target="_blank" rel="noopener noreferrer" href=',
        html
    )
    
    return html

# Supported languages
LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇬🇧'},
    'fr': {'name': 'Français', 'flag': '🇫🇷'},
    'de': {'name': 'Deutsch', 'flag': '🇩🇪'}
}

DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', 'en')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'blog.db')
SCHEDULER_INTERVAL = int(os.getenv('SCHEDULER_INTERVAL', '5'))

# Load translations
TRANSLATIONS = {}
LOCALES_DIR = os.path.join(os.path.dirname(__file__), 'locales')

def load_translations():
    """Load all translation files."""
    global TRANSLATIONS
    
    # Ensure English is always available as fallback
    TRANSLATIONS['en'] = {}
    
    for lang_code in LANGUAGES.keys():
        locale_file = os.path.join(LOCALES_DIR, f'{lang_code}.json')
        try:
            with open(locale_file, 'r', encoding='utf-8') as f:
                TRANSLATIONS[lang_code] = json.load(f)
                print(f"✓ Loaded translations for: {lang_code}")
        except FileNotFoundError:
            print(f"⚠️  Warning: Translation file not found: {locale_file}")
            if lang_code != 'en':
                TRANSLATIONS[lang_code] = {}
        except json.JSONDecodeError as e:
            print(f"❌ Error loading {locale_file}: {e}")
            if lang_code != 'en':
                TRANSLATIONS[lang_code] = {}
    
    # Verify English translations loaded successfully
    if not TRANSLATIONS.get('en'):
        print(f"❌ Critical: English translations not loaded! Application may not work correctly.")
    
    print(f"📚 Loaded {len(TRANSLATIONS)} language(s): {', '.join(TRANSLATIONS.keys())}")

# Load translations on startup
load_translations()

# File upload configuration
UPLOAD_FOLDER = os.path.join('static', 'authors')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Create upload folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_author_image(file, author_id):
    """Save and optimize author profile image."""
    if not file or file.filename == '':
        return None
    
    if not allowed_file(file.filename):
        return None
    
    try:
        # Read and optimize image
        img = Image.open(file.stream)
        
        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        # Resize to max 400x400
        img.thumbnail((400, 400), Image.Resampling.LANCZOS)
        
        # Save as optimized JPEG
        filename = f'author_{author_id}.jpg'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        img.save(filepath, 'JPEG', quality=85, optimize=True)
        
        return filename
    except Exception as e:
        print(f"Error saving image: {e}")
        return None

def get_setting(key, default=None):
    """Get a setting value by key."""
    try:
        db = get_db()
        setting = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return setting['value'] if setting else default
    except Exception as e:
        return default

def set_setting(key, value):
    """Set a setting value."""
    try:
        db = get_db()
        db.execute('''
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=?
        ''', (key, value, datetime.now().isoformat(), datetime.now().isoformat()))
        db.commit()
        return True
    except Exception as e:
        print(f"Error setting: {e}")
        return False

@app.context_processor
def inject_global_settings():
    """Inject commonly used settings and translations into all templates."""
    # Get current language with fallback to English
    current_lang = getattr(g, 'language', 'en')
    
    # Ensure language is valid, otherwise use English
    if current_lang not in TRANSLATIONS:
        current_lang = 'en'
    
    # Get translations for current language with double fallback to English
    translations = TRANSLATIONS.get(current_lang, TRANSLATIONS.get('en', {}))
    
    # Get blog title for current language
    blog_title = get_setting(f'blog_title_{current_lang}') or get_setting('blog_title_en') or 'My Blog'
    
    return {
        'global_favicon': get_setting('favicon', 'favicon.ico'),
        'global_template_css': get_setting('template_css', 'default.css'),
        'analytics_code': get_setting('analytics_code', ''),
        'blog_title': blog_title,
        't': translations,
        'lang': current_lang  # Ensure lang is always available in templates
    }

def get_enabled_languages():
    """Get dictionary of enabled languages based on settings."""
    enabled = {}
    for code in LANGUAGES.keys():
        setting_key = f'enabled_lang_{code}'
        if get_setting(setting_key, 'on') == 'on':
            enabled[code] = LANGUAGES[code]
    # Ensure at least one language is enabled
    if not enabled:
        enabled = {'en': LANGUAGES['en']}
    return enabled

# Statistics Helper Functions
def get_post_view_count(post_id):
    """Get total view count for a post."""
    db = get_db()
    result = db.execute('SELECT COUNT(*) as count FROM post_views WHERE post_id = ?', (post_id,)).fetchone()
    return result['count'] if result else 0

def get_most_viewed_posts(limit=10, lang=None):
    """Get most viewed posts with their view counts."""
    db = get_db()
    query = '''
        SELECT p.id, p.title, p.slug, p.language, p.author, 
               COUNT(pv.id) as views
        FROM posts p
        LEFT JOIN post_views pv ON p.id = pv.post_id
        WHERE p.status = 'published'
    '''
    params = []
    
    if lang:
        query += ' AND p.language = ?'
        params.append(lang)
    
    query += ' GROUP BY p.id ORDER BY views DESC LIMIT ?'
    params.append(limit)
    
    return db.execute(query, params).fetchall()

def get_traffic_sources(days=30):
    """Get traffic sources for the last N days."""
    from collections import defaultdict
    db = get_db()
    
    query = '''
        SELECT referrer, COUNT(*) as count
        FROM post_views
        WHERE viewed_at >= datetime('now', '-' || ? || ' days')
        GROUP BY referrer
        ORDER BY count DESC
    '''
    
    results = db.execute(query, (days,)).fetchall()
    
    # Categorize referrers
    sources = defaultdict(int)
    for row in results:
        referrer = row['referrer'] or 'direct'
        
        if 'google' in referrer.lower():
            sources['Google'] += row['count']
        elif 'facebook' in referrer.lower():
            sources['Facebook'] += row['count']
        elif 'twitter' in referrer.lower() or 'x.com' in referrer.lower():
            sources['Twitter/X'] += row['count']
        elif 'linkedin' in referrer.lower():
            sources['LinkedIn'] += row['count']
        elif referrer == 'direct':
            sources['Direct'] += row['count']
        else:
            sources['Other'] += row['count']
    
    return dict(sorted(sources.items(), key=lambda x: x[1], reverse=True))

def get_reading_patterns(days=30):
    """Get hourly distribution of views for the last N days."""
    from collections import defaultdict
    db = get_db()
    
    query = '''
        SELECT strftime('%H', viewed_at) as hour, COUNT(*) as count
        FROM post_views
        WHERE viewed_at >= datetime('now', '-' || ? || ' days')
        GROUP BY hour
        ORDER BY hour
    '''
    
    results = db.execute(query, (days,)).fetchall()
    
    # Create hourly data (0-23)
    patterns = {str(i).zfill(2): 0 for i in range(24)}
    for row in results:
        if row['hour']:
            patterns[row['hour']] = row['count']
    
    return patterns


def get_dashboard_summary(lang=None):
    """Get overall statistics summary."""
    db = get_db()
    
    query = 'SELECT COUNT(*) as total FROM post_views'
    if lang:
        query += ' WHERE language = ?'
        total_views = db.execute(query, (lang,)).fetchone()['total']
    else:
        total_views = db.execute(query).fetchone()['total']
    
    # Get today's views
    today_query = '''
        SELECT COUNT(*) as count FROM post_views
        WHERE DATE(viewed_at) = DATE('now')
    '''
    if lang:
        today_query += ' AND language = ?'
        today_views = db.execute(today_query, (lang,)).fetchone()['count']
    else:
        today_views = db.execute(today_query).fetchone()['count']
    
    return {
        'total_views': total_views,
        'today_views': today_views
    }

def migrate_database():
    """Add missing columns to existing database."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Check if profile_image column exists in authors table
        cursor.execute("PRAGMA table_info(authors)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'profile_image' not in columns:
            cursor.execute("ALTER TABLE authors ADD COLUMN profile_image TEXT")
            conn.commit()
            print("✓ Added profile_image column to authors table")
        
        # Check if featured_image column exists in posts table
        cursor.execute("PRAGMA table_info(posts)")
        posts_columns = [row[1] for row in cursor.fetchall()]
        
        if 'featured_image' not in posts_columns:
            cursor.execute("ALTER TABLE posts ADD COLUMN featured_image TEXT")
            conn.commit()
            print("✓ Added featured_image column to posts table")
        
        # Create settings table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        
        conn.close()
    except Exception as e:
        print(f"Migration info: {e}")

def calculate_reading_time(text):
    """Calculate reading time in minutes based on word count.
    Average reading speed: 200 words per minute."""
    if not text:
        return 1
    # Remove HTML tags for accurate word count
    import re
    clean_text = re.sub('<[^<]+?>', '', text)
    word_count = len(clean_text.split())
    reading_time = max(1, round(word_count / 200))
    return reading_time

def get_db():
    """Get database connection."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

def login_required(f):
    """Decorator to require login for admin routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin privileges."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('admin_login'))
        if not session.get('is_admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.teardown_appcontext
def close_db(error):
    """Close database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def send_email(to_email, subject, body):
    """Send an email using SMTP configuration from .env"""
    smtp_host = os.getenv('SMTP_HOST', 'localhost')
    smtp_port = int(os.getenv('SMTP_PORT', '25'))
    smtp_login = os.getenv('SMTP_LOGIN', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    smtp_from = os.getenv('SMTP_FROM', 'no-reply@example.com')
    
    if not to_email:
        print("No recipient email address provided")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from
        msg['To'] = to_email
        
        msg.attach(MIMEText(body, 'html'))
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_login and smtp_password:
                server.starttls()
                server.login(smtp_login, smtp_password)
            server.send_message(msg)
        
        print(f"Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"Error sending email to {to_email}: {e}")
        return False


def update_scheduled_posts():
    """Update scheduled posts to published if their publish date has passed."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    # Fetch scheduled posts that need to be published
    cursor.execute('''
        SELECT p.id, p.title, p.slug, p.language, p.author, a.email, a.name as author_name
        FROM posts p
        LEFT JOIN authors a ON p.author = a.name
        WHERE p.status = 'scheduled' AND p.publish_date <= ?
    ''', (now,))
    
    posts_to_publish = cursor.fetchall()
    
    # Update posts to published
    cursor.execute('''
        UPDATE posts 
        SET status = 'published', updated_at = ? 
        WHERE status = 'scheduled' AND publish_date <= ?
    ''', (now, now))
    
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    
    # Send email notifications to authors
    if updated > 0:
        print(f"Updated {updated} scheduled post(s) to published")
        
        for post in posts_to_publish:
            if post['email']:
                post_url = f"{request.url_root if hasattr(request, 'url_root') else 'http://localhost:5001/'}{post['language']}/post/{post['slug']}"
                
                subject = f"Your post '{post['title']}' has been published"
                body = f"""
                <html>
                  <body>
                    <h2>Post Published</h2>
                    <p>Hello {post['author_name']},</p>
                    <p>Your scheduled post <strong>{post['title']}</strong> has been automatically published.</p>
                    <p><a href="{post_url}">View your post</a></p>
                    <br>
                    <p>Best regards,<br>{app.config['APP_NAME']}</p>
                  </body>
                </html>
                """
                
                send_email(post['email'], subject, body)

# Run database migrations on app startup
try:
    migrate_database()
    # Add featured column if it doesn't exist
    db = get_db()
    try:
        db.execute("ALTER TABLE posts ADD COLUMN featured INTEGER DEFAULT 0")
        db.commit()
        print("Added 'featured' column to posts table")
    except sqlite3.OperationalError:
        # Column already exists
        pass
except Exception as e:
    print(f"Migration error: {e}")

@app.before_request
def before_request():
    """Handle language detection and routing with English fallback."""
    # Skip for static files, SEO files, admin routes, and set-language route
    if (request.path.startswith('/static') or 
        request.path.startswith('/set-language') or
        request.path.startswith('/admin') or
        request.path in ['/sitemap.xml', '/robots.txt']):
        return
    
    # Check if path starts with language code
    path_parts = request.path.strip('/').split('/')
    if path_parts and path_parts[0] in LANGUAGES:
        g.language = path_parts[0]
    else:
        # Check cookie, fallback to English if invalid
        lang_cookie = request.cookies.get('preferred_language')
        if lang_cookie and lang_cookie in LANGUAGES:
            g.language = lang_cookie
        else:
            # Always fallback to English if no valid language found
            g.language = 'en'
        
        # Redirect to language-specific URL if not already there
        if not path_parts or path_parts[0] not in LANGUAGES:
            return redirect(url_for('index', lang=g.language))

@app.route('/')
def root():
    """Root redirect to default language."""
    lang = request.cookies.get('preferred_language', DEFAULT_LANGUAGE)
    return redirect(url_for('index', lang=lang))

@app.route('/<lang>')
@app.route('/<lang>/page/<int:page>')
@limiter.limit("30 per minute")  # Rate limit search queries
def index(lang, page=1):
    """Blog home page with pagination."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    g.language = lang
    meta_description = get_setting(f'blog_description_{lang}', get_setting('blog_description_en', ''))
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{lang}', get_setting('blog_subtitle_en', ''))
    meta_title = blog_title
    meta_url = request.url
    template_css = get_setting('template_css', 'default.css')
    db = get_db()
    
    # Check for search query
    search_query = request.args.get('q', '').strip()
    
    # Pagination settings
    posts_per_page = 10
    offset = (page - 1) * posts_per_page
    
    # Get published posts for this language
    now = datetime.now().isoformat()
    
    # Get featured posts for homepage (not paginated)
    featured_posts = []
    if page == 1:  # Only show featured posts on first page
        featured_posts_raw = db.execute('''
            SELECT * FROM posts 
            WHERE language = ? AND status = 'published' AND publish_date <= ? AND featured = 1
            ORDER BY publish_date DESC
            LIMIT 3
        ''', (lang, now)).fetchall()
        
        for post in featured_posts_raw:
            post_dict = dict(post)
            post_dict['reading_time'] = calculate_reading_time(post_dict['content'])
            featured_posts.append(post_dict)
    
    if search_query:
        # Count total posts for pagination
        total_count = db.execute('''
            SELECT COUNT(*) as count FROM posts 
            WHERE language = ? AND status = 'published' AND publish_date <= ?
            AND (title LIKE ? OR content LIKE ?)
        ''', (lang, now, f'%{search_query}%', f'%{search_query}%')).fetchone()['count']
        
        # Search in title and content
        posts = db.execute('''
            SELECT * FROM posts 
            WHERE language = ? AND status = 'published' AND publish_date <= ?
            AND (title LIKE ? OR content LIKE ?)
            ORDER BY publish_date DESC
            LIMIT ? OFFSET ?
        ''', (lang, now, f'%{search_query}%', f'%{search_query}%', posts_per_page, offset)).fetchall()
    else:
        # Count total posts for pagination
        total_count = db.execute('''
            SELECT COUNT(*) as count FROM posts 
            WHERE language = ? AND status = 'published' AND publish_date <= ?
        ''', (lang, now)).fetchone()['count']
        
        posts = db.execute('''
            SELECT * FROM posts 
            WHERE language = ? AND status = 'published' AND publish_date <= ?
            ORDER BY publish_date DESC
            LIMIT ? OFFSET ?
        ''', (lang, now, posts_per_page, offset)).fetchall()
    
    # Calculate pagination info
    total_pages = (total_count + posts_per_page - 1) // posts_per_page
    has_prev = page > 1
    has_next = page < total_pages
    prev_page = page - 1 if has_prev else None
    next_page = page + 1 if has_next else None
    
    # Add reading time to each post
    posts_with_reading_time = []
    for post in posts:
        post_dict = dict(post)
        post_dict['reading_time'] = calculate_reading_time(post_dict['content'])
        posts_with_reading_time.append(post_dict)
    
    return render_template('index.html', 
                         posts=posts_with_reading_time,
                         featured_posts=featured_posts,
                         lang=lang, 
                         languages=get_enabled_languages(), 
                         search_query=search_query,
                         current_page=page,
                         total_pages=total_pages,
                         has_prev=has_prev,
                         has_next=has_next,
                         prev_page=prev_page,
                         next_page=next_page,
                         total_count=total_count,
                         meta_description=meta_description,
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_type='website',
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle)

@app.route('/<lang>/post/<slug>')
def post_detail(lang, slug):
    """Individual post page."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    g.language = lang
    meta_description = get_setting(f'blog_description_{lang}', get_setting('blog_description_en', ''))
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{lang}', get_setting('blog_subtitle_en', ''))
    meta_url = request.url
    template_css = get_setting('template_css', 'default.css')
    db = get_db()
    
    # Get post
    now = datetime.now().isoformat()
    post = db.execute('''
        SELECT * FROM posts 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now)).fetchone()
    
    if not post:
        return render_template('404.html', lang=lang, languages=get_enabled_languages(), meta_description=meta_description, meta_title=blog_title, meta_url=meta_url, meta_type='article'), 404

    # Calculate reading time
    post = dict(post)
    post['reading_time'] = calculate_reading_time(post['content'])
    page_meta_description = post.get('excerpt') or meta_description
    meta_title = f"{post['title']} - {blog_title}" if blog_title else post['title']
    meta_image = url_for('static', filename=f"uploads/{post['featured_image']}", _external=True) if post.get('featured_image') else None
    
    # Get author information if available
    author_info = None
    if post.get('author'):
        author_info = db.execute('SELECT * FROM authors WHERE name = ?', (post['author'],)).fetchone()
    
    # Get previous post (older)
    prev_post = db.execute('''
        SELECT id, title, slug FROM posts
        WHERE language = ? AND status = 'published' AND publish_date <= ? AND publish_date < ?
        ORDER BY publish_date DESC
        LIMIT 1
    ''', (lang, now, post['publish_date'])).fetchone()
    
    # Get next post (newer)
    next_post = db.execute('''
        SELECT id, title, slug FROM posts
        WHERE language = ? AND status = 'published' AND publish_date <= ? AND publish_date > ?
        ORDER BY publish_date ASC
        LIMIT 1
    ''', (lang, now, post['publish_date'])).fetchone()
    
    # Track view for statistics (without blocking the response)
    try:
        referrer = request.referrer or 'direct'
        user_agent = request.headers.get('User-Agent', 'unknown')
        db.execute('''
            INSERT INTO post_views (post_id, post_slug, language, referrer, user_agent, viewed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (post['id'], slug, lang, referrer, user_agent, datetime.now().isoformat()))
        db.commit()
    except Exception as e:
        print(f"Error tracking view: {e}")
    
    return render_template('post.html', 
                         post=post, 
                         author=author_info,
                         prev_post=prev_post,
                         next_post=next_post,
                         lang=lang, 
                         languages=get_enabled_languages(), 
                         meta_description=page_meta_description,
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_image=meta_image,
                         meta_type='article',
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle)

@app.route('/<lang>/post/<slug>/amp')
def post_detail_amp(lang, slug):
    """AMP version of individual post page."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    g.language = lang
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    db = get_db()
    
    # Get post
    now = datetime.now().isoformat()
    post = db.execute('''
        SELECT * FROM posts 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now)).fetchone()
    
    if not post:
        abort(404)

    # Calculate reading time
    post = dict(post)
    post['reading_time'] = calculate_reading_time(post['content'])
    
    # Get author information if available
    author_info = None
    if post.get('author'):
        author_info = db.execute('SELECT * FROM authors WHERE name = ?', (post['author'],)).fetchone()
    
    return render_template('post_amp.html', 
                         post=post, 
                         author=author_info,
                         lang=lang,
                         blog_title=blog_title)

@app.route('/rss')
def rss_feed_default():
    """Redirect /rss to /en/rss (default language)."""
    return redirect('/en/rss', code=301)

@app.route('/<lang>/rss')
def rss_feed(lang):
    """Generate RSS feed for the specified language."""
    if lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    db = get_db()
    now = datetime.now().isoformat()
    
    # Get published posts
    posts = db.execute('''
        SELECT * FROM posts 
        WHERE language = ? AND status = 'published' AND publish_date <= ?
        ORDER BY publish_date DESC
        LIMIT 20
    ''', (lang, now)).fetchall()
    
    # Create feed
    fg = FeedGenerator()
    blog_title = get_setting(f'blog_title_{lang}') or get_setting('blog_title_en') or 'My Blog'
    fg.title(f'{blog_title} - {LANGUAGES[lang]["name"]}')
    fg.link(href=request.url_root, rel='alternate')
    fg.description(f'Latest posts from my multilingual blog in {LANGUAGES[lang]["name"]}')
    fg.language(lang)
    
    for post in posts:
        fe = fg.add_entry()
        fe.title(post['title'])
        fe.link(href=request.url_root + f'{lang}/post/{post["slug"]}')
        fe.description(post['excerpt'] or post['content'][:200])
        fe.pubDate(datetime.fromisoformat(post['publish_date']).replace(tzinfo=pytz.UTC))
        if post['author']:
            fe.author({'name': post['author']})
        # Add featured image if available
        if post['featured_image']:
            image_url = request.url_root + f'static/uploads/{post["featured_image"]}'
            fe.enclosure(url=image_url, length='0', type='image/jpeg')
    
    response = make_response(fg.rss_str())
    response.headers['Content-Type'] = 'application/rss+xml; charset=utf-8'
    return response

@app.route('/set-language/<lang>')
def set_language(lang):
    """Set language preference cookie."""
    if lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        lang = DEFAULT_LANGUAGE
    
    # Redirect directly to the language path
    response = make_response(redirect(f'/{lang}'))
    response.set_cookie('preferred_language', lang, max_age=365*24*60*60)  # 1 year
    return response

@app.errorhandler(404)
def page_not_found(e):
    """404 error handler."""
    enabled_languages = get_enabled_languages()
    lang = getattr(g, 'language', DEFAULT_LANGUAGE)
    # Fall back to the first enabled language if the requested one is disabled
    if lang not in enabled_languages:
        lang = next(iter(enabled_languages.keys()), DEFAULT_LANGUAGE)
    # Try to get language-specific title, fall back to English, then to default
    blog_name = get_setting(f'blog_title_{lang}') or get_setting('blog_title_en') or 'My Blog'
    return render_template('404.html', lang=lang, languages=enabled_languages, blog_name=blog_name), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    """429 Too Many Requests error handler."""
    enabled_languages = get_enabled_languages()
    lang = getattr(g, 'language', DEFAULT_LANGUAGE)
    # Fall back to the first enabled language if the requested one is disabled
    if lang not in enabled_languages:
        lang = next(iter(enabled_languages.keys()), DEFAULT_LANGUAGE)
    # Try to get language-specific title, fall back to English, then to default
    blog_name = get_setting(f'blog_title_{lang}') or get_setting('blog_title_en') or 'My Blog'
    return render_template('429.html', lang=lang, languages=enabled_languages, blog_name=blog_name), 429

@app.route('/robots.txt')
def robots():
    """Serve robots.txt for SEO."""
    return Response('''User-agent: *
Allow: /
Allow: /en/
Allow: /fr/
Allow: /de/
Allow: /en/rss
Allow: /fr/rss
Allow: /de/rss
Disallow: /admin/
Disallow: /set-language/

Sitemap: https://''' + request.host + '''/sitemap.xml
''', mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    """Generate XML sitemap for search engines."""
    db = get_db()
    now = datetime.now().isoformat()
    
    # Get all published posts
    posts = db.execute('''
        SELECT slug, language, updated_at FROM posts 
        WHERE status = 'published' AND publish_date <= ?
        ORDER BY updated_at DESC
    ''', (now,)).fetchall()
    
    # Build sitemap XML
    sitemap_urls = []
    
    # Add home pages for each language
    for lang in LANGUAGES:
        sitemap_urls.append({
            'url': f'https://{request.host}/{lang}',
            'updated': datetime.now().isoformat()
        })
    
    # Add post URLs
    for post in posts:
        sitemap_urls.append({
            'url': f'https://{request.host}/{dict(post)["language"]}/post/{dict(post)["slug"]}',
            'updated': dict(post)['updated_at']
        })
    
    # Generate XML
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for entry in sitemap_urls:
        xml += f'  <url>\n'
        xml += f'    <loc>{entry["url"]}</loc>\n'
        xml += f'    <lastmod>{entry["updated"][:10]}</lastmod>\n'
        xml += f'  </url>\n'
    
    xml += '</urlset>'
    
    return Response(xml, mimetype='application/xml')

@app.route('/<lang>/author/<author_name>')
def author_profile(lang, author_name):
    """Author profile page."""
    if lang not in LANGUAGES:
        return redirect(url_for('author_profile', lang=DEFAULT_LANGUAGE, author_name=author_name))
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    g.language = lang
    meta_description = get_setting(f'blog_description_{lang}', get_setting('blog_description_en', ''))
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    meta_url = request.url
    template_css = get_setting('template_css', 'default.css')
    db = get_db()
    
    # Convert URL-friendly name back to actual name (replace hyphens with spaces)
    actual_author_name = author_name.replace('-', ' ')
    
    # Get author info
    author = db.execute('''
        SELECT * FROM authors WHERE name = ?
    ''', (actual_author_name,)).fetchone()
    
    if not author:
        return render_template('404.html', lang=lang, languages=get_enabled_languages(), meta_description=meta_description, meta_title=blog_title, meta_url=meta_url, meta_type='website'), 404
    
    # Get author's published posts in this language
    now = datetime.now().isoformat()
    posts = db.execute('''
        SELECT * FROM posts 
        WHERE author = ? AND language = ? AND status = 'published' AND publish_date <= ?
        ORDER BY publish_date DESC
    ''', (actual_author_name, lang, now)).fetchall()
    
    # Add reading time to posts
    posts_with_reading_time = []
    for post in posts:
        post_dict = dict(post)
        post_dict['reading_time'] = calculate_reading_time(post_dict['content'])
        posts_with_reading_time.append(post_dict)
    
    meta_title = f"Posts by {actual_author_name} - {blog_title}" if blog_title else f"Posts by {actual_author_name}"
    return render_template('author.html', 
                         author=dict(author) if author else None, 
                         posts=posts_with_reading_time,
                         lang=lang, 
                         languages=get_enabled_languages(),
                         meta_description=meta_description,
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_type='website',
                         template_css=template_css,
                         blog_title=blog_title)

# ==================== ADMIN ROUTES ====================

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Prevent brute force attacks
def admin_login():
    """Admin login page."""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        db = get_db()
        user = db.execute('''
            SELECT * FROM authors WHERE email = ?
        ''', (email,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['is_admin'] = bool(int(user['is_admin']))  # normalize to real bool
            flash('Successfully logged in!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    """Logout admin user."""
    session.clear()
    flash('Successfully logged out', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Dashboard (always shows full blog stats)."""
    db = get_db()

    total_posts = db.execute('SELECT COUNT(*) as count FROM posts').fetchone()['count']
    published_posts = db.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'published'").fetchone()['count']
    draft_posts = db.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'draft'").fetchone()['count']
    scheduled_posts = db.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'scheduled'").fetchone()['count']
    recent_posts = db.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT 10").fetchall()

    posts_with_reading_time = []
    for post in recent_posts:
        post_dict = dict(post)
        post_dict['reading_time'] = calculate_reading_time(post_dict['content'])
        posts_with_reading_time.append(post_dict)
    
    return render_template('admin/dashboard.html',
                         total_posts=total_posts,
                         published_posts=published_posts,
                         draft_posts=draft_posts,
                         scheduled_posts=scheduled_posts,
                         recent_posts=posts_with_reading_time,
                         is_admin_user=session.get('is_admin'))

@app.route('/admin/posts')
@login_required
def admin_posts():
    """Admin posts list page."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    
    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    language_filter = request.args.get('language', 'all')
    search_query = request.args.get('q', '').strip()
    
    # Build query
    query = 'SELECT * FROM posts WHERE 1=1'
    params = []
    
    if not is_admin_user:
        query += ' AND author = ?'
        params.append(current_author)
    
    if status_filter != 'all':
        query += ' AND status = ?'
        params.append(status_filter)
    
    if language_filter != 'all':
        query += ' AND language = ?'
        params.append(language_filter)
    
    if search_query:
        query += ' AND (title LIKE ? OR content LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    
    query += ' ORDER BY created_at DESC'
    
    posts = db.execute(query, params).fetchall()
    
    # Add reading time to posts
    posts_with_reading_time = []
    for post in posts:
        post_dict = dict(post)
        post_dict['reading_time'] = calculate_reading_time(post_dict['content'])
        posts_with_reading_time.append(post_dict)
    
    return render_template('admin/posts.html',
                         posts=posts_with_reading_time,
                         status_filter=status_filter,
                         language_filter=language_filter,
                         search_query=search_query,
                         languages=LANGUAGES,
                         is_admin_user=is_admin_user)

@app.route('/admin/posts/delete/<int:post_id>', methods=['POST'])
@login_required
def admin_delete_post(post_id):
    """Delete a post."""
    db = get_db()
    
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        flash('Post not found', 'error')
        return redirect(url_for('admin_posts'))
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and post['author'] != current_author:
        abort(403)
    
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()
    flash(f'Post "{post["title"]}" deleted successfully!', 'success')
    
    return redirect(url_for('admin_posts'))

@app.route('/admin/posts/new', methods=['GET', 'POST'])
@login_required
def admin_new_post():
    """Create a new post."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    
    # Get authors list (restricted for non-admins)
    if is_admin_user:
        authors = db.execute('SELECT name FROM authors ORDER BY name').fetchall()
        authors_list = [dict(a)['name'] for a in authors]
    else:
        authors_list = [current_author] if current_author else []
    
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug')
        content = request.form.get('content')
        excerpt = request.form.get('excerpt')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author
        
        # Validation
        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/new_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form)
        
        # Check if slug already exists for this language
        existing = db.execute('''
            SELECT id FROM posts WHERE slug = ? AND language = ?
        ''', (slug, language)).fetchone()
        
        if existing:
            # Post already exists - redirect to edit page instead
            return redirect(url_for('admin_edit_post', post_id=existing['id']))
        
        # Insert post
        try:
            # Handle featured image upload
            featured_image = None
            if 'featured_image' in request.files:
                file = request.files['featured_image']
                if file and file.filename:
                    filename = secure_filename(f"post_{datetime.now().timestamp()}_{file.filename}")
                    filepath = os.path.join('static', 'uploads', filename)
                    
                    # Create uploads directory if it doesn't exist
                    os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
                    
                    # Save and optimize image
                    try:
                        img = Image.open(file.stream)
                        # Convert RGBA to RGB if necessary
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        # Resize to max 1200px width while maintaining aspect ratio
                        max_width = 1200
                        if img.width > max_width:
                            ratio = max_width / img.width
                            new_height = int(img.height * ratio)
                            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                        img.save(filepath, 'JPEG', quality=85, optimize=True)
                        featured_image = filename
                    except Exception as e:
                        flash(f'Error processing image: {str(e)}', 'warning')
            
            # Handle featured checkbox
            featured = 1 if request.form.get('featured') else 0
            
            db.execute('''
                INSERT INTO posts (title, slug, content, excerpt, language, status, publish_date, author, featured_image, featured, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, slug, content, excerpt, language, status, publish_date, author, featured_image, featured,
                  datetime.now().isoformat(), datetime.now().isoformat()))
            db.commit()
            
            flash(f'Post "{title}" created successfully!', 'success')
            return redirect(url_for('admin_posts'))
        except Exception as e:
            flash(f'Error creating post: {str(e)}', 'error')
            return render_template('admin/new_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form)
    
    # GET request
    return render_template('admin/new_post.html', 
                         languages=LANGUAGES,
                         authors=authors_list,
                         current_user=session.get('user_name'),
                         form_data={})

@app.route('/admin/posts/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_post(post_id):
    """Edit an existing post."""
    db = get_db()
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    
    if not post:
        flash('Post not found', 'error')
        return redirect(url_for('admin_posts'))
    
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    
    # Only admins or the post author can edit
    if not is_admin_user and post['author'] != current_author:
        abort(403)
    
    # Get authors list
    if is_admin_user:
        authors = db.execute('SELECT name FROM authors ORDER BY name').fetchall()
        authors_list = [dict(a)['name'] for a in authors]
    else:
        authors_list = [current_author] if current_author else []
    
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug')
        content = request.form.get('content')
        excerpt = request.form.get('excerpt')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author
        
        # Validation
        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/edit_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 post=post,
                                 form_data=request.form)
        
        # Check if slug already exists for this language (excluding current post)
        existing = db.execute('''
            SELECT id FROM posts WHERE slug = ? AND language = ? AND id != ?
        ''', (slug, language, post_id)).fetchone()
        
        if existing:
            flash(f'A post with slug "{slug}" already exists in {language.upper()}', 'error')
            return render_template('admin/edit_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 post=post,
                                 form_data=request.form)
        
        # Update post
        try:
            # Handle featured image upload
            featured_image = dict(post)['featured_image']  # Keep existing image by default
            if 'featured_image' in request.files:
                file = request.files['featured_image']
                if file and file.filename:
                    filename = secure_filename(f"post_{datetime.now().timestamp()}_{file.filename}")
                    filepath = os.path.join('static', 'uploads', filename)
                    
                    # Create uploads directory if it doesn't exist
                    os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
                    
                    # Save and optimize image
                    try:
                        img = Image.open(file.stream)
                        # Convert any mode to RGB for JPEG compatibility
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        # Resize to max 1200px width while maintaining aspect ratio
                        max_width = 1200
                        if img.width > max_width:
                            ratio = max_width / img.width
                            new_height = int(img.height * ratio)
                            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                        img.save(filepath, 'JPEG', quality=85, optimize=True)
                        featured_image = filename
                    except Exception as e:
                        flash(f'Error processing image: {str(e)}', 'warning')
            
            # Handle featured checkbox
            featured = 1 if request.form.get('featured') else 0
            
            db.execute('''
                UPDATE posts SET 
                    title = ?, slug = ?, content = ?, excerpt = ?, 
                    language = ?, status = ?, publish_date = ?, author = ?, 
                    featured_image = ?, featured = ?, updated_at = ?
                WHERE id = ?
            ''', (title, slug, content, excerpt, language, status, publish_date, author, 
                  featured_image, featured, datetime.now().isoformat(), post_id))
            db.commit()
            
            flash(f'Post "{title}" updated successfully!', 'success')
            return redirect(url_for('admin_posts'))
        except Exception as e:
            flash(f'Error updating post: {str(e)}', 'error')
            return render_template('admin/edit_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 post=post,
                                 form_data=request.form)
    
    # GET request - populate form with post data
    return render_template('admin/edit_post.html', 
                         languages=LANGUAGES,
                         authors=authors_list,
                         current_user=session.get('user_name'),
                         post=post,
                         form_data=post)

@app.route('/admin/media', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_media():
    """Manage media files."""
    uploads_dir = os.path.join('static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    
    if request.method == 'POST':
        # Handle file upload
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename:
                try:
                    filename = secure_filename(f"media_{datetime.now().timestamp()}_{file.filename}")
                    filepath = os.path.join(uploads_dir, filename)
                    
                    # Save and optimize image
                    img = Image.open(file.stream)
                    # Convert RGBA to RGB if necessary
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                    # Resize to max 1200px width while maintaining aspect ratio
                    max_width = 1200
                    if img.width > max_width:
                        ratio = max_width / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                    img.save(filepath, 'JPEG', quality=85, optimize=True)
                    
                    flash('Image uploaded successfully!', 'success')
                except Exception as e:
                    flash(f'Error uploading image: {str(e)}', 'error')
            return redirect(url_for('admin_media'))
    
    # Get all media files
    media_files = []
    try:
        if os.path.exists(uploads_dir):
            for filename in os.listdir(uploads_dir):
                if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    filepath = os.path.join(uploads_dir, filename)
                    file_size = os.path.getsize(filepath)
                    file_size_kb = round(file_size / 1024, 2)
                    # Get file modification time
                    file_mtime = os.path.getmtime(filepath)
                    file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    media_files.append({
                        'filename': filename,
                        'url': url_for('static', filename=f'uploads/{filename}'),
                        'size': file_size_kb,
                        'date': file_date
                    })
            # Sort by date (newest first)
            media_files.sort(key=lambda x: x['filename'], reverse=True)
    except Exception as e:
        flash(f'Error reading media files: {str(e)}', 'error')
    
    return render_template('admin/media.html', media_files=media_files)

@app.route('/admin/media/delete/<filename>', methods=['POST'])
@login_required
@admin_required
def admin_delete_media(filename):
    """Delete a media file."""
    try:
        # Security: ensure filename doesn't contain path traversal
        filename = os.path.basename(filename)
        filepath = os.path.join('static', 'uploads', filename)
        
        # Verify file exists and is in uploads directory
        if os.path.exists(filepath) and os.path.dirname(os.path.abspath(filepath)) == os.path.abspath(os.path.join('static', 'uploads')):
            os.remove(filepath)
            flash('Image deleted successfully!', 'success')
        else:
            flash('File not found', 'error')
    except Exception as e:
        flash(f'Error deleting image: {str(e)}', 'error')
    
    return redirect(url_for('admin_media'))

@app.route('/admin/authors', methods=['GET'])
@login_required
def admin_authors():
    """List authors (admins see all, authors see only themselves)."""
    db = get_db()
    if session.get('is_admin'):
        authors = db.execute('SELECT * FROM authors ORDER BY name').fetchall()
    else:
        authors = db.execute('SELECT * FROM authors WHERE id = ?', (session.get('user_id'),)).fetchall()
    return render_template('admin/authors.html', authors=authors, is_admin_user=session.get('is_admin'))

@app.route('/admin/authors/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_author():
    """Create a new author."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        bio_en = request.form.get('bio_en', '').strip()
        bio_fr = request.form.get('bio_fr', '').strip()
        bio_de = request.form.get('bio_de', '').strip()
        twitter = request.form.get('twitter', '').strip()
        linkedin = request.form.get('linkedin', '').strip()
        github = request.form.get('github', '').strip()
        website = request.form.get('website', '').strip()
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        
        # Validation
        if not all([name, email, password]):
            flash('Name, email, and password are required', 'error')
            return render_template('admin/new_author.html', form_data=request.form)
        
        db = get_db()
        
        # Check if author already exists
        existing = db.execute('SELECT id FROM authors WHERE name = ? OR email = ?', (name, email)).fetchone()
        if existing:
            flash('An author with this name or email already exists', 'error')
            return render_template('admin/new_author.html', form_data=request.form)
        
        # Create author
        try:
            from werkzeug.security import generate_password_hash
            hashed_password = generate_password_hash(password)
            
            db.execute('''
                INSERT INTO authors (name, email, password, is_admin, bio_en, bio_fr, bio_de, twitter, linkedin, github, website)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, email, hashed_password, is_admin, bio_en, bio_fr, bio_de, twitter, linkedin, github, website))
            db.commit()
            
            # Get the new author's ID and save image if provided
            new_author = db.execute('SELECT id FROM authors WHERE name = ?', (name,)).fetchone()
            if new_author and 'profile_image' in request.files:
                file = request.files['profile_image']
                if file and file.filename:
                    image_filename = save_author_image(file, new_author['id'])
                    if image_filename:
                        db.execute('UPDATE authors SET profile_image = ? WHERE id = ?', (image_filename, new_author['id']))
                        db.commit()
            
            flash(f'Author "{name}" created successfully!', 'success')
            return redirect(url_for('admin_authors'))
        except Exception as e:
            flash(f'Error creating author: {str(e)}', 'error')
            return render_template('admin/new_author.html', form_data=request.form)
    
    return render_template('admin/new_author.html', form_data={})

@app.route('/admin/authors/edit/<int:author_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_author(author_id):
    """Edit an author."""
    db = get_db()
    author = db.execute('SELECT * FROM authors WHERE id = ?', (author_id,)).fetchone()
    
    if not author:
        flash('Author not found', 'error')
        return redirect(url_for('admin_authors'))
    # Only admins or the author themselves can edit
    if not session.get('is_admin') and author['id'] != session.get('user_id'):
        abort(403)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        bio_en = request.form.get('bio_en', '').strip()
        bio_fr = request.form.get('bio_fr', '').strip()
        bio_de = request.form.get('bio_de', '').strip()
        twitter = request.form.get('twitter', '').strip()
        linkedin = request.form.get('linkedin', '').strip()
        github = request.form.get('github', '').strip()
        website = request.form.get('website', '').strip()
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        if not session.get('is_admin'):
            is_admin = author['is_admin']  # Non-admins cannot elevate
        
        # Validation
        if not all([name, email]):
            flash('Name and email are required', 'error')
            return render_template('admin/edit_author.html', author=author, form_data=request.form)
        
        # Check if name/email already exists (excluding current author)
        existing = db.execute(
            'SELECT id FROM authors WHERE (name = ? OR email = ?) AND id != ?', 
            (name, email, author_id)
        ).fetchone()
        if existing:
            flash('An author with this name or email already exists', 'error')
            return render_template('admin/edit_author.html', author=author, form_data=request.form)
        
        # Update author
        try:
            if password:
                from werkzeug.security import generate_password_hash
                hashed_password = generate_password_hash(password)
                db.execute('''
                    UPDATE authors SET 
                        name = ?, email = ?, password = ?, is_admin = ?,
                        bio_en = ?, bio_fr = ?, bio_de = ?, 
                        twitter = ?, linkedin = ?, github = ?, website = ?
                    WHERE id = ?
                ''', (name, email, hashed_password, is_admin, bio_en, bio_fr, bio_de, twitter, linkedin, github, website, author_id))
            else:
                db.execute('''
                    UPDATE authors SET 
                        name = ?, email = ?, is_admin = ?,
                        bio_en = ?, bio_fr = ?, bio_de = ?, 
                        twitter = ?, linkedin = ?, github = ?, website = ?
                    WHERE id = ?
                ''', (name, email, is_admin, bio_en, bio_fr, bio_de, twitter, linkedin, github, website, author_id))
            
            # Handle image upload
            if 'profile_image' in request.files:
                file = request.files['profile_image']
                if file and file.filename:
                    image_filename = save_author_image(file, author_id)
                    if image_filename:
                        db.execute('UPDATE authors SET profile_image = ? WHERE id = ?', (image_filename, author_id))
            
            db.commit()
            flash(f'Author "{name}" updated successfully!', 'success')
            return redirect(url_for('admin_authors'))
        except Exception as e:
            flash(f'Error updating author: {str(e)}', 'error')
            return render_template('admin/edit_author.html', author=author, form_data=request.form)
    
    return render_template('admin/edit_author.html', author=author, form_data=author)

@app.route('/admin/authors/delete/<int:author_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_author(author_id):
    """Delete an author."""
    db = get_db()
    author = db.execute('SELECT * FROM authors WHERE id = ?', (author_id,)).fetchone()
    
    if not author:
        flash('Author not found', 'error')
        return redirect(url_for('admin_authors'))
    
    # Don't allow deleting if there are posts by this author
    posts = db.execute('SELECT COUNT(*) as count FROM posts WHERE author = ?', (author['name'],)).fetchone()
    if posts['count'] > 0:
        flash(f'Cannot delete author "{author["name"]}" - they have {posts["count"]} post(s). Delete or reassign posts first.', 'error')
        return redirect(url_for('admin_authors'))
    
    try:
        db.execute('DELETE FROM authors WHERE id = ?', (author_id,))
        db.commit()
        flash(f'Author "{author["name"]}" deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting author: {str(e)}', 'error')
    
    return redirect(url_for('admin_authors'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    """Manage blog settings."""
    if request.method == 'POST':
        try:
            # Save all settings
            settings_map = {
                'blog_title': request.form.get('blog_title', ''),
                'blog_title_en': request.form.get('blog_title_en', ''),
                'blog_title_fr': request.form.get('blog_title_fr', ''),
                'blog_title_de': request.form.get('blog_title_de', ''),
                'blog_subtitle_en': request.form.get('blog_subtitle_en', ''),
                'blog_subtitle_fr': request.form.get('blog_subtitle_fr', ''),
                'blog_subtitle_de': request.form.get('blog_subtitle_de', ''),
                'blog_description_en': request.form.get('blog_description_en', ''),
                'blog_description_fr': request.form.get('blog_description_fr', ''),
                'blog_description_de': request.form.get('blog_description_de', ''),
                'blog_url': request.form.get('blog_url', ''),
                'admin_email': request.form.get('admin_email', ''),
                'contact_email': request.form.get('contact_email', ''),
                'social_twitter': request.form.get('social_twitter', ''),
                'social_linkedin': request.form.get('social_linkedin', ''),
                'social_github': request.form.get('social_github', ''),
                'social_facebook': request.form.get('social_facebook', ''),
                'analytics_code': request.form.get('analytics_code', ''),
                'items_per_page': request.form.get('items_per_page', '10'),
                'template_css': request.form.get('template_css', 'default.css'),
                'enable_comments': 'on' if request.form.get('enable_comments') == 'on' else 'off',
                'enabled_lang_en': 'on' if request.form.get('enabled_lang_en') == 'on' else 'off',
                'enabled_lang_fr': 'on' if request.form.get('enabled_lang_fr') == 'on' else 'off',
                'enabled_lang_de': 'on' if request.form.get('enabled_lang_de') == 'on' else 'off',
            }
            
            for key, value in settings_map.items():
                set_setting(key, value)
            
            # Handle favicon upload
            if 'favicon' in request.files:
                file = request.files['favicon']
                if file and file.filename:
                    # Save favicon
                    filename = secure_filename('favicon.ico')
                    filepath = os.path.join('static', filename)
                    
                    try:
                        # If it's an image, convert to ICO
                        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                            img = Image.open(file.stream)
                            # Convert any mode to RGB for compatibility
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            img = img.resize((32, 32), Image.Resampling.LANCZOS)
                            img.save(filepath, format='ICO')
                        else:
                            file.save(filepath)
                        
                        set_setting('favicon', filename)
                    except Exception as e:
                        flash(f'Error saving favicon: {str(e)}', 'error')
            
            flash('Settings saved successfully!', 'success')
            return redirect(url_for('admin_settings'))
        except Exception as e:
            flash(f'Error saving settings: {str(e)}', 'error')
    
    # Get all settings
    db = get_db()
    settings_rows = db.execute('SELECT key, value FROM settings').fetchall()
    settings = {row['key']: row['value'] for row in settings_rows}
    
    return render_template('admin/settings.html', settings=settings, languages=LANGUAGES)


@app.route('/admin/api/export-database')
@login_required
@admin_required
def api_export_database():
    """Export database to JSON for backup."""
    try:
        db = get_db()
        
        # Get all tables
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        
        export_data = {
            'export_date': datetime.now().isoformat(),
            'tables': {}
        }
        
        # Export each table
        for table_row in tables:
            table_name = table_row['name']
            
            # Get column names
            columns_info = db.execute(f"PRAGMA table_info({table_name})").fetchall()
            columns = [col['name'] for col in columns_info]
            
            # Get all rows
            rows = db.execute(f"SELECT * FROM {table_name}").fetchall()
            
            # Convert to list of dictionaries
            export_data['tables'][table_name] = {
                'columns': columns,
                'rows': [dict(row) for row in rows]
            }
        
        # Convert to JSON
        json_data = json.dumps(export_data, indent=2, default=str)
        
        # Create response with download headers
        response = make_response(json_data)
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=blog_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        return response
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/api/import-database', methods=['POST'])
@login_required
@admin_required
@csrf.exempt
def api_import_database():
    """Import database from JSON backup."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        erase = request.form.get('erase', 'false') == 'true'
        
        # Read JSON data
        try:
            import_data = json.load(file)
        except json.JSONDecodeError:
            return jsonify({'success': False, 'message': 'Invalid JSON file'}), 400
        
        db = get_db()
        
        # If erase option is checked, delete all data from tables
        if erase:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            
            for table_row in tables:
                table_name = table_row['name']
                db.execute(f"DELETE FROM {table_name}")
        
        # Import each table
        imported_count = 0
        for table_name, table_data in import_data.get('tables', {}).items():
            rows = table_data.get('rows', [])
            
            for row in rows:
                columns = list(row.keys())
                values = list(row.values())
                placeholders = ','.join(['?' for _ in columns])
                
                if erase:
                    # Direct insert when erasing
                    db.execute(
                        f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})",
                        values
                    )
                else:
                    # Insert or replace to avoid duplicates
                    db.execute(
                        f"INSERT OR REPLACE INTO {table_name} ({','.join(columns)}) VALUES ({placeholders})",
                        values
                    )
                imported_count += 1
        
        db.commit()
        
        message = f'Successfully imported {imported_count} records'
        if erase:
            message += ' (database was erased first)'
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        print(f"Import error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/statistics')
@login_required
def admin_statistics():
    """Statistics dashboard for blog analytics."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    
    # Get summary
    summary = get_dashboard_summary()
    
    # Get most viewed posts
    most_viewed = get_most_viewed_posts(limit=10)
    most_viewed_list = []
    for post in most_viewed:
        most_viewed_list.append({
            'title': post['title'],
            'slug': post['slug'],
            'language': post['language'],
            'author': post['author'],
            'views': post['views']
        })
    
    # Get traffic sources
    traffic_sources = get_traffic_sources(days=30)
    
    # Get reading patterns (hourly)
    reading_patterns = get_reading_patterns(days=7)
    
    return render_template('admin/statistics.html',
                         summary=summary,
                         most_viewed=most_viewed_list,
                         traffic_sources=traffic_sources,
                         reading_patterns=reading_patterns,
                         languages=LANGUAGES)

@app.route('/admin/api/post-stats/<int:post_id>')
@login_required
def api_post_stats(post_id):
    """Get detailed stats for a specific post."""
    db = get_db()
    
    # Get post details
    post = db.execute('SELECT id, title, slug FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return {'error': 'Post not found'}, 404
    
    views = get_post_view_count(post_id)
    
    # Get last 7 days view trend
    view_trend = db.execute('''
        SELECT DATE(viewed_at) as date, COUNT(*) as count
        FROM post_views
        WHERE post_id = ?
        AND viewed_at >= datetime('now', '-7 days')
        GROUP BY DATE(viewed_at)
        ORDER BY date
    ''', (post_id,)).fetchall()
    
    trend_data = [{'date': row['date'], 'views': row['count']} for row in view_trend]
    
    return {
        'post_id': post['id'],
        'title': post['title'],
        'total_views': views,
        'trend': trend_data
    }

@app.route('/admin/api/autosave', methods=['POST'])
@login_required
@csrf.exempt
def api_autosave():
    """Auto-save post draft to prevent data loss."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
            
        post_id = data.get('post_id')
        title = data.get('title', '').strip()
        content = data.get('content', '').strip()
        slug = data.get('slug', '').strip()
        excerpt = data.get('excerpt', '').strip()
        language = data.get('language', 'en')
        author = data.get('author', session.get('user_name'))
        
        db = get_db()
        current_author = session.get('user_name')
        is_admin_user = bool(session.get('is_admin'))
        
        # Validate minimum data
        if not title and not content:
            return jsonify({'success': False, 'message': 'No content to save'}), 400
        
        # Use a default slug if empty
        if not slug:
            slug = 'untitled-' + datetime.now().strftime('%Y%m%d%H%M%S')
        
        if post_id:
            # Update existing post
            existing = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
            if not existing:
                return jsonify({'success': False, 'message': 'Post not found'}), 404
            
            # Only admins or the post author can update
            if not is_admin_user and existing['author'] != current_author:
                return jsonify({'success': False, 'message': 'Unauthorized'}), 403
            
            db.execute('''
                UPDATE posts 
                SET title = ?, slug = ?, content = ?, excerpt = ?, language = ?, 
                    author = ?, updated_at = ?
                WHERE id = ?
            ''', (title, slug, content, excerpt, language, author, datetime.now().isoformat(), post_id))
            db.commit()
            
            return jsonify({'success': True, 'message': 'Draft saved', 'post_id': post_id})
        else:
            # Create new draft post
            # Check for existing draft with same slug
            existing = db.execute('''
                SELECT id FROM posts WHERE slug = ? AND language = ? AND status = 'draft'
            ''', (slug, language)).fetchone()
            
            if existing:
                # Update existing draft
                db.execute('''
                    UPDATE posts 
                    SET title = ?, content = ?, excerpt = ?, author = ?, updated_at = ?
                    WHERE id = ?
                ''', (title, content, excerpt, author, datetime.now().isoformat(), existing['id']))
                db.commit()
                return jsonify({'success': True, 'message': 'Draft updated', 'post_id': existing['id']})
            else:
                # Create new draft
                cursor = db.execute('''
                    INSERT INTO posts (title, slug, content, excerpt, language, status, 
                                     publish_date, author, created_at, updated_at, featured)
                    VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, 0)
                ''', (title, slug, content, excerpt, language, 
                      datetime.now().isoformat(), author, 
                      datetime.now().isoformat(), datetime.now().isoformat()))
                db.commit()
                
                return jsonify({'success': True, 'message': 'Draft created', 'post_id': cursor.lastrowid})
                
    except Exception as e:
        print(f"Auto-save error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/about')
@login_required
def admin_about():
    """About page for the admin area."""
    repo_url = "https://github.com/JMousqueton/Yet-Another-Blog"
    highlights = [
        {"icon": "fa-language", "title": "Multilingual", "text": "English, French, German with JSON-based i18n and fallbacks."},
        {"icon": "fa-gauge-high", "title": "Performance", "text": "AMP support, lazy-loading images, smooth transitions, and optimized assets."},
        {"icon": "fa-shield-alt", "title": "Security", "text": "CSRF protection, rate limiting, CSP headers, and secure auth."},
        {"icon": "fa-database", "title": "Data Safety", "text": "Export/import scripts, scheduled publishing, and backups."},
        {"icon": "fa-pen", "title": "Authoring", "text": "WYSIWYG editor, featured posts, drafts/scheduled posts, and media."},
        {"icon": "fa-rss", "title": "Reach", "text": "Per-language RSS, SEO metadata, sitemaps, and social sharing."},
    ]
    return render_template('admin/about.html', repo_url=repo_url, highlights=highlights)

# Initialize scheduler for auto-publishing scheduled posts
scheduler = BackgroundScheduler()
scheduler.add_job(func=update_scheduled_posts, trigger="interval", minutes=SCHEDULER_INTERVAL)
scheduler.start()

if __name__ == '__main__':
    # Run update once at startup
    update_scheduled_posts()
    
    # Get configuration from environment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5000'))
    debug = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')
    
    print(f"🚀 Starting {app.config['APP_NAME']} (ID: {app.config['APP_ID']})")
    print(f"📍 Server: http://{host}:{port}")
    print(f"🌍 Languages: {', '.join(LANGUAGES.keys())}")
    print(f"⏰ Auto-publish interval: {SCHEDULER_INTERVAL} minutes")
    
    # Start the app
    app.run(debug=debug, host=host, port=port)
