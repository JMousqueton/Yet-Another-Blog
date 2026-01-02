import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

def init_database():
    """Initialize the SQLite database with the posts table."""
    conn = sqlite3.connect('blog.db')
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
    
    # Create index for better performance
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_language_status 
        ON posts(language, status, publish_date)
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
    
    conn.commit()
    conn.close()
    print("Database initialized successfully with sample posts!")

if __name__ == '__main__':
    init_database()
