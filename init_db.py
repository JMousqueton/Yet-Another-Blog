import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

def init_database():
    """Initialize the SQLite database with the posts table."""
    # Get database path from environment or use default
    db_path = os.getenv('DATABASE_PATH', 'blog.db')
    
    # If db_path is just a filename, use current directory
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), db_path)
    
    db_dir = os.path.dirname(db_path)
    
    # Create directory if it doesn't exist
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, mode=0o755, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create authors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bio_en TEXT,
            bio_fr TEXT,
            bio_de TEXT,
            twitter TEXT,
            linkedin TEXT,
            github TEXT,
            website TEXT,
            profile_image TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create posts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts (
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
            excerpt TEXT,
            featured_image TEXT,
            featured INTEGER DEFAULT 0,
            UNIQUE(slug, language),
            FOREIGN KEY(author) REFERENCES authors(name)
        )
    ''')

    # Create pages table
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
    
    # Create index for better performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_language_status 
        ON posts(language, status, publish_date)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_pages_language_status 
        ON pages(language, status, publish_date)
    ''')

    # Create contact messages table
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
    
    # Create post_views table for statistics tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            referrer TEXT,
            user_agent TEXT,
            language TEXT,
            post_slug TEXT,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
        )
    ''')
    
    # Create index for post views queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_post_views_post_id 
        ON post_views(post_id, viewed_at)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_post_views_slug 
        ON post_views(post_slug, language)
    ''')
    
    # Create settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Add sample author
    try:
        hashed_password = generate_password_hash('Password123')
        cursor.execute('''
            INSERT INTO authors (name, email, password, is_admin, bio_en, bio_fr, bio_de, twitter, linkedin, github, website)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'Blog Admin',
            'admin@example.com',
            hashed_password,
            1,
            'Passionate about technology, travel, and sharing knowledge. Full-stack developer and tech enthusiast.',
            'Passionné par la technologie, les voyages et le partage des connaissances. Développeur full-stack et passionné de technologie.',
            'Leidenschaftlich für Technologie, Reisen und Wissensaustausch. Full-Stack-Entwickler und Technik-Enthusiast.',
            'https://twitter.com',
            'https://linkedin.com',
            'https://github.com',
            'https://example.com'
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Author already exists
    
    # Add sample posts
    sample_posts = [
        {
            'title': 'Welcome to My Blog',
            'slug': 'welcome',
            'content': '''<h2>Welcome!</h2>
<p>This is my new multilingual blog. I'll be sharing thoughts on technology, travel, and more.</p>
<p>Feel free to explore and switch between English, French, and German using the language selector.</p>''',
            'language': 'en',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin',
            'excerpt': 'Welcome to my new multilingual blog!'
        },
        {
            'title': 'Bienvenue sur mon blog',
            'slug': 'bienvenue',
            'content': '''<h2>Bienvenue !</h2>
<p>Ceci est mon nouveau blog multilingue. Je partagerai des réflexions sur la technologie, les voyages et plus encore.</p>
<p>N'hésitez pas à explorer et à basculer entre l'anglais, le français et l'allemand à l'aide du sélecteur de langue.</p>''',
            'language': 'fr',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin',
            'excerpt': 'Bienvenue sur mon nouveau blog multilingue !'
        },
        {
            'title': 'Willkommen auf meinem Blog',
            'slug': 'willkommen',
            'content': '''<h2>Willkommen!</h2>
<p>Dies ist mein neuer mehrsprachiger Blog. Ich werde Gedanken über Technologie, Reisen und mehr teilen.</p>
<p>Erkunden Sie gerne und wechseln Sie mit dem Sprachauswähler zwischen Englisch, Französisch und Deutsch.</p>''',
            'language': 'de',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin',
            'excerpt': 'Willkommen auf meinem neuen mehrsprachigen Blog!'
        }
    ]
    
    for post in sample_posts:
        cursor.execute('''
            INSERT OR IGNORE INTO posts 
            (title, slug, content, language, status, publish_date, author, excerpt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (post['title'], post['slug'], post['content'], post['language'], 
              post['status'], post['publish_date'], post['author'], post['excerpt']))

    # Add sample pages
    sample_pages = [
        {
            'title': 'About',
            'slug': 'about',
            'content': '''<h2>About This Site</h2>
<p>This page is managed like a post but does not show author details or navigation.</p>
<p>Use it for static content such as About, Contact, or Legal mentions.</p>''',
            'language': 'en',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin'
        },
        {
            'title': 'À propos',
            'slug': 'a-propos',
            'content': '''<h2>À propos</h2>
<p>Cette page est gérée comme un article mais n'affiche pas d'auteur ni de navigation.</p>
<p>Utilisez-la pour du contenu statique comme À propos, Contact ou Mentions légales.</p>''',
            'language': 'fr',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin'
        },
        {
            'title': 'Über uns',
            'slug': 'uber-uns',
            'content': '''<h2>Über uns</h2>
<p>Diese Seite wird wie ein Beitrag verwaltet, zeigt aber keine Autorendaten oder Navigation.</p>
<p>Nutzen Sie sie für statische Inhalte wie Über uns, Kontakt oder Impressum.</p>''',
            'language': 'de',
            'status': 'published',
            'publish_date': datetime.now().isoformat(),
            'author': 'Blog Admin'
        }
    ]

    for page in sample_pages:
        cursor.execute('''
            INSERT OR IGNORE INTO pages 
            (title, slug, content, language, status, publish_date, author)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (page['title'], page['slug'], page['content'], page['language'], 
              page['status'], page['publish_date'], page['author']))
    
    conn.commit()
    conn.close()
    print("Database initialized successfully with sample posts!")

if __name__ == '__main__':
    init_database()
