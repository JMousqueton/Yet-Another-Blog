from flask import Flask, render_template, request, make_response, redirect, url_for, g, Response, session, flash, abort, jsonify
import sqlite3
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
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
import pyotp
import qrcode
import base64
import random
import unicodedata

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Trust proxy headers for real client IP and scheme (1 proxy hop)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-this')
app.config['APP_ID'] = os.getenv('APP_ID', 'multilingual-blog')
app.config['APP_NAME'] = os.getenv('APP_NAME', 'My Multilingual Blog')
app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF tokens don't expire

# Session cookie security
app.config['SESSION_COOKIE_SECURE'] = not app.debug  # HTTPS only in production
app.config['SESSION_COOKIE_HTTPONLY'] = True  # No JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection

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

# Word count filter for Jinja2 templates
@app.template_filter('wordcount')
def wordcount_filter(text):
    """Count words in text."""
    if not text:
        return 0
    # Remove HTML tags and count words
    clean_text = re.sub('<[^<]+?>', '', text)
    return len(clean_text.split())

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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

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

def get_disclaimer_page(lang):
    """Return published disclaimer page info for a language if configured."""
    slug = get_setting(f'disclaimer_page_{lang}', '')
    if not slug:
        return None

def normalize_slug(value):
    """Normalize titles/slugs by stripping accents and special chars.

    Handles French and German diacritics (é, è, à, ç, ä, ö, ü, ß -> ss, etc.).
    """
    if not value:
        return ''
    value = value.strip().lower()
    replacements = {
        'ß': 'ss', 'ä': 'a', 'ö': 'o', 'ü': 'u', 'Ä': 'a', 'Ö': 'o', 'Ü': 'u',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'à': 'a', 'â': 'a', 'á': 'a',
        'ç': 'c',
        'î': 'i', 'ï': 'i', 'ì': 'i', 'í': 'i',
        'ô': 'o', 'ò': 'o', 'ó': 'o',
        'ù': 'u', 'û': 'u', 'ú': 'u',
        'ÿ': 'y'
    }
    for src, tgt in replacements.items():
        value = value.replace(src, tgt)
    # Strip remaining accents
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    # Keep alphanumerics and hyphens
    value = re.sub(r'[^a-z0-9]+', '-', value)
    value = value.strip('-')
    return value or 'post'
    try:
        db = get_db()
        page = db.execute('''
            SELECT title, slug
            FROM pages
            WHERE language = ? AND slug = ? AND status = 'published'
        ''', (lang, slug)).fetchone()
        if page:
            return {
                'title': page['title'],
                'slug': page['slug'],
                'url': url_for('page_detail', lang=lang, slug=page['slug'])
            }
    except Exception as e:
        print(f"Error fetching disclaimer page for {lang}: {e}")
    return None

def generate_captcha(lang):
    """Generate a simple addition captcha using number words per language."""
    translations = TRANSLATIONS.get(lang, TRANSLATIONS.get('en', {}))
    lang_words = translations.get('contact', {}).get('captcha_numbers')
    if not lang_words:
        lang_words = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine']
    a = random.randint(1, 4)
    b = random.randint(1, 5)
    prompt = f"{lang_words[a]} + {lang_words[b]} ="
    return prompt, a + b

def get_unread_contact_count():
    """Return count of unread contact messages."""
    try:
        db = get_db()
        row = db.execute('SELECT COUNT(*) as c FROM contact_messages WHERE is_read = 0').fetchone()
        return row['c'] if row else 0
    except Exception as e:
        print(f"Error counting contact messages: {e}")
        return 0

def get_pending_comment_count():
    """Return count of comments awaiting approval."""
    try:
        db = get_db()
        row = db.execute("SELECT COUNT(*) as c FROM comments WHERE status = 'pending'").fetchone()
        return row['c'] if row else 0
    except Exception as e:
        print(f"Error counting pending comments: {e}")
        return 0

@app.context_processor
def inject_global_settings():
    """Inject commonly used settings and translations into all templates."""
    # Try to get language from template context, then URL, then g.language, then cookie, then default
    # Use lang from g, then URL, then cookie, then default
    current_lang = getattr(g, 'language', None)
    if not current_lang:
        path_parts = request.path.strip('/').split('/')
        if path_parts and path_parts[0] in TRANSLATIONS:
            current_lang = path_parts[0]
    if not current_lang:
        current_lang = request.cookies.get('preferred_language')
    if not current_lang or current_lang not in TRANSLATIONS:
        current_lang = 'en'
    translations = TRANSLATIONS.get(current_lang, TRANSLATIONS.get('en', {}))
    blog_title = get_setting(f'blog_title_{current_lang}') or get_setting('blog_title_en') or 'My Blog'
    return {
        'global_favicon': get_setting('favicon', 'favicon.ico'),
        'global_template_css': get_setting('template_css', 'default.css'),
        'analytics_code': get_setting('analytics_code', ''),
        'blog_title': blog_title,
        't': translations,
        'lang': current_lang,
        'disclaimer_page': get_disclaimer_page(current_lang),
        'contact_unread_count': get_unread_contact_count() if session.get('is_admin') else 0,
        'comment_pending_count': get_pending_comment_count() if session.get('is_admin') else 0
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
    other_details = []  # Track individual 'Other' referrers
    
    for row in results:
        referrer = row['referrer'] or 'direct'
        
        if 'google' in referrer.lower():
            sources['Google'] += row['count']
        elif 'bing.com' in referrer.lower():
            sources['Bing'] += row['count']
        elif 'yahoo' in referrer.lower():
            sources['Yahoo'] += row['count']
        elif 'facebook' in referrer.lower():
            sources['Facebook'] += row['count']
        elif 'twitter' in referrer.lower() or 'x.com' in referrer.lower() or 't.co' in referrer.lower():
            sources['Twitter/X'] += row['count']
        elif 'linkedin' in referrer.lower():
            sources['LinkedIn'] += row['count']
        elif 'bsky.app' in referrer.lower():
            sources['Bluesky'] += row['count']
        elif 'yandex.ru' in referrer.lower() or 'yandex.com' in referrer.lower():
            sources['Yandex'] += row['count']
        elif 'duckduckgo' in referrer.lower():
            sources['DuckDuckGo'] += row['count']
        elif 'baidu' in referrer.lower():
            sources['Baidu'] += row['count']
        elif referrer == 'direct':
            sources['Direct'] += row['count']
        else:
            sources['Other'] += row['count']
            other_details.append({'referrer': referrer, 'count': row['count']})
    
    # Sort other_details by count and keep only top 10
    other_details_sorted = sorted(other_details, key=lambda x: x['count'], reverse=True)[:10]
    
    return {
        'sources': dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)),
        'other_details': other_details_sorted
    }

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
    
    # Get last 30 days views
    last_30_days_query = '''
        SELECT COUNT(*) as count FROM post_views
        WHERE DATE(viewed_at) >= DATE('now', '-30 days')
    '''
    if lang:
        last_30_days_query += ' AND language = ?'
        last_30_days_views = db.execute(last_30_days_query, (lang,)).fetchone()['count']
    else:
        last_30_days_views = db.execute(last_30_days_query).fetchone()['count']
    
    return {
        'total_views': total_views,
        'today_views': today_views,
        'last_30_days_views': last_30_days_views
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
        
        if 'totp_secret' not in columns:
            cursor.execute("ALTER TABLE authors ADD COLUMN totp_secret TEXT")
            conn.commit()
            print("✓ Added totp_secret column to authors table")
        
        if 'totp_enabled' not in columns:
            cursor.execute("ALTER TABLE authors ADD COLUMN totp_enabled INTEGER DEFAULT 0")
            conn.commit()
            print("✓ Added totp_enabled column to authors table")
        
        # Check if featured_image column exists in posts table
        cursor.execute("PRAGMA table_info(posts)")
        posts_columns = [row[1] for row in cursor.fetchall()]
        
        if 'featured_image' not in posts_columns:
            cursor.execute("ALTER TABLE posts ADD COLUMN featured_image TEXT")
            conn.commit()
            print("✓ Added featured_image column to posts table")
        
        if 'share_token' not in posts_columns:
            cursor.execute("ALTER TABLE posts ADD COLUMN share_token TEXT")
            conn.commit()
            print("✓ Added share_token column to posts table")

        if 'enable_comments' not in posts_columns:
            cursor.execute("ALTER TABLE posts ADD COLUMN enable_comments INTEGER DEFAULT 0")
            conn.commit()
            print("✓ Added enable_comments column to posts table")
        
        # Create settings table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create pages table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT NOT NULL,
                content TEXT NOT NULL,
                language TEXT NOT NULL CHECK(language IN ('en', 'fr', 'de')),
                status TEXT NOT NULL CHECK(status IN ('draft', 'published', 'scheduled')),
                publish_date DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                author TEXT,
                share_token TEXT,
                UNIQUE(slug, language),
                FOREIGN KEY(author) REFERENCES authors(name)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pages_language_status 
            ON pages(language, status, publish_date)
        ''')
        conn.commit()

        # Add/remove columns in pages table if it already existed
        cursor.execute("PRAGMA table_info(pages)")
        pages_columns = [row[1] for row in cursor.fetchall()]

        if 'share_token' not in pages_columns:
            cursor.execute("ALTER TABLE pages ADD COLUMN share_token TEXT")
            conn.commit()
            print("✓ Added share_token column to pages table")

        if 'author' not in pages_columns:
            cursor.execute("ALTER TABLE pages ADD COLUMN author TEXT")
            conn.commit()
            print("✓ Added author column to pages table")

        # Contact messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contact_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT,
                message TEXT NOT NULL,
                language TEXT NOT NULL CHECK(language IN ('en', 'fr', 'de')),
                is_read INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_contact_messages_lang_read
            ON contact_messages(language, is_read, created_at DESC)
        ''')

        # Comments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                parent_id INTEGER,
                author_name TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')) DEFAULT 'pending',
                language TEXT NOT NULL CHECK(language IN ('en', 'fr', 'de')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id) REFERENCES comments(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_comments_post_status
            ON comments(post_id, status, created_at DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_comments_parent
            ON comments(parent_id)
        ''')

        # Reactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                reaction_type TEXT NOT NULL CHECK(reaction_type IN ('helpful', 'not_helpful')),
                ip_address TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
                UNIQUE(post_id, ip_address)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_reactions_post
            ON reactions(post_id, reaction_type)
        ''')

        # Remove deprecated excerpt column by recreating table without it
        if 'excerpt' in pages_columns:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pages_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    content TEXT NOT NULL,
                    language TEXT NOT NULL CHECK(language IN ('en', 'fr', 'de')),
                    status TEXT NOT NULL CHECK(status IN ('draft', 'published', 'scheduled')),
                    publish_date DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    author TEXT,
                    share_token TEXT,
                    UNIQUE(slug, language),
                    FOREIGN KEY(author) REFERENCES authors(name)
                )
            ''')

            cursor.execute('''
                INSERT INTO pages_new (id, title, slug, content, language, status, publish_date, created_at, updated_at, author, share_token)
                SELECT id, title, slug, content, language, status, publish_date, created_at, updated_at, author, share_token
                FROM pages
            ''')

            cursor.execute('DROP TABLE pages')
            cursor.execute('ALTER TABLE pages_new RENAME TO pages')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_language_status ON pages(language, status, publish_date)')
            conn.commit()
            print("✓ Removed deprecated excerpt column from pages table")

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

def clean_comment_content(text):
    """Strip HTML/markdown-like syntax so only plain text and emojis remain."""
    if not text:
        return ''
    # Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', '', text)
    # Drop common markdown control characters
    cleaned = re.sub(r'[`*_#~>|]', '', cleaned)
    # Normalize whitespace and trim length
    cleaned = re.sub(r'[\r\t]+', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def build_comment_tree(rows):
    """Return a parent->children mapping for approved comments."""
    tree = {}
    for row in rows:
        parent_id = row.get('parent_id')
        tree.setdefault(parent_id, []).append(row)
    return tree

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
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        now = datetime.now(timezone.utc).isoformat()
        print(f"⏰ Scheduler check (UTC) at {now}")
        
        # Fetch scheduled posts that need to be published
        # Use datetime() for proper comparison regardless of format variations
        cursor.execute('''
            SELECT p.id, p.title, p.slug, p.language, p.author, a.email, a.name as author_name
            FROM posts p
            LEFT JOIN authors a ON p.author = a.name
            WHERE p.status = 'scheduled' AND datetime(p.publish_date) <= datetime('now')
        ''')
        
        posts_to_publish = cursor.fetchall()
        print(f"📋 Found {len(posts_to_publish)} post(s) ready to publish")
        
        # Update posts to published
        cursor.execute('''
            UPDATE posts 
            SET status = 'published', updated_at = ? 
            WHERE status = 'scheduled' AND datetime(publish_date) <= datetime('now')
        ''', (now,))
        
        posts_updated = cursor.rowcount

        # Publish scheduled pages
        cursor.execute('''
            SELECT id, title, slug, language
            FROM pages
            WHERE status = 'scheduled' AND datetime(publish_date) <= datetime('now')
        ''')
        pages_to_publish = cursor.fetchall()

        cursor.execute('''
            UPDATE pages
            SET status = 'published', updated_at = ?
            WHERE status = 'scheduled' AND datetime(publish_date) <= datetime('now')
        ''', (now,))

        pages_updated = cursor.rowcount

        conn.commit()
        conn.close()
        
        # Send email notifications to authors
        if posts_updated > 0:
            print(f"✅ Updated {posts_updated} scheduled post(s) to published at {now}")
            
            # Get base URL from environment or use default
            base_url = os.getenv('BASE_URL', 'http://localhost:5001')
            
            for post in posts_to_publish:
                if post['email']:
                    post_url = f"{base_url}/{post['language']}/post/{post['slug']}"
                    
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
        else:
            print(f"⏰ No scheduled posts to publish at {now}")

        if pages_updated > 0:
            print(f"✅ Updated {pages_updated} scheduled page(s) to published at {now}")
        else:
            print(f"⏰ No scheduled pages to publish at {now}")
    except Exception as e:
        print(f"❌ Error in scheduled post publishing: {e}")
        import traceback
        traceback.print_exc()

def purge_old_views():
    """Background task to delete post_views older than 30 days."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM post_views
            WHERE viewed_at < datetime('now', '-30 days')
        ''')
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            print(f"🧹 Purged {deleted_count} post_views entries older than 30 days")
    except Exception as e:
        print(f"❌ Error purging old views: {e}")

# Run database migrations on app startup
with app.app_context():
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
    # Skip for static files, SEO files, admin routes, set-language route, and preview links
    if (request.path.startswith('/static') or 
        request.path.startswith('/set-language') or
        request.path.startswith('/admin') or
        request.path.startswith('/preview/') or
        request.path in ['/sitemap.xml', '/robots.txt', '/rss', '/rss/']):
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
                         meta_keywords=get_setting(f'meta_keywords_{lang}', ''),
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_type='website',
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle,
                         max=max,
                         min=min)

@app.route('/<lang>/post/<slug>')
def post_detail(lang, slug):
    """Individual post page."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    # Check if language is enabled
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    # Auto-set language cookie if not already set
    has_language_cookie = request.cookies.get('preferred_language')
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

    # Comments (only if globally enabled and post allows it)
    comments_enabled_global = get_setting('enable_comments', 'off') == 'on'
    allow_comments = bool(comments_enabled_global and post.get('enable_comments'))
    approved_comments = []
    comment_tree = {}
    if allow_comments:
        approved_comments = db.execute('''
            SELECT id, post_id, parent_id, author_name, content, created_at
            FROM comments
            WHERE post_id = ? AND status = 'approved'
            ORDER BY created_at ASC
        ''', (post['id'],)).fetchall()
        approved_comments = [dict(c) for c in approved_comments]
        comment_tree = build_comment_tree(approved_comments)
    
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
    
    # Track view for statistics (skip internal referrals like julien.io)
    try:
        referrer = request.referrer or 'direct'
        if 'julien.io' not in (referrer or '').lower():
            user_agent = request.headers.get('User-Agent', 'unknown')
            db.execute('''
                INSERT INTO post_views (post_id, post_slug, language, referrer, user_agent, viewed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (post['id'], slug, lang, referrer, user_agent, datetime.now().isoformat()))
            db.commit()
    except Exception as e:
        print(f"Error tracking view: {e}")
    
    # Generate captcha for comment form if comments enabled
    captcha_prompt = None
    if allow_comments:
        prompt, answer = generate_captcha(lang)
        session['comment_captcha_prompt'] = prompt
        session['comment_captcha_answer'] = answer
        captcha_prompt = prompt
    
    # Get reaction counts and user's reaction
    reaction_counts = get_reaction_counts(post['id'])
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()
    user_reaction = get_user_reaction(post['id'], ip_address)
    
    author_tag = TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('post', {}).get('author_label', 'Author')
    # Get prefilled values from query params if present
    author_name_prefill = request.args.get('author_name', '')
    content_prefill = request.args.get('content', '')
    response = make_response(render_template('post.html', 
                         post=post, 
                         author=author_info,
                         prev_post=prev_post,
                         next_post=next_post,
                         allow_comments=allow_comments,
                         comment_tree=comment_tree,
                         comments_count=len(approved_comments),
                         comments_enabled_global=comments_enabled_global,
                         captcha_prompt=captcha_prompt,
                         reaction_counts=reaction_counts,
                         user_reaction=user_reaction,
                         lang=lang, 
                         languages=get_enabled_languages(), 
                         meta_description=page_meta_description,
                         meta_keywords=get_setting(f'meta_keywords_{lang}', ''),
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_image=meta_image,
                         meta_type='article',
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle,
                         author_tag=author_tag,
                         author_name_prefill=author_name_prefill,
                         content_prefill=content_prefill))
    
    # Set language cookie if not already set
    if not has_language_cookie:
        response.set_cookie('preferred_language', lang, max_age=365*24*60*60)  # 1 year
    
    return response

# Bulk approve/delete for comments
@app.route('/admin/comments/bulk-action', methods=['POST'])
@login_required
@admin_required
def admin_bulk_comment_action():
    action = request.form.get('action')
    comment_ids = request.form.getlist('comment_ids')
    if not comment_ids:
        flash('No comments selected.', 'warning')
        return redirect(request.referrer or url_for('admin_comments'))
    db = get_db()
    placeholders = ','.join(['?'] * len(comment_ids))
    if action == 'approve':
        db.execute(f"UPDATE comments SET status = 'approved' WHERE id IN ({placeholders})", comment_ids)
        db.commit()
        flash(f"Approved {len(comment_ids)} comment(s).", 'success')
    elif action == 'delete':
        db.execute(f"DELETE FROM comments WHERE id IN ({placeholders})", comment_ids)
        db.commit()
        flash(f"Deleted {len(comment_ids)} comment(s).", 'success')
    else:
        flash('Invalid action.', 'danger')
    return redirect(request.referrer or url_for('admin_comments'))



@app.route('/<lang>/post/<slug>/comment', methods=['POST'])
@limiter.limit('5 per minute')
def submit_comment(lang, slug):
    # List of unauthorized names (case-insensitive)
    UNAUTHORIZED_NAMES = [
            'admin', 'author', 'auteur', 'administrateur',
            'julien', 'julien mousqueton', 'mousqueton', 'root'
    ]
    """Handle public comment submissions with moderation and threading."""
    if lang not in LANGUAGES:
        abort(404)

    g.language = lang
    translations = TRANSLATIONS.get(lang, TRANSLATIONS.get('en', {}))
    comment_copy = translations.get('comments', {}) if isinstance(translations, dict) else {}

    def msg(key, default):
        return comment_copy.get(key, default) if isinstance(comment_copy, dict) else default

    # Respect global setting
    if get_setting('enable_comments', 'off') != 'on':
        flash(msg('disabled', 'Comments are disabled for this blog.'), 'error')
        return redirect(url_for('post_detail', lang=lang, slug=slug) + '#comments')

    db = get_db()
    now_iso = datetime.now().isoformat()
    post = db.execute('''
        SELECT * FROM posts 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now_iso)).fetchone()

    if not post:
        flash(msg('disabled', 'Comments are disabled for this post.'), 'error')
        return redirect(url_for('post_detail', lang=lang, slug=slug))

    post = dict(post)
    if not post.get('enable_comments'):
        flash(msg('disabled', 'Comments are disabled for this post.'), 'error')
        return redirect(url_for('post_detail', lang=lang, slug=slug))

    # Use admin name if logged in
    if session.get('is_admin') and session.get('user_name'):
        author_name = session['user_name']
    else:
        author_name = (request.form.get('author_name') or '').strip()
    content_raw = request.form.get('content') or ''
    parent_id_raw = request.form.get('parent_id')
    captcha_input = request.form.get('captcha_answer', '').strip()
    expected = session.get('comment_captcha_answer')

    # Validate captcha only for non-admin users
    if not session.get('is_admin'):
        if not (captcha_input.isdigit() and expected is not None and int(captcha_input) == expected):
            flash(msg('error_captcha', 'Captcha is incorrect. Please try again.'), 'error')
            return redirect(url_for('post_detail', lang=lang, slug=slug, author_name=author_name, content=content_raw) + '#comments')


    # Check for unauthorized names and allowed characters (only for non-logged-in users)
    import re
    allowed_name_re = re.compile(r'^[A-Za-z0-9\- ]+$')
    if not session.get('is_admin'):
        if (
            not author_name or
            not content_raw.strip() or
            author_name.lower() in [n.lower() for n in UNAUTHORIZED_NAMES] or
            not allowed_name_re.match(author_name)
        ):
            unauthorized_msg = comment_copy.get('error_unauthorized_name', 'This name is not allowed. Please choose another name.')
            flash(unauthorized_msg, 'error')
            return redirect(url_for('post_detail', lang=lang, slug=slug, author_name=author_name, content=content_raw) + '#comments')
    else:
        if not author_name or not content_raw.strip():
            flash(msg('error_required', 'Name and comment are required.'), 'error')
            return redirect(url_for('post_detail', lang=lang, slug=slug, author_name=author_name, content=content_raw) + '#comments')

    content_clean = clean_comment_content(content_raw)
    if not content_clean:
        flash(msg('error_required', 'Name and comment are required.'), 'error')
        return redirect(url_for('post_detail', lang=lang, slug=slug) + '#comments')

    # Enforce length limit
    if len(content_clean) > 2000:
        content_clean = content_clean[:2000]

    # Validate parent comment belongs to this post and is approved (only reply to visible comments)
    parent_id = None
    if parent_id_raw:
        try:
            candidate_id = int(parent_id_raw)
            parent = db.execute(
                'SELECT id, status FROM comments WHERE id = ? AND post_id = ?',
                (candidate_id, post['id'])
            ).fetchone()
            if parent and parent['status'] == 'approved':
                parent_id = candidate_id
        except ValueError:
            parent_id = None


    # Auto-approve if admin is post author
    status = 'pending'
    if session.get('is_admin') and author_name == post['author']:
        status = 'approved'

    # Prevent duplicate comments: check for same post, author, content, parent, and status 'pending' or 'approved'
    existing = db.execute('''
        SELECT id FROM comments WHERE post_id = ? AND author_name = ? AND content = ? AND IFNULL(parent_id, 0) = IFNULL(?, 0) AND status IN ('pending', 'approved')
    ''', (post['id'], author_name, content_clean, parent_id)).fetchone()
    if existing:
        flash(msg('error_generic', 'Duplicate comment detected.'), 'warning')
    else:
        try:
            db.execute('''
                INSERT INTO comments (post_id, parent_id, author_name, content, status, language, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (post['id'], parent_id, author_name, content_clean, status, lang, datetime.now().isoformat()))
            db.commit()
            if status == 'approved':
                flash(msg('submitted', 'Thank you! Your comment is published.'), 'success')
            else:
                flash(msg('submitted', 'Thank you! Your comment is awaiting moderation.'), 'success')
        except Exception as e:
            print(f"Error saving comment: {e}")
            flash(msg('error_generic', 'Unable to submit your comment right now.'), 'error')

    return redirect(url_for('post_detail', lang=lang, slug=slug) + '#comments')


@app.route('/<lang>/post/<slug>/react', methods=['POST'])
@limiter.limit('10 per minute')
def submit_reaction(lang, slug):
    """Handle helpful/not_helpful reactions for posts."""
    if lang not in LANGUAGES:
        abort(404)

    g.language = lang
    reaction_type = request.form.get('reaction_type')
    
    if reaction_type not in ('helpful', 'not_helpful'):
        return jsonify({'success': False, 'error': 'Invalid reaction type'}), 400

    db = get_db()
    now_iso = datetime.now().isoformat()
    post = db.execute('''
        SELECT id FROM posts 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now_iso)).fetchone()

    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404

    # Get user's IP address
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()

    try:
        # Check if user already voted on this post
        existing = db.execute(
            'SELECT reaction_type FROM reactions WHERE post_id = ? AND ip_address = ?',
            (post['id'], ip_address)
        ).fetchone()

        if existing:
            # Update existing reaction if different
            if existing['reaction_type'] != reaction_type:
                db.execute(
                    'UPDATE reactions SET reaction_type = ?, created_at = ? WHERE post_id = ? AND ip_address = ?',
                    (reaction_type, now_iso, post['id'], ip_address)
                )
                db.commit()
        else:
            # Insert new reaction
            db.execute(
                'INSERT INTO reactions (post_id, reaction_type, ip_address, created_at) VALUES (?, ?, ?, ?)',
                (post['id'], reaction_type, ip_address, now_iso)
            )
            db.commit()

        # Get updated counts
        counts = get_reaction_counts(post['id'])
        return jsonify({'success': True, 'counts': counts})

    except Exception as e:
        print(f"Error saving reaction: {e}")
        return jsonify({'success': False, 'error': 'Unable to save reaction'}), 500


def get_reaction_counts(post_id):
    """Get reaction counts for a post."""
    db = get_db()
    helpful = db.execute(
        'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
        (post_id, 'helpful')
    ).fetchone()['count']
    
    not_helpful = db.execute(
        'SELECT COUNT(*) as count FROM reactions WHERE post_id = ? AND reaction_type = ?',
        (post_id, 'not_helpful')
    ).fetchone()['count']
    
    return {'helpful': helpful, 'not_helpful': not_helpful}


def get_user_reaction(post_id, ip_address):
    """Get user's reaction for a post (if any)."""
    db = get_db()
    reaction = db.execute(
        'SELECT reaction_type FROM reactions WHERE post_id = ? AND ip_address = ?',
        (post_id, ip_address)
    ).fetchone()
    
    return reaction['reaction_type'] if reaction else None


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


@app.route('/<lang>/page/<slug>')
def page_detail(lang, slug):
    """Individual page (no author or navigation)."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    has_language_cookie = request.cookies.get('preferred_language')
    g.language = lang
    meta_description = get_setting(f'blog_description_{lang}', get_setting('blog_description_en', ''))
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{lang}', get_setting('blog_subtitle_en', ''))
    meta_url = request.url
    template_css = get_setting('template_css', 'default.css')
    db = get_db()
    
    now = datetime.now().isoformat()
    page = db.execute('''
        SELECT * FROM pages 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now)).fetchone()
    
    if not page:
        return render_template('404.html', lang=lang, languages=get_enabled_languages(), meta_description=meta_description, meta_title=blog_title, meta_url=meta_url, meta_type='website'), 404

    page = dict(page)
    page['reading_time'] = calculate_reading_time(page['content'])
    page_meta_description = (page.get('content')[:160] if page.get('content') else meta_description)
    meta_title = f"{page['title']} - {blog_title}" if blog_title else page['title']
    meta_image = url_for('static', filename='default-og-image.jpg', _external=True) if os.path.exists(os.path.join('static', 'default-og-image.jpg')) else None
    
    response = make_response(render_template('page.html',
                         page=page,
                         lang=lang,
                         languages=get_enabled_languages(),
                         meta_description=page_meta_description,
                         meta_keywords=get_setting(f'meta_keywords_{lang}', ''),
                         meta_title=meta_title,
                         meta_url=meta_url,
                         meta_image=meta_image,
                         meta_type='website',
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle))

    if not has_language_cookie:
        response.set_cookie('preferred_language', lang, max_age=365*24*60*60)
    
    return response


@app.route('/<lang>/page/<slug>/amp')
def page_detail_amp(lang, slug):
    """AMP version of page."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))
    
    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)
    
    g.language = lang
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    db = get_db()
    
    now = datetime.now().isoformat()
    page = db.execute('''
        SELECT * FROM pages 
        WHERE language = ? AND slug = ? AND status = 'published' AND publish_date <= ?
    ''', (lang, slug, now)).fetchone()
    
    if not page:
        abort(404)

    page = dict(page)
    page['reading_time'] = calculate_reading_time(page['content'])
    
    return render_template('page_amp.html',
                         page=page,
                         lang=lang,
                         blog_title=blog_title)


@app.route('/<lang>/contact', methods=['GET', 'POST'])
def contact(lang):
    """Contact form per language, stores messages for admins."""
    if lang not in LANGUAGES:
        return redirect(url_for('index', lang=DEFAULT_LANGUAGE))

    enabled_languages = get_enabled_languages()
    if lang not in enabled_languages:
        abort(404)

    g.language = lang
    db = get_db()

    t_contact = TRANSLATIONS.get(lang, TRANSLATIONS.get('en', {})).get('contact', {})
    error_required = t_contact.get('error_required', 'Please fill in your name, email, and message.')
    success_msg = t_contact.get('success', 'Message sent! We will get back to you soon.')
    error_generic = t_contact.get('error_generic', 'Error sending message.')
    error_captcha = t_contact.get('error_captcha', 'Captcha is incorrect. Please try again.')

    def new_captcha():
        prompt, answer = generate_captcha(lang)
        session['captcha_prompt'] = prompt
        session['captcha_answer'] = answer
        return prompt

    # Always generate a fresh captcha for each page load
    captcha_prompt = new_captcha()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        captcha_input = request.form.get('captcha_answer', '').strip()
        expected = session.get('captcha_answer')

        if not (captcha_input.isdigit() and expected is not None and int(captcha_input) == expected):
            flash(error_captcha, 'error')
            captcha_prompt = new_captcha()
        elif not all([name, email, message]):
            flash(error_required, 'error')
            captcha_prompt = new_captcha()
        else:
            try:
                db.execute('''
                    INSERT INTO contact_messages (name, email, subject, message, language)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, email, subject, message, lang))
                db.commit()
                admin_email = (get_setting('admin_email', '') or '').strip()
                if admin_email:
                    email_subject = f"[Contact {lang.upper()}] {subject or 'New message'}"
                    email_body = f"""
                        <p>You have received a new contact message.</p>
                        <ul>
                            <li><strong>Name:</strong> {name}</li>
                            <li><strong>Email:</strong> {email}</li>
                            <li><strong>Language:</strong> {lang.upper()}</li>
                            <li><strong>Subject:</strong> {subject or '—'}</li>
                        </ul>
                        <p><strong>Message:</strong></p>
                        <pre style='white-space:pre-wrap;font-family:inherit;'>{message}</pre>
                    """
                    send_email(admin_email, email_subject, email_body)

                flash(success_msg, 'success')
                return redirect(url_for('contact', lang=lang))
            except Exception as e:
                flash(f"{error_generic} {str(e)}", 'error')
                captcha_prompt = new_captcha()

    meta_description = get_setting(f'blog_description_{lang}', get_setting('blog_description_en', ''))
    blog_title = get_setting(f'blog_title_{lang}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{lang}', get_setting('blog_subtitle_en', ''))
    meta_title = f"{blog_title} - Contact"
    meta_url = request.url
    template_css = get_setting('template_css', 'default.css')

    return render_template('contact.html',
                         lang=lang,
                         languages=enabled_languages,
                         template_css=template_css,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle,
                         meta_title=meta_title,
                         meta_description=meta_description,
                         meta_url=meta_url,
                         meta_type='website',
                         captcha_prompt=captcha_prompt,
                         form_data=request.form if request.method == 'POST' else {})

@app.route('/rss')
@app.route('/rss/')
def rss_feed_default():
    """Generate RSS feed aggregating all enabled languages."""
    enabled_languages = get_enabled_languages()
    if not enabled_languages:
        abort(404)
    lang_codes = list(enabled_languages.keys())

    db = get_db()
    now = datetime.now().isoformat()
    placeholders = ','.join(['?'] * len(lang_codes))

    posts = db.execute(f'''
        SELECT p.*, a.email as author_email FROM posts p
        LEFT JOIN authors a ON p.author = a.name
        WHERE p.language IN ({placeholders}) AND p.status = 'published' AND p.publish_date <= ?
        ORDER BY p.publish_date DESC
        LIMIT 50
    ''', (*lang_codes, now)).fetchall()

    fg = FeedGenerator()
    blog_title = get_setting('blog_title_en') or get_setting('blog_title', 'My Blog') or 'My Blog'
    fg.title(f'{blog_title} - All Languages')
    fg.link(href=request.url_root, rel='alternate')
    blog_subtitle = get_setting('blog_subtitle_en', get_setting('blog_subtitle', ''))
    subtitle_plain = re.sub('<[^<]+?>', '', blog_subtitle) if blog_subtitle else ''
    fg.description(subtitle_plain or 'Latest posts from all enabled languages')
    fg.language('en')
    fg.author({'name': blog_title})

    if posts:
        latest_dt = max(datetime.fromisoformat(p['publish_date']) for p in posts)
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=pytz.UTC)
        fg.lastBuildDate(latest_dt)
    else:
        fg.lastBuildDate(datetime.now(pytz.UTC))

    for post in posts:
        fe = fg.add_entry()
        fe.title(post['title'])
        fe.link(href=request.url_root + f"{post['language']}/post/{post['slug']}")
        fe.description(post['excerpt'] or post['content'][:200])
        fe.pubDate(datetime.fromisoformat(post['publish_date']).replace(tzinfo=pytz.UTC))
        # Tag entry with language as category
        fe.category({'term': post['language'].upper()})
        if post['author']:
            fe.author({'name': post['author'], 'email': 'noemail@confidential'})
        if post['featured_image']:
            image_url = request.url_root + f"static/uploads/{post['featured_image']}"
            fe.enclosure(url=image_url, length='0', type='image/jpeg')

    rss_bytes = fg.rss_str()
    response = make_response(rss_bytes)
    response.headers['Content-Type'] = 'application/rss+xml; charset=utf-8'
    return response

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
    
    # Get published posts with author email (if available)
    posts = db.execute('''
        SELECT p.*, a.email as author_email FROM posts p
        LEFT JOIN authors a ON p.author = a.name
        WHERE p.language = ? AND p.status = 'published' AND p.publish_date <= ?
        ORDER BY p.publish_date DESC
        LIMIT 20
    ''', (lang, now)).fetchall()
    
    # Create feed
    fg = FeedGenerator()
    blog_title = get_setting(f'blog_title_{lang}') or get_setting('blog_title_en') or 'My Blog'
    fg.title(f'{blog_title} - {LANGUAGES[lang]["name"]}')
    fg.link(href=request.url_root, rel='alternate')
    blog_subtitle = get_setting(f'blog_subtitle_{lang}', get_setting('blog_subtitle_en', ''))
    subtitle_plain = re.sub('<[^<]+?>', '', blog_subtitle) if blog_subtitle else ''
    fg.description(subtitle_plain or f'Latest posts from my multilingual blog in {LANGUAGES[lang]["name"]}')
    fg.language(lang)
    # Feed-level author tag
    fg.author({'name': blog_title})
    # lastBuildDate based on latest publish date, fallback to now
    if posts:
        latest_dt = max(datetime.fromisoformat(p['publish_date']) for p in posts)
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=pytz.UTC)
        fg.lastBuildDate(latest_dt)
    else:
        fg.lastBuildDate(datetime.now(pytz.UTC))
    
    for post in posts:
        fe = fg.add_entry()
        fe.title(post['title'])
        fe.link(href=request.url_root + f'{lang}/post/{post["slug"]}')
        fe.description(post['excerpt'] or post['content'][:200])
        fe.pubDate(datetime.fromisoformat(post['publish_date']).replace(tzinfo=pytz.UTC))
        if post['author']:
            fe.author({'name': post['author'], 'email': 'noemail@confidential'})
        # Add featured image if available
        if post['featured_image']:
            image_url = request.url_root + f'static/uploads/{post["featured_image"]}'
            fe.enclosure(url=image_url, length='0', type='image/jpeg')
    
    rss_bytes = fg.rss_str()
    response = make_response(rss_bytes)
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
    enabled_languages = get_enabled_languages().keys()
    lines = ["User-agent: *", "Allow: /"]
    for lang in enabled_languages:
        lines.append(f"Allow: /{lang}/")
        lines.append(f"Allow: /{lang}/rss")
    lines.extend([
        "Disallow: /admin/",
        "Disallow: /set-language/",
        "",
        f"Sitemap: https://{request.host}/sitemap.xml"
    ])
    return Response("\n".join(lines), mimetype='text/plain')

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
    
    # Build sitemap XML using only enabled languages
    sitemap_urls = []
    enabled_languages = get_enabled_languages().keys()
    
    # Add home pages for each enabled language
    for lang in enabled_languages:
        sitemap_urls.append({
            'url': f'https://{request.host}/{lang}',
            'updated': datetime.now().isoformat(),
            'changefreq': 'daily',
            'priority': '1.0'
        })
    
    # Add post URLs only for enabled languages
    for post in posts:
        post_lang = dict(post)['language']
        if post_lang in enabled_languages:
            sitemap_urls.append({
                'url': f'https://{request.host}/{post_lang}/post/{dict(post)["slug"]}',
                'updated': dict(post)['updated_at'],
                'changefreq': 'monthly',
                'priority': '0.9'
            })

    # Add pages
    pages = db.execute('''
        SELECT slug, language, updated_at FROM pages 
        WHERE status = 'published' AND publish_date <= ?
        ORDER BY updated_at DESC
    ''', (now,)).fetchall()

    for page in pages:
        page_lang = dict(page)['language']
        if page_lang in enabled_languages:
            sitemap_urls.append({
                'url': f'https://{request.host}/{page_lang}/page/{dict(page)["slug"]}',
                'updated': dict(page)['updated_at'],
                'changefreq': 'yearly',
                'priority': '0.7'
            })
    
    # Generate XML
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for entry in sitemap_urls:
        xml += f'  <url>\n'
        xml += f'    <loc>{entry["url"]}</loc>\n'
        xml += f'    <lastmod>{entry["updated"][:10]}</lastmod>\n'
        xml += f'    <changefreq>{entry["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{entry["priority"]}</priority>\n'
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
                         meta_keywords=get_setting(f'meta_keywords_{lang}', ''),
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
            # Check if 2FA is enabled
            if user['totp_enabled']:
                # Store user_id temporarily for 2FA verification
                session['pending_2fa_user_id'] = user['id']
                session['pending_2fa_user_name'] = user['name']
                session['pending_2fa_user_email'] = user['email']
                session['pending_2fa_is_admin'] = bool(int(user['is_admin']))
                return redirect(url_for('admin_2fa_verify'))
            else:
                # No 2FA, log in directly
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['user_email'] = user['email']
                session['is_admin'] = bool(int(user['is_admin']))
                flash('Successfully logged in!', 'success')
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/2fa-verify', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def admin_2fa_verify():
    """2FA verification page."""
    if 'pending_2fa_user_id' not in session:
        flash('Invalid session. Please log in again.', 'error')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        
        db = get_db()
        user = db.execute('SELECT * FROM authors WHERE id = ?', (session['pending_2fa_user_id'],)).fetchone()
        
        if user and user['totp_secret']:
            totp = pyotp.TOTP(user['totp_secret'])
            if totp.verify(code, valid_window=1):
                # 2FA successful, complete login
                session['user_id'] = session.pop('pending_2fa_user_id')
                session['user_name'] = session.pop('pending_2fa_user_name')
                session['user_email'] = session.pop('pending_2fa_user_email')
                session['is_admin'] = session.pop('pending_2fa_is_admin')
                flash('Successfully logged in with 2FA!', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid 2FA code. Please try again.', 'error')
        else:
            flash('2FA configuration error. Please contact administrator.', 'error')
    
    return render_template('admin/2fa_verify.html')

@app.route('/admin/logout')
def admin_logout():
    """Logout admin user."""
    session.clear()
    flash('Successfully logged out', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/2fa/setup', methods=['GET', 'POST'])
@login_required
def admin_2fa_setup():
    """Setup 2FA for current user."""
    db = get_db()
    user = db.execute('SELECT * FROM authors WHERE id = ?', (session['user_id'],)).fetchone()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'enable':
            # Generate new TOTP secret
            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            
            # Generate QR code
            provisioning_uri = totp.provisioning_uri(
                name=user['email'],
                issuer_name=app.config['APP_NAME']
            )
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            qr_code_data = base64.b64encode(buffered.getvalue()).decode()
            
            # Store secret temporarily in session
            session['temp_totp_secret'] = secret
            
            return render_template('admin/2fa_setup.html',
                                 user=user,
                                 qr_code=qr_code_data,
                                 secret=secret,
                                 setup_step='verify')
        
        elif action == 'verify':
            code = request.form.get('code', '').strip()
            secret = session.get('temp_totp_secret')
            
            if secret:
                totp = pyotp.TOTP(secret)
                if totp.verify(code, valid_window=1):
                    # Save secret and enable 2FA
                    db.execute('''
                        UPDATE authors
                        SET totp_secret = ?, totp_enabled = 1
                        WHERE id = ?
                    ''', (secret, session['user_id']))
                    db.commit()
                    session.pop('temp_totp_secret', None)
                    flash('2FA enabled successfully!', 'success')
                    return redirect(url_for('admin_edit_author', author_id=session['user_id']))
                else:
                    flash('Invalid code. Please try again.', 'error')
                    return redirect(url_for('admin_2fa_setup'))
            else:
                flash('Session expired. Please try again.', 'error')
                return redirect(url_for('admin_2fa_setup'))
        
        elif action == 'disable':
            verify_code = request.form.get('code', '').strip()
            
            if user['totp_secret']:
                totp = pyotp.TOTP(user['totp_secret'])
                if totp.verify(verify_code, valid_window=1):
                    db.execute('''
                        UPDATE authors
                        SET totp_secret = NULL, totp_enabled = 0
                        WHERE id = ?
                    ''', (session['user_id'],))
                    db.commit()
                    flash('2FA disabled successfully!', 'success')
                    return redirect(url_for('admin_edit_author', author_id=session['user_id']))
                else:
                    flash('Invalid code. 2FA not disabled.', 'error')
    
    return render_template('admin/2fa_setup.html', user=user, setup_step='start')

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


@app.route('/admin/pages')
@login_required
def admin_pages():
    """Admin pages list page."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')

    status_filter = request.args.get('status', 'all')
    language_filter = request.args.get('language', 'all')
    search_query = request.args.get('q', '').strip()

    query = 'SELECT * FROM pages WHERE 1=1'
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

    pages = db.execute(query, params).fetchall()

    pages_with_reading_time = []
    for page in pages:
        page_dict = dict(page)
        page_dict['reading_time'] = calculate_reading_time(page_dict['content'])
        pages_with_reading_time.append(page_dict)

    return render_template('admin/pages.html',
                         pages=pages_with_reading_time,
                         status_filter=status_filter,
                         language_filter=language_filter,
                         search_query=search_query,
                         languages=LANGUAGES,
                         is_admin_user=is_admin_user)


@app.route('/admin/contact-messages')
@login_required
@admin_required
def admin_contact_messages():
    """Inbox listing for contact form submissions."""
    db = get_db()
    language_filter = request.args.get('language', 'all')
    status_filter = request.args.get('status', 'all')

    query = 'SELECT * FROM contact_messages WHERE 1=1'
    params = []

    if language_filter != 'all':
        query += ' AND language = ?'
        params.append(language_filter)

    if status_filter == 'unread':
        query += ' AND is_read = 0'
    elif status_filter == 'read':
        query += ' AND is_read = 1'

    query += ' ORDER BY created_at DESC'

    messages = db.execute(query, params).fetchall()

    return render_template('admin/contact_messages.html',
                         messages=messages,
                         languages=LANGUAGES,
                         language_filter=language_filter,
                         status_filter=status_filter)


@app.route('/admin/contact-messages/<int:message_id>')
@login_required
@admin_required
def admin_view_contact_message(message_id):
    """View a single contact message and mark it read."""
    db = get_db()
    message = db.execute('SELECT * FROM contact_messages WHERE id = ?', (message_id,)).fetchone()
    if not message:
        flash('Message not found', 'error')
        return redirect(url_for('admin_contact_messages'))

    if not message['is_read']:
        db.execute('UPDATE contact_messages SET is_read = 1 WHERE id = ?', (message_id,))
        db.commit()

    return render_template('admin/contact_message_detail.html', message=message)


@app.route('/admin/contact-messages/<int:message_id>/mark-unread', methods=['POST'])
@login_required
@admin_required
def admin_mark_contact_unread(message_id):
    db = get_db()
    db.execute('UPDATE contact_messages SET is_read = 0 WHERE id = ?', (message_id,))
    db.commit()
    flash('Message marked as unread', 'success')
    ref = request.referrer or ''
    if '/admin/contact-messages' in ref:
        return redirect(ref)
    return redirect(url_for('admin_contact_messages'))


@app.route('/admin/contact-messages/<int:message_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_contact_message(message_id):
    db = get_db()
    message = db.execute('SELECT id FROM contact_messages WHERE id = ?', (message_id,)).fetchone()
    if not message:
        flash('Message not found', 'error')
        return redirect(url_for('admin_contact_messages'))
    db.execute('DELETE FROM contact_messages WHERE id = ?', (message_id,))
    db.commit()
    flash('Message deleted', 'success')
    return redirect(url_for('admin_contact_messages'))


@app.route('/admin/comments')
@login_required
@admin_required
def admin_comments():
    """Moderate public comments."""
    status = request.args.get('status', 'pending')
    db = get_db()

    query = '''
        SELECT c.*, p.title as post_title, p.slug as post_slug, p.language as post_language, p.author as post_author
        FROM comments c
        JOIN posts p ON c.post_id = p.id
    '''
    params = []

    if status != 'all':
        query += ' WHERE c.status = ?'
        params.append(status)

    query += ' ORDER BY c.created_at DESC LIMIT 200'

    comments = db.execute(query, params).fetchall()

    # Get translation for 'author' tag in the current language (fallback to English)
    lang = comments[0]['post_language'] if comments else 'en'
    author_tag = TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('author', {}).get('author', 'author')
    return render_template('admin/comments.html', comments=comments, status=status, author_tag=author_tag)


@app.route('/admin/comments/<int:comment_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_comment(comment_id):
    db = get_db()
    # Only approve if the comment is still pending
    updated = db.execute("UPDATE comments SET status = 'approved' WHERE id = ? AND status = 'pending'", (comment_id,)).rowcount
    db.commit()
    if updated:
        flash('Comment approved and published', 'success')
    else:
        # If not updated, check if it exists and is already approved
        row = db.execute("SELECT status FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if row and row['status'] == 'approved':
            flash('Comment is already approved.', 'info')
        else:
            flash('Comment not found', 'error')

    ref = request.referrer or url_for('admin_comments')
    return redirect(ref)


@app.route('/admin/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_comment(comment_id):
    db = get_db()
    deleted = db.execute('DELETE FROM comments WHERE id = ?', (comment_id,)).rowcount
    db.commit()
    if deleted:
        flash('Comment deleted', 'success')
    else:
        flash('Comment not found', 'error')
    ref = request.referrer or url_for('admin_comments')
    return redirect(ref)

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


@app.route('/admin/pages/delete/<int:page_id>', methods=['POST'])
@login_required
def admin_delete_page(page_id):
    """Delete a page."""
    db = get_db()

    page = db.execute('SELECT * FROM pages WHERE id = ?', (page_id,)).fetchone()
    if not page:
        flash('Page not found', 'error')
        return redirect(url_for('admin_pages'))

    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and page['author'] != current_author:
        abort(403)

    db.execute('DELETE FROM pages WHERE id = ?', (page_id,))
    db.commit()
    flash(f'Page "{page["title"]}" deleted successfully!', 'success')

    return redirect(url_for('admin_pages'))

@app.route('/admin/posts/<int:post_id>/generate-share-link', methods=['POST'])
@login_required
def admin_generate_share_link(post_id):
    """Generate a shareable preview link for a draft post."""
    db = get_db()
    
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    
    # Check permissions
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and post['author'] != current_author:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Generate unique token
    import secrets
    share_token = secrets.token_urlsafe(32)
    
    # Update post with share token
    db.execute('UPDATE posts SET share_token = ? WHERE id = ?', (share_token, post_id))
    db.commit()
    
    # Return the preview URL - use absolute URL
    preview_url = request.url_root.rstrip('/') + f'/preview/{share_token}'
    return jsonify({'success': True, 'preview_url': preview_url})


@app.route('/admin/pages/<int:page_id>/generate-share-link', methods=['POST'])
@login_required
def admin_generate_page_share_link(page_id):
    """Generate a shareable preview link for a draft page."""
    db = get_db()

    page = db.execute('SELECT * FROM pages WHERE id = ?', (page_id,)).fetchone()
    if not page:
        return jsonify({'success': False, 'error': 'Page not found'}), 404

    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and page['author'] != current_author:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    import secrets
    share_token = secrets.token_urlsafe(32)

    db.execute('UPDATE pages SET share_token = ? WHERE id = ?', (share_token, page_id))
    db.commit()

    preview_url = request.url_root.rstrip('/') + f'/preview/page/{share_token}'
    return jsonify({'success': True, 'preview_url': preview_url})

@app.route('/preview/<token>')
def preview_post(token):
    """Display a post preview using share token."""
    if not token or len(token) < 10:
        abort(404)
    
    db = get_db()
    
    post = db.execute('SELECT * FROM posts WHERE share_token = ?', (token,)).fetchone()
    if not post:
        abort(404)
    
    # Get author info
    author = None
    if post['author']:
        author = db.execute('SELECT * FROM authors WHERE name = ?', (post['author'],)).fetchone()
    
    # Get settings
    template_css = get_setting('template_css', 'default.css')
    blog_title = get_setting(f'blog_title_{post["language"]}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{post["language"]}', get_setting('blog_subtitle_en', ''))
    
    # Get meta image
    meta_image = None
    if post['featured_image']:
        meta_image = request.url_root + f"static/uploads/{post['featured_image']}"
    
    g.language = post['language']
    
    return render_template('post_preview.html',
                         post=post,
                         author=author,
                         lang=post['language'],
                         meta_description=post['excerpt'] or (post['content'][:160] if post['content'] else ''),
                         meta_image=meta_image,
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle,
                         template_css=template_css,
                         languages=LANGUAGES,
                         is_preview=True)


@app.route('/preview/page/<token>')
def preview_page(token):
    """Display a page preview using share token."""
    if not token or len(token) < 10:
        abort(404)

    db = get_db()

    page = db.execute('SELECT * FROM pages WHERE share_token = ?', (token,)).fetchone()
    if not page:
        abort(404)

    template_css = get_setting('template_css', 'default.css')
    blog_title = get_setting(f'blog_title_{page["language"]}', get_setting('blog_title', 'My Blog'))
    blog_subtitle = get_setting(f'blog_subtitle_{page["language"]}', get_setting('blog_subtitle_en', ''))

    g.language = page['language']
    page = dict(page)
    page['reading_time'] = calculate_reading_time(page['content'])

    return render_template('page_preview.html',
                         page=page,
                         lang=page['language'],
                         meta_description=(page['content'][:160] if page['content'] else ''),
                         blog_title=blog_title,
                         blog_subtitle=blog_subtitle,
                         template_css=template_css,
                         languages=LANGUAGES,
                         is_preview=True)

@app.route('/admin/posts/<int:post_id>/publish-now', methods=['POST'])
@login_required
def admin_publish_now(post_id):
    """Publish a draft post immediately."""
    db = get_db()
    
    post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    
    # Check permissions
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and post['author'] != current_author:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Update post status to published with current date/time
    current_datetime = datetime.now().isoformat()
    db.execute('UPDATE posts SET status = ?, publish_date = ? WHERE id = ?',
               ('published', current_datetime, post_id))
    db.commit()
    
    return jsonify({'success': True, 'message': 'Post published successfully'})


@app.route('/admin/pages/<int:page_id>/publish-now', methods=['POST'])
@login_required
def admin_publish_page_now(page_id):
    """Publish a draft page immediately."""
    db = get_db()

    page = db.execute('SELECT * FROM pages WHERE id = ?', (page_id,)).fetchone()
    if not page:
        return jsonify({'success': False, 'error': 'Page not found'}), 404

    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    if not is_admin_user and page['author'] != current_author:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    current_datetime = datetime.now().isoformat()
    db.execute('UPDATE pages SET status = ?, publish_date = ? WHERE id = ?',
               ('published', current_datetime, page_id))
    db.commit()

    return jsonify({'success': True, 'message': 'Page published successfully'})

@app.route('/admin/posts/new', methods=['GET', 'POST'])
@login_required
def admin_new_post():
    """Create a new post."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')
    comments_global_on = get_setting('enable_comments', 'off') == 'on'
    
    # Get authors list (restricted for non-admins)
    if is_admin_user:
        authors = db.execute('SELECT name FROM authors ORDER BY name').fetchall()
        authors_list = [dict(a)['name'] for a in authors]
    else:
        authors_list = [current_author] if current_author else []
    
    if request.method == 'POST':
        title = request.form.get('title')
        slug = normalize_slug(request.form.get('slug') or title)
        content = request.form.get('content')
        excerpt = request.form.get('excerpt')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author
        enable_comments = 1 if request.form.get('enable_comments') else 0
        
        # Validation
        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/new_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form,
                                 form_enable_comments=enable_comments,
                                 global_comments_on=comments_global_on)
        
        # Check if slug already exists for this language
        existing = db.execute('''
            SELECT * FROM posts WHERE slug = ? AND language = ?
        ''', (slug, language)).fetchone()
        
        if existing:
            # If the post already exists (e.g., a draft), update it with new data instead of creating a duplicate
            try:
                featured_image = existing['featured_image']
                if 'featured_image' in request.files:
                    file = request.files['featured_image']
                    if file and file.filename:
                        filename = secure_filename(f"post_{datetime.now().timestamp()}_{file.filename}")
                        filepath = os.path.join('static', 'uploads', filename)
                        os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
                        try:
                            img = Image.open(file.stream)
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            max_width = 1200
                            if img.width > max_width:
                                ratio = max_width / img.width
                                new_height = int(img.height * ratio)
                                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                            img.save(filepath, 'JPEG', quality=85, optimize=True)
                            featured_image = filename
                        except Exception as e:
                            flash(f'Error processing image: {str(e)}', 'warning')
                featured = 1 if request.form.get('featured') else 0
                db.execute('''
                    UPDATE posts SET 
                        title = ?, slug = ?, content = ?, excerpt = ?, language = ?, status = ?, publish_date = ?, author = ?, featured_image = ?, featured = ?, enable_comments = ?, updated_at = ?
                    WHERE id = ?
                ''', (title, slug, content, excerpt, language, status, publish_date, author, featured_image, featured, enable_comments, datetime.now().isoformat(), existing['id']))
                db.commit()
                flash(f'Post "{title}" updated successfully!', 'success')
                return redirect(url_for('admin_edit_post', post_id=existing['id']))
            except Exception as e:
                flash(f'Error updating post: {str(e)}', 'error')
                return render_template('admin/new_post.html', 
                                     languages=LANGUAGES,
                                     authors=authors_list,
                                     current_user=session.get('user_name'),
                                     form_data=request.form,
                                     form_enable_comments=enable_comments,
                                     global_comments_on=comments_global_on)
        
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
                INSERT INTO posts (title, slug, content, excerpt, language, status, publish_date, author, featured_image, featured, enable_comments, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, slug, content, excerpt, language, status, publish_date, author, featured_image, featured, enable_comments,
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
                                 form_data=request.form,
                                 form_enable_comments=enable_comments,
                                 global_comments_on=comments_global_on)
    
    # GET request
    form_enable_comments = 1 if comments_global_on else 0
    return render_template('admin/new_post.html', 
                         languages=LANGUAGES,
                         authors=authors_list,
                         current_user=session.get('user_name'),
                         form_data={},
                         form_enable_comments=form_enable_comments,
                         global_comments_on=comments_global_on)


@app.route('/admin/pages/new', methods=['GET', 'POST'])
@login_required
def admin_new_page():
    """Create a new page."""
    db = get_db()
    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')

    if is_admin_user:
        authors = db.execute('SELECT name FROM authors ORDER BY name').fetchall()
        authors_list = [dict(a)['name'] for a in authors]
    else:
        authors_list = [current_author] if current_author else []

    if request.method == 'POST':
        title = request.form.get('title')
        slug = normalize_slug(request.form.get('slug') or title)
        content = request.form.get('content')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author

        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/new_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form)

        existing = db.execute('SELECT * FROM pages WHERE slug = ? AND language = ?', (slug, language)).fetchone()
        if existing:
            flash(f'A page with slug "{slug}" already exists in {language.upper()}', 'error')
            return render_template('admin/new_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form)

        try:
            db.execute('''
                INSERT INTO pages (title, slug, content, language, status, publish_date, author, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, slug, content, language, status, publish_date, author,
                  datetime.now().isoformat(), datetime.now().isoformat()))
            db.commit()

            flash(f'Page "{title}" created successfully!', 'success')
            return redirect(url_for('admin_pages'))
        except Exception as e:
            flash(f'Error creating page: {str(e)}', 'error')
            return render_template('admin/new_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 form_data=request.form)

    return render_template('admin/new_page.html',
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
    else:
        post = dict(post)
    
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
        slug = normalize_slug(request.form.get('slug') or title)
        content = request.form.get('content')
        excerpt = request.form.get('excerpt')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author
        enable_comments = 1 if request.form.get('enable_comments') else 0
        
        # Validation
        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/edit_post.html', 
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 post=post,
                                 form_data=request.form,
                                 form_enable_comments=enable_comments)
        
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
                                 form_data=request.form,
                                 form_enable_comments=enable_comments)
        
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
                    featured_image = ?, featured = ?, enable_comments = ?, updated_at = ?
                WHERE id = ?
            ''', (title, slug, content, excerpt, language, status, publish_date, author, 
                  featured_image, featured, enable_comments, datetime.now().isoformat(), post_id))
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
                                 form_data=request.form,
                                 form_enable_comments=enable_comments)
    
    # GET request - populate form with post data
    return render_template('admin/edit_post.html', 
                         languages=LANGUAGES,
                         authors=authors_list,
                         current_user=session.get('user_name'),
                         post=post,
                         form_data=post,
                         form_enable_comments=post.get('enable_comments', 0))


@app.route('/admin/pages/edit/<int:page_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_page(page_id):
    """Edit an existing page."""
    db = get_db()
    page = db.execute('SELECT * FROM pages WHERE id = ?', (page_id,)).fetchone()

    if not page:
        flash('Page not found', 'error')
        return redirect(url_for('admin_pages'))

    is_admin_user = bool(session.get('is_admin'))
    current_author = session.get('user_name')

    if not is_admin_user and page['author'] != current_author:
        abort(403)

    if is_admin_user:
        authors = db.execute('SELECT name FROM authors ORDER BY name').fetchall()
        authors_list = [dict(a)['name'] for a in authors]
    else:
        authors_list = [current_author] if current_author else []

    if request.method == 'POST':
        title = request.form.get('title')
        slug = normalize_slug(request.form.get('slug') or title)
        content = request.form.get('content')
        language = request.form.get('language')
        status = request.form.get('status')
        publish_date = request.form.get('publish_date')
        author = request.form.get('author') if is_admin_user else current_author

        if not all([title, slug, content, language, status, publish_date, author]):
            flash('Please fill in all required fields', 'error')
            return render_template('admin/edit_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 page=page,
                                 form_data=request.form)

        existing = db.execute('SELECT id FROM pages WHERE slug = ? AND language = ? AND id != ?', (slug, language, page_id)).fetchone()
        if existing:
            flash(f'A page with slug "{slug}" already exists in {language.upper()}', 'error')
            return render_template('admin/edit_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 page=page,
                                 form_data=request.form)

        try:
            db.execute('''
                UPDATE pages SET 
                    title = ?, slug = ?, content = ?, 
                    language = ?, status = ?, publish_date = ?, author = ?, 
                    updated_at = ?
                WHERE id = ?
            ''', (title, slug, content, language, status, publish_date, author,
                  datetime.now().isoformat(), page_id))
            db.commit()

            flash(f'Page "{title}" updated successfully!', 'success')
            return redirect(url_for('admin_pages'))
        except Exception as e:
            flash(f'Error updating page: {str(e)}', 'error')
            return render_template('admin/edit_page.html',
                                 languages=LANGUAGES,
                                 authors=authors_list,
                                 current_user=session.get('user_name'),
                                 page=page,
                                 form_data=request.form)

    return render_template('admin/edit_page.html',
                         languages=LANGUAGES,
                         authors=authors_list,
                         current_user=session.get('user_name'),
                         page=page,
                         form_data=page)

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
                ext = file.filename.rsplit('.', 1)[1].lower()
                try:
                    filename = secure_filename(f"media_{datetime.now().timestamp()}_{file.filename}")
                    filepath = os.path.join(uploads_dir, filename)
                    if ext in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
                        # Save and optimize image
                        img = Image.open(file.stream)
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        max_width = 1200
                        if img.width > max_width:
                            ratio = max_width / img.width
                            new_height = int(img.height * ratio)
                            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                        img.save(filepath, 'JPEG', quality=85, optimize=True)
                        flash('Image uploaded successfully!', 'success')
                    elif ext == 'pdf':
                        file.save(filepath)
                        # Extract PDF metadata
                        try:
                            from PyPDF2 import PdfReader
                            reader = PdfReader(filepath)
                            info = reader.metadata or {}
                            num_pages = len(reader.pages)
                            meta = {
                                'title': info.title if info.title else '',
                                'author': info.author if info.author else '',
                                'subject': info.subject if info.subject else '',
                                'creator': info.creator if info.creator else '',
                                'producer': info.producer if info.producer else '',
                                'num_pages': num_pages
                            }
                            import json
                            with open(filepath + '.meta.json', 'w') as metafile:
                                json.dump(meta, metafile)
                            flash('PDF uploaded successfully!', 'success')
                        except Exception as meta_e:
                            error_msg = f"Error extracting PDF metadata: {meta_e}"
                            print(error_msg)
                            flash(error_msg, 'error')
                    else:
                        flash('Unsupported file type.', 'error')
                except Exception as e:
                    flash(f'Error uploading file: {str(e)}', 'error')
            return redirect(url_for('admin_media'))
    
    # Get all media files
    media_files = []
    try:
        if os.path.exists(uploads_dir):
            import json
            allowed_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf')
            for filename in os.listdir(uploads_dir):
                if not filename.lower().endswith(allowed_exts):
                    continue
                filepath = os.path.join(uploads_dir, filename)
                file_size = os.path.getsize(filepath)
                file_size_kb = round(file_size / 1024, 2)
                file_mtime = os.path.getmtime(filepath)
                file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                media = {
                    'filename': filename,
                    'url': url_for('static', filename=f'uploads/{filename}'),
                    'size': file_size_kb,
                    'date': file_date
                }
                if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    try:
                        from PIL import Image
                        with Image.open(filepath) as img:
                            media['resolution'] = f"{img.width}x{img.height}"
                    except Exception as img_e:
                        print(f"Error reading image resolution: {img_e}")
                if filename.lower().endswith('.pdf'):
                    meta_path = filepath + '.meta.json'
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, 'r') as metafile:
                                meta = json.load(metafile)
                            media['pdf_meta'] = meta
                        except Exception as meta_e:
                            print(f"Error reading PDF metadata: {meta_e}")
                media_files.append(media)
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
                'meta_keywords_en': request.form.get('meta_keywords_en', ''),
                'meta_keywords_fr': request.form.get('meta_keywords_fr', ''),
                'meta_keywords_de': request.form.get('meta_keywords_de', ''),
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
                'disclaimer_page_en': request.form.get('disclaimer_page_en', ''),
                'disclaimer_page_fr': request.form.get('disclaimer_page_fr', ''),
                'disclaimer_page_de': request.form.get('disclaimer_page_de', ''),
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

    pages_by_language = {}
    for code in LANGUAGES:
        pages_by_language[code] = db.execute(
            "SELECT id, title, slug FROM pages WHERE language = ? AND status = 'published' ORDER BY title",
            (code,)
        ).fetchall()
    
    return render_template('admin/settings.html', settings=settings, languages=LANGUAGES, pages_by_language=pages_by_language)


@app.route('/admin/api/export-database')
@login_required
@admin_required
@limiter.limit('5 per day')  # Prevent abuse of database exports
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

@app.route('/admin/api/purge-old-views', methods=['POST'])
@login_required
@admin_required
@limiter.limit('10 per day')
def api_purge_old_views():
    """Manually trigger purge of post_views older than 30 days."""
    try:
        db = get_db()
        result = db.execute('''
            DELETE FROM post_views
            WHERE viewed_at < datetime('now', '-30 days')
        ''')
        deleted_count = result.rowcount
        db.commit()
        
        return jsonify({
            'success': True,
            'deleted': deleted_count,
            'message': f'Purged {deleted_count} entries older than 30 days'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/admin/api/import-database', methods=['POST'])
@login_required
@admin_required
@limiter.limit('5 per day')  # Prevent abuse of database imports
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
    traffic_data = get_traffic_sources(days=30)
    traffic_sources = traffic_data['sources']
    other_referrers = traffic_data['other_details']
    
    # Get reading patterns (hourly)
    reading_patterns = get_reading_patterns(days=7)
    
    return render_template('admin/statistics.html',
                         summary=summary,
                         most_viewed=most_viewed_list,
                         traffic_sources=traffic_sources,
                         other_referrers=other_referrers,
                         reading_patterns=reading_patterns,
                         languages=LANGUAGES)

@app.route('/admin/api/post-stats/<int:post_id>')
@login_required
@limiter.limit('30 per minute')  # Allow frequent stats checks
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
@limiter.limit('60 per minute')  # Allow frequent autosaves
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
        {"icon": "fa-comments", "title": "Comments Moderation", "text": "Bulk and single comment approval, deletion, and anti-spam features."},
        {"icon": "fa-envelope", "title": "Contact Messages", "text": "Admin inbox for user messages, mark as read/unread, and delete."},
        {"icon": "fa-chart-bar", "title": "Statistics", "text": "Admin dashboard with post, comment, and author stats."},
    ]
    return render_template('admin/about.html', repo_url=repo_url, highlights=highlights)

# Initialize scheduler for auto-publishing scheduled posts
scheduler = BackgroundScheduler()
scheduler.add_job(func=update_scheduled_posts, trigger="interval", minutes=SCHEDULER_INTERVAL)
scheduler.add_job(func=purge_old_views, trigger="interval", hours=24)  # Run daily
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
