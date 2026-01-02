#!/bin/bash

# Quick start script for the blog

echo "🚀 Starting Blog Setup..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Initialize database if it doesn't exist
if [ ! -f "blog.db" ]; then
    echo "🗄️  Initializing database..."
    python init_db.py
else
    echo "✅ Database already exists"
fi

# Start the application
echo ""
echo "✨ Starting the blog application..."
echo "📍 Access your blog at: http://localhost:5000"
echo "🌍 Available languages: /en, /fr, /de"
echo "📡 RSS feeds: /en/rss, /fr/rss, /de/rss"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python app.py
