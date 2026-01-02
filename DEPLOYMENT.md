# Production Deployment Guide

This guide covers deploying Yet Another Blog to a production server using systemd and Nginx.

## Prerequisites

- Linux server (Ubuntu/Debian recommended)
- Python 3.8+
- Nginx
- Domain name with DNS pointing to your server
- (Optional) Certbot for SSL certificates

## 1. Server Preparation

### Install required packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
```

### Create deployment user (optional)

```bash
sudo useradd -m -s /bin/bash bloguser
sudo usermod -aG www-data bloguser
```

## 2. Application Setup

### Clone and configure the application

```bash
# Switch to deployment directory
sudo mkdir -p /var/www/yet-another-blog
sudo chown bloguser:www-data /var/www/yet-another-blog
cd /var/www/yet-another-blog

# Clone repository
git clone https://github.com/JMousqueton/Yet-Another-Blog.git .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize database
python init_db.py

# Configure environment
cp .env.example .env
nano .env
```

### Update `.env` for production

```bash
SECRET_KEY=your-very-secure-random-secret-key-here
APP_ID=your-blog-id
APP_NAME=Your Blog Name
DEFAULT_LANGUAGE=en
DATABASE_PATH=blog.db
SCHEDULER_INTERVAL=5
DEBUG=False

# SMTP Configuration
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_LOGIN=your-email@example.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=no-reply@example.com
```

### Set proper permissions

```bash
sudo chown -R bloguser:www-data /var/www/yet-another-blog
sudo chmod -R 755 /var/www/yet-another-blog
sudo chmod 640 /var/www/yet-another-blog/.env
sudo chmod 664 /var/www/yet-another-blog/blog.db
```

## 3. Systemd Service Setup

### Copy and configure service file

```bash
sudo cp /var/www/yet-another-blog/etc/yet-another-blog.service /etc/systemd/system/
sudo nano /etc/systemd/system/yet-another-blog.service
```

### Verify these settings in the service file

```ini
User=bloguser
Group=www-data
WorkingDirectory=/var/www/yet-another-blog
ExecStart=/var/www/yet-another-blog/venv/bin/python /var/www/yet-another-blog/app.py
```

### Enable and start the service

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable yet-another-blog

# Start the service
sudo systemctl start yet-another-blog

# Check status
sudo systemctl status yet-another-blog

# View logs
sudo journalctl -u yet-another-blog -f
```

### Service management commands

```bash
# Stop service
sudo systemctl stop yet-another-blog

# Restart service
sudo systemctl restart yet-another-blog

# View full logs
sudo journalctl -u yet-another-blog --no-pager
```

## 4. Nginx Reverse Proxy Setup

### Copy and configure Nginx file

```bash
sudo cp /var/www/yet-another-blog/etc/nginx.conf /etc/nginx/sites-available/yet-another-blog
sudo nano /etc/nginx/sites-available/yet-another-blog
```

### Update these settings

```nginx
# Change server_name to your domain
server_name blog.example.com;

# Update SSL certificate paths (or let Certbot do this)
ssl_certificate /etc/letsencrypt/live/blog.example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/blog.example.com/privkey.pem;
```

### Obtain SSL certificate with Let's Encrypt

```bash
sudo certbot --nginx -d blog.example.com
```

Follow the prompts to:
- Enter your email
- Agree to terms of service
- Choose whether to redirect HTTP to HTTPS (recommended: yes)

### Enable the site

```bash
# Create symbolic link to enable site
sudo ln -s /etc/nginx/sites-available/yet-another-blog /etc/nginx/sites-enabled/

# Remove default site if needed
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

## 5. Firewall Configuration

### Configure UFW (Ubuntu Firewall)

```bash
# Allow SSH (if not already allowed)
sudo ufw allow OpenSSH

# Allow HTTP and HTTPS
sudo ufw allow 'Nginx Full'

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

## 6. Database Backups

### Create backup script

```bash
sudo nano /usr/local/bin/backup-blog-db.sh
```

Add the following:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/yet-another-blog"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/var/www/yet-another-blog"

mkdir -p $BACKUP_DIR
cd $APP_DIR
source venv/bin/activate
python scripts/export_db.py $BACKUP_DIR/backup_$DATE.json --database blog.db

# Keep only last 30 backups
cd $BACKUP_DIR
ls -t | tail -n +31 | xargs -r rm
```

Make it executable:

```bash
sudo chmod +x /usr/local/bin/backup-blog-db.sh
```

### Setup cron job for daily backups

```bash
sudo crontab -e
```

Add this line for daily backups at 2 AM:

```cron
0 2 * * * /usr/local/bin/backup-blog-db.sh
```

## 7. SSL Certificate Auto-Renewal

Certbot automatically sets up renewal. Verify with:

```bash
sudo certbot renew --dry-run
```

## 8. Monitoring and Maintenance

### Check application logs

```bash
# Real-time logs
sudo journalctl -u yet-another-blog -f

# Last 100 lines
sudo journalctl -u yet-another-blog -n 100

# Logs since yesterday
sudo journalctl -u yet-another-blog --since yesterday
```

### Check Nginx logs

```bash
# Access logs
sudo tail -f /var/log/nginx/access.log

# Error logs
sudo tail -f /var/log/nginx/error.log
```

### Monitor service status

```bash
# Service status
sudo systemctl status yet-another-blog

# Nginx status
sudo systemctl status nginx

# Check if ports are listening
sudo ss -tulpn | grep :5001
sudo ss -tulpn | grep :80
sudo ss -tulpn | grep :443
```

## 9. Updating the Application

```bash
# Stop the service
sudo systemctl stop yet-another-blog

# Navigate to app directory
cd /var/www/yet-another-blog

# Pull latest changes
git pull

# Activate virtual environment
source venv/bin/activate

# Update dependencies
pip install -r requirements.txt --upgrade

# Run any database migrations (if needed)
# python migrate.py

# Restart service
sudo systemctl start yet-another-blog

# Check status
sudo systemctl status yet-another-blog
```

## 10. Troubleshooting

### Application won't start

```bash
# Check logs
sudo journalctl -u yet-another-blog -n 50

# Verify permissions
ls -la /var/www/yet-another-blog

# Test manually
cd /var/www/yet-another-blog
source venv/bin/activate
python app.py
```

### Nginx issues

```bash
# Test configuration
sudo nginx -t

# Check error logs
sudo tail -f /var/log/nginx/error.log

# Verify port 5001 is listening
sudo ss -tulpn | grep :5001
```

### SSL certificate issues

```bash
# Test certificate renewal
sudo certbot renew --dry-run

# Check certificate status
sudo certbot certificates
```

### Database issues

```bash
# Check database file permissions
ls -la /var/www/yet-another-blog/blog.db

# Backup database
cd /var/www/yet-another-blog
source venv/bin/activate
python scripts/export_db.py backup_$(date +%Y%m%d).json

# Restore from backup
python scripts/import_db.py backup_20260102.json -F
```

## 11. Production Checklist

Before going live, verify:

- [ ] `.env` has a strong, unique `SECRET_KEY`
- [ ] `DEBUG=False` in `.env`
- [ ] SSL certificate is installed and auto-renews
- [ ] Firewall is configured (ports 80, 443 open)
- [ ] Database backups are scheduled
- [ ] SMTP settings are configured for email notifications
- [ ] Application logs are being written and rotated
- [ ] Monitoring is in place (optional: UptimeRobot, Pingdom, etc.)
- [ ] DNS is properly configured
- [ ] Admin password is changed from default
- [ ] Regular security updates are scheduled

## 12. Performance Optimization (Optional)

### Enable HTTP/2 in Nginx

Already enabled in the template config with `http2` directive.

### Add caching headers

Edit `/etc/nginx/sites-available/yet-another-blog` and add to the server block:

```nginx
location /static/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

### Use Gunicorn for production

Install Gunicorn:

```bash
cd /var/www/yet-another-blog
source venv/bin/activate
pip install gunicorn
```

Update systemd service `ExecStart`:

```ini
ExecStart=/var/www/yet-another-blog/venv/bin/gunicorn -w 4 -b 127.0.0.1:5001 app:app
```

Restart service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart yet-another-blog
```

## Support

For issues and questions:
- GitHub: https://github.com/JMousqueton/Yet-Another-Blog
- Documentation: See README.md

---

**Good luck with your deployment!**
