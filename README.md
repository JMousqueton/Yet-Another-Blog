# Multilingual Blog Platform

A modern, feature-rich multilingual blog platform with an intuitive admin interface, built with Flask, Bootstrap 5, and SQLite.

## ✨ Features

### 🌍 Multilingual Support
- **3 Languages**: English (default), French, and German
- **JSON-based i18n**: Easy translation management with external locale files
- **Language Selection**: Automatic detection with cookie persistence
- **Per-language settings**: Customizable titles, subtitles, and descriptions

### 📝 Content Management
- **Full Admin Panel**: Complete WYSIWYG editor with markdown support
- **Code Syntax Highlighting**: Beautiful syntax highlighting for code blocks
- **Media Embeds**: YouTube and Twitter/X embed support
- **Post Management**: Draft, Published, and Scheduled statuses
- **Featured Posts**: Pin important articles to the top of the homepage
- **Author Profiles**: Bio, social links, and profile images
- **Media Library**: Upload and manage images
- **Featured Images**: Support for post and author images
- **Reading Time**: Automatic calculation
- **Search**: Full-text search across posts
- **Auto-save**: Draft auto-save to prevent data loss
- **Draft Sharing**: Shareable preview links for unpublished posts (drafts & scheduled)

### 🎨 Design & UX
- **4 Themes**: Default, Light, Dark, and Vibrant
- **Dark Mode Toggle**: Persistent user preference
- **Responsive Design**: Mobile-first Bootstrap 5
- **Smooth Animations**: Page transitions and hover effects
- **Lazy Loading**: Optimized image loading with shimmer effect
- **Custom Favicon**: Upload your own

### 🚀 Performance & SEO
- **RSS Feeds**: Per-language RSS with featured images, author tags, and lastBuildDate
- **SEO Optimized**: Meta tags, Open Graph, Twitter Cards, canonical URLs
- **JSON-LD Schemas**: BlogPosting, Blog, and Person structured data for rich snippets
- **AMP Support**: Accelerated Mobile Pages for lightning-fast mobile experience
- **Sitemap**: Automatic XML sitemap generation with language alternates
- **Robots.txt**: Search engine configuration
- **Page Transitions**: Smooth fade-in/out effects
- **Auto-Publishing**: Scheduled posts publish automatically via APScheduler
- **Lazy Loading**: Optimized image loading with shimmer effect

### 💬 Engagement
- **Social Sharing**: LinkedIn, Twitter/X, Bluesky integration
- **Reactions**: Helpful/Not Helpful with localStorage persistence
- **Author Pages**: Dedicated pages for each author
- **Post Navigation**: Previous/Next links on post pages
- **Analytics**: Post view tracking and statistics dashboard

### 📊 Analytics & Statistics
- **Traffic Sources**: Track referrers (Google, Yahoo, Facebook, Twitter/X, LinkedIn, Bluesky, Direct, Other)
- **Reading Patterns**: Hourly view distribution charts
- **Rate Limiting**: Flask-Limiter with real IP detection via ProxyFix
- **Docker Support**: Multi-stage Dockerfile with docker-compose setup
- **Production Guides**: Ubuntu deployment with Nginx and systemd
- **Most Viewed Posts**: Top 10 posts by view count
- **Post Stats API**: Detailed analytics per post with 7-day trends
- **Expandable Details**: Click "Other" traffic sources to see top 10 individual referrers
- **Auto-Cleanup**: Automatically purges view data older than 30 days

### � Security Features
- **Two-Factor Authentication (2FA)**: TOTP-based authentication for admin accounts
- **Session Security**: HTTPONLY, SECURE (production), SAMESITE cookies
- **Rate Limiting**: Protection against brute force and API abuse
- **CSRF Protection**: Flask-WTF tokens on all forms
- **Content Security Policy**: Whitelisted external domains
- **Real IP Detection**: ProxyFix for accurate rate limiting behind proxies
- **Referrer Filtering**: Excludes internal traffic from analytics

### �🛠️ Developer Features
- **Database Tools**: Export/import scripts for backups
- **Sample Data**: Quick population with test posts
- **Environment Config**: `.env` file support
- **Clean Architecture**: Modular design with utilities

## 🖼️ Screenshots

| Language Picker | Admin Login | Admin Dashboard |
| --- | --- | --- |
| ![Language picker](.github/screenshots/Chooselang.png) | ![Admin login](.github/screenshots/adminlogin.png) | ![Admin dashboard](.github/screenshots/admindashboard.png) |

| Posts | Authors | Media |
| --- | --- | --- |
| ![Admin posts](.github/screenshots/adminposts.png) | ![Admin authors](.github/screenshots/adminauthors.png) | ![Admin media](.github/screenshots/adminmedia.png) |

| Settings | Post Page |
| --- | --- |
| ![Admin settings](.github/screenshots/adminsettings.png) | ![Post page](.github/screenshots/post.png) |

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip

See `requirements.txt` for complete list.

### Installation

1. **Clone and setup environment**:
```bash
git clone <repository-url>
cd blog
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Initialize database**:
```bash
python init_db.py
```

4. **Configure environment** (optional):
```bash
cp .env.example .env
# Edit .env with your settings
```

5. **Run the application**:
```bash
./start.sh  # Or: python app.py
```

6. **Access the blog**:
- Blog: `http://localhost:5001`
- Admin: `http://localhost:5001/admin/login`
- Default credentials: See `init_db.py` output

## 📁 Project Structure

```
blog/
├── app.py                  # Main Flask application
├── init_db.py             # Database initialization
├── db_utils.py            # Database utilities
├── requirements.txt       # Python dependencies
├── start.sh              # Startup script
├── locales/              # Translation files
│   ├── en.json
│   ├── fr.json
│   └── de.json
├── scripts/              # Utility scripts
│   ├── export_db.py     # Database backup
│   ├── import_db.py     # Database restore
│   └── add_sample_posts.py
├── static/
│   ├── css/             # Theme stylesheets
│   │   ├── default.css
│   │   ├── light.css
│   │   ├── dark.css
│   │   └── vibrant.css
│   ├── uploads/         # Featured images
│   └── authors/         # Author profile images
└── templates/
    ├── base.html        # Base template
    ├── index.html       # Post listing
    ├── post.html        # Single post view
    ├── author.html      # Author profile
    └── admin/          # Admin templates
```

## 🛠️ Database Management

### Backup Database
```bash
python scripts/export_db.py backup.json --database blog.db
```

### Restore Database
```bash
# Standard restore (appends data)
python scripts/import_db.py backup.json --database blog.db

# Force wipe and restore
python scripts/import_db.py backup.json --database blog.db -F
```

### Add Sample Data
```bash
python scripts/add_sample_posts.py
```

## 🎨 Theme Customization

Themes are CSS files in `static/css/`:
- `default.css` - Professional blue/grey
- `light.css` - Clean light theme
- `dark.css` - Modern dark theme
- `vibrant.css` - Colorful gradient theme

Change themes in Admin → Settings or by editing the `template_css` setting.

## ✍️ Writing Posts

### Markdown Syntax
Posts are written in Markdown with enhanced features:

#### Code Blocks with Syntax Highlighting
Use triple backticks with language identifier:

\`\`\`python
def hello_world():
    print("Hello, World!")
    return True
\`\`\`

\`\`\`javascript
const greeting = () => {
    console.log("Hello, World!");
};
\`\`\`

Supported languages: Python, JavaScript, Java, C++, HTML, CSS, and many more.

#### Inline Code
Use single backticks for inline code: \`print("hello")\`

#### YouTube Embeds
Embed YouTube videos in three ways:

1. **Short syntax**: \`[youtube:VIDEO_ID]\`
   - Example: \`[youtube:dQw4w9WgXcQ]\`

2. **Full URL**: Just paste the YouTube URL
   - Example: \`https://www.youtube.com/watch?v=dQw4w9WgXcQ\`
   - Example: \`https://youtu.be/dQw4w9WgXcQ\`

#### Twitter/X Embeds
Embed tweets in three ways:

1. **Short syntax**: \`[twitter:TWEET_ID]\` or \`[x:TWEET_ID]\`
   - Example: \`[twitter:1234567890]\`

2. **Full URL**: Just paste the tweet URL
   - Example: \`https://twitter.com/username/status/1234567890\`
   - Example: \`https://x.com/username/status/1234567890\`

### Standard Markdown Features
- **Bold**: \`**text**\` or \`__text__\`
- **Italic**: \`*text*\` or \`_text_\`
- **Headers**: \`# H1\`, \`## H2\`, \`### H3\`, etc.
- **Links**: \`[text](url)\`
- **Images**: \`![alt](url)\`
- **Lists**: Use \`-\` or \`*\` for unordered, \`1.\` for ordered
- **Blockquotes**: Start line with \`>\`
- **Tables**: Use pipe \`|\` syntax

## 🌍 Adding New Languages

1. **Create translation file**:
```bash
cp locales/en.json locales/es.json
# Edit es.json with Spanish translations
```

2. **Add language to app.py**:
```python
LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇬🇧'},
    'fr': {'name': 'Français', 'flag': '🇫🇷'},
    'de': {'name': 'Deutsch', 'flag': '🇩🇪'},
    'es': {'name': 'Español', 'flag': '🇪🇸'}  # Add this
}
```

3. **Restart application**

## ⚙️ Configuration

### Two-Factor Authentication (2FA)

Admin accounts can be secured with TOTP-based 2FA (compatible with Google Authenticator, Authy, 1Password, etc.):

1. **Enable 2FA**:
   - Log in to admin panel
   - Go to Admin → Authors → Edit your profile (or click your name)
   - Scroll to "Security Settings" section
   - Click "Manage 2FA"
   - Click "Start Setup" and scan QR code with authenticator app
   - Enter 6-digit code to confirm

2. **Login with 2FA**:
   - Enter email/password as usual
   - You'll be redirected to enter 6-digit code from your authenticator app
   - Code expires every 30 seconds

3. **Disable 2FA**:
   - Go to Security Settings → Manage 2FA
   - Enter current 6-digit code to disable

**Note**: Each admin can manage their own 2FA independently. No global 2FA enforcement.

### Environment Variables (.env)
```bash  # Minutes between auto-publish checks
# Server configuration
HOST=0.0.0.0
PORT=5000
DEBUG=True
BASE_URL=http://localhost:5000

# Security (IMPORTANT: Change this in production!)
SECRET_KEY=your-secret-key-change-this-in-production

# Database
DATABASE_PATH=blog.db

# Scheduler settings (minutes)
SCHEDULER_INTERVAL=5

# Default language
DEFAULT_LANGUAGE=en

# SMTP Configuration
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_LOGIN=your-email@example.com
SMTP_PASSWORD=your-password-here
SMTP_FROM=no-reply@example.com
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## 🙏 Credits

- Built with Flask and Bootstrap 5
- Icons by Font Awesome
- Font: IBM Plex Sans

---

**Made with ❤️ by Julien Mousqueton**
