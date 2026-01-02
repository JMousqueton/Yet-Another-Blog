"""
Sample script to add more test posts to the database.
Run this after init_db.py to populate with additional content.
"""

import sys
from pathlib import Path

# Add parent directory to path to import db_utils
parent_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_dir))

from db_utils import BlogDB
from datetime import datetime, timedelta

def add_sample_posts():
    """Add sample posts in all three languages."""
    
    db = BlogDB('../blog.db')
    
    sample_posts = [
        # English Posts
        {
            'title': 'Getting Started with Python',
            'slug': 'getting-started-python',
            'content': '''<h2>Introduction to Python</h2>
<p>Python is a versatile and beginner-friendly programming language that has become one of the most popular languages in the world.</p>
<h3>Why Python?</h3>
<ul>
    <li><strong>Easy to Learn</strong>: Clean and readable syntax</li>
    <li><strong>Versatile</strong>: Web development, data science, AI, automation</li>
    <li><strong>Great Community</strong>: Extensive libraries and frameworks</li>
</ul>
<h3>Hello World</h3>
<pre><code>print("Hello, World!")</code></pre>
<p>That's it! Python makes programming accessible to everyone.</p>''',
            'language': 'en',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=2)).isoformat(),
            'author': 'Tech Writer',
            'excerpt': 'Learn why Python is a great first programming language'
        },
        
        {
            'title': 'The Future of Web Development',
            'slug': 'future-web-development',
            'content': '''<h2>Web Development Trends 2026</h2>
<p>The web development landscape is evolving rapidly. Here are the key trends shaping the future:</p>
<h3>1. AI-Powered Development</h3>
<p>AI assistants are revolutionizing how we write code, debug, and optimize applications.</p>
<h3>2. WebAssembly Growth</h3>
<p>Near-native performance in the browser opens up new possibilities for web applications.</p>
<h3>3. Progressive Web Apps</h3>
<p>The line between web and native apps continues to blur.</p>
<blockquote>The future of web development is more exciting than ever before.</blockquote>''',
            'language': 'en',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=5)).isoformat(),
            'author': 'Tech Writer',
            'excerpt': 'Exploring the latest trends in web development for 2026'
        },
        
        {
            'title': 'Coming Soon: Advanced Flask Tutorial',
            'slug': 'advanced-flask-tutorial',
            'content': '''<h2>Advanced Flask Patterns</h2>
<p>This post will cover advanced Flask development patterns including:</p>
<ul>
    <li>Application factories</li>
    <li>Blueprints organization</li>
    <li>Custom middleware</li>
    <li>Testing strategies</li>
</ul>
<p>Stay tuned for this comprehensive guide!</p>''',
            'language': 'en',
            'status': 'scheduled',
            'publish_date': (datetime.now() + timedelta(days=3)).isoformat(),
            'author': 'Tech Writer',
            'excerpt': 'An upcoming guide to advanced Flask development patterns'
        },
        
        # French Posts
        {
            'title': 'Débuter avec Python',
            'slug': 'debuter-avec-python',
            'content': '''<h2>Introduction à Python</h2>
<p>Python est un langage de programmation polyvalent et convivial pour les débutants, devenu l'un des langages les plus populaires au monde.</p>
<h3>Pourquoi Python ?</h3>
<ul>
    <li><strong>Facile à apprendre</strong> : Syntaxe claire et lisible</li>
    <li><strong>Polyvalent</strong> : Développement web, data science, IA, automatisation</li>
    <li><strong>Grande communauté</strong> : Bibliothèques et frameworks étendus</li>
</ul>
<h3>Hello World</h3>
<pre><code>print("Bonjour, le monde !")</code></pre>
<p>C'est tout ! Python rend la programmation accessible à tous.</p>''',
            'language': 'fr',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=2)).isoformat(),
            'author': 'Rédacteur Tech',
            'excerpt': 'Découvrez pourquoi Python est un excellent premier langage de programmation'
        },
        
        {
            'title': 'L\'avenir du développement web',
            'slug': 'avenir-developpement-web',
            'content': '''<h2>Tendances du développement web 2026</h2>
<p>Le paysage du développement web évolue rapidement. Voici les tendances clés qui façonnent l'avenir :</p>
<h3>1. Développement assisté par IA</h3>
<p>Les assistants IA révolutionnent notre façon d'écrire du code, de déboguer et d'optimiser les applications.</p>
<h3>2. Croissance de WebAssembly</h3>
<p>Des performances quasi-natives dans le navigateur ouvrent de nouvelles possibilités pour les applications web.</p>
<h3>3. Applications Web Progressives</h3>
<p>La frontière entre applications web et natives continue de s'estomper.</p>
<blockquote>L'avenir du développement web est plus passionnant que jamais.</blockquote>''',
            'language': 'fr',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=5)).isoformat(),
            'author': 'Rédacteur Tech',
            'excerpt': 'Explorer les dernières tendances du développement web pour 2026'
        },
        
        # German Posts
        {
            'title': 'Erste Schritte mit Python',
            'slug': 'erste-schritte-python',
            'content': '''<h2>Einführung in Python</h2>
<p>Python ist eine vielseitige und anfängerfreundliche Programmiersprache, die zu einer der beliebtesten Sprachen der Welt geworden ist.</p>
<h3>Warum Python?</h3>
<ul>
    <li><strong>Leicht zu lernen</strong>: Klare und lesbare Syntax</li>
    <li><strong>Vielseitig</strong>: Webentwicklung, Data Science, KI, Automatisierung</li>
    <li><strong>Große Community</strong>: Umfangreiche Bibliotheken und Frameworks</li>
</ul>
<h3>Hello World</h3>
<pre><code>print("Hallo, Welt!")</code></pre>
<p>Das war's! Python macht Programmierung für jeden zugänglich.</p>''',
            'language': 'de',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=2)).isoformat(),
            'author': 'Tech Autor',
            'excerpt': 'Erfahren Sie, warum Python eine großartige erste Programmiersprache ist'
        },
        
        {
            'title': 'Die Zukunft der Webentwicklung',
            'slug': 'zukunft-webentwicklung',
            'content': '''<h2>Webentwicklungstrends 2026</h2>
<p>Die Webentwicklungslandschaft entwickelt sich rasant. Hier sind die wichtigsten Trends, die die Zukunft gestalten:</p>
<h3>1. KI-gestützte Entwicklung</h3>
<p>KI-Assistenten revolutionieren, wie wir Code schreiben, debuggen und Anwendungen optimieren.</p>
<h3>2. WebAssembly-Wachstum</h3>
<p>Nahezu native Leistung im Browser eröffnet neue Möglichkeiten für Webanwendungen.</p>
<h3>3. Progressive Web Apps</h3>
<p>Die Grenze zwischen Web- und nativen Apps verschwimmt weiter.</p>
<blockquote>Die Zukunft der Webentwicklung ist aufregender denn je.</blockquote>''',
            'language': 'de',
            'status': 'published',
            'publish_date': (datetime.now() - timedelta(days=5)).isoformat(),
            'author': 'Tech Autor',
            'excerpt': 'Die neuesten Trends in der Webentwicklung für 2026 erkunden'
        },
        
        # Draft examples
        {
            'title': 'Draft: Machine Learning Basics',
            'slug': 'ml-basics-draft',
            'content': '<h2>Work in Progress</h2><p>This is a draft post about machine learning.</p>',
            'language': 'en',
            'status': 'draft',
            'publish_date': datetime.now().isoformat(),
            'author': 'Tech Writer',
            'excerpt': 'A draft post about machine learning fundamentals'
        }
    ]
    
    print("📝 Adding sample posts to database...\n")
    
    for post_data in sample_posts:
        try:
            post_id = db.create_post(**post_data)
            status_emoji = {
                'published': '✅',
                'scheduled': '⏰',
                'draft': '📝'
            }.get(post_data['status'], '❓')
            
            print(f"{status_emoji} [{post_data['language'].upper()}] {post_data['title']} (ID: {post_id})")
        except Exception as e:
            print(f"❌ Error adding '{post_data['title']}': {e}")
    
    print("\n✨ Sample posts added successfully!")
    print("\n📊 Database Summary:")
    
    # Show summary
    for lang in ['en', 'fr', 'de']:
        total = len(db.get_posts(language=lang))
        published = len(db.get_posts(language=lang, status='published'))
        scheduled = len(db.get_posts(language=lang, status='scheduled'))
        drafts = len(db.get_posts(language=lang, status='draft'))
        
        print(f"  {lang.upper()}: {total} total ({published} published, {scheduled} scheduled, {drafts} drafts)")

if __name__ == '__main__':
    add_sample_posts()
