"""
Database utility functions for managing blog posts.
This will be useful for creating a backend admin interface later.
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

class BlogDB:
    """Blog database manager."""
    
    def __init__(self, db_path: str = 'blog.db'):
        self.db_path = db_path
    
    def get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_post(self, title: str, slug: str, content: str, language: str,
                   status: str = 'draft', publish_date: Optional[str] = None,
                   author: Optional[str] = None, excerpt: Optional[str] = None) -> int:
        """
        Create a new blog post.
        
        Args:
            title: Post title
            slug: URL-friendly slug (unique per language)
            content: HTML content
            language: 'en', 'fr', or 'de'
            status: 'draft', 'published', or 'scheduled'
            publish_date: ISO format datetime (defaults to now)
            author: Author name
            excerpt: Short excerpt/summary
        
        Returns:
            Post ID
        """
        if not publish_date:
            publish_date = datetime.now().isoformat()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO posts (title, slug, content, language, status, 
                             publish_date, author, excerpt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (title, slug, content, language, status, publish_date, author, excerpt))
        
        post_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return post_id
    
    def update_post(self, post_id: int, **kwargs) -> bool:
        """
        Update an existing post.
        
        Args:
            post_id: ID of the post to update
            **kwargs: Fields to update (title, content, status, etc.)
        
        Returns:
            True if successful
        """
        allowed_fields = {'title', 'slug', 'content', 'language', 'status',
                         'publish_date', 'author', 'excerpt'}
        
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        updates['updated_at'] = datetime.now().isoformat()
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [post_id]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(f'''
            UPDATE posts 
            SET {set_clause}
            WHERE id = ?
        ''', values)
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def delete_post(self, post_id: int) -> bool:
        """Delete a post by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def get_post(self, post_id: Optional[int] = None, 
                 slug: Optional[str] = None, 
                 language: Optional[str] = None) -> Optional[Dict]:
        """Get a single post by ID or slug+language."""
        conn = self.get_connection()
        
        if post_id:
            post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
        elif slug and language:
            post = conn.execute(
                'SELECT * FROM posts WHERE slug = ? AND language = ?',
                (slug, language)
            ).fetchone()
        else:
            conn.close()
            return None
        
        conn.close()
        return dict(post) if post else None
    
    def get_posts(self, language: Optional[str] = None,
                  status: Optional[str] = None,
                  limit: Optional[int] = None) -> List[Dict]:
        """
        Get multiple posts with optional filtering.
        
        Args:
            language: Filter by language
            status: Filter by status
            limit: Maximum number of posts to return
        
        Returns:
            List of post dictionaries
        """
        conn = self.get_connection()
        
        query = 'SELECT * FROM posts WHERE 1=1'
        params = []
        
        if language:
            query += ' AND language = ?'
            params.append(language)
        
        if status:
            query += ' AND status = ?'
            params.append(status)
        
        query += ' ORDER BY publish_date DESC'
        
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        
        posts = conn.execute(query, params).fetchall()
        conn.close()
        
        return [dict(post) for post in posts]
    
    def update_scheduled_posts(self) -> int:
        """Update scheduled posts to published if their time has come."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute('''
            UPDATE posts 
            SET status = 'published', updated_at = ? 
            WHERE status = 'scheduled' AND publish_date <= ?
        ''', (now, now))
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return count


# Example usage
if __name__ == '__main__':
    from datetime import timedelta
    
    db = BlogDB()
    
    # Example: Create a scheduled post (will be published in the future)
    future_date = (datetime.now() + timedelta(days=1)).isoformat()
    
    print("📝 Database Utility Examples:")
    print("\n1. Get all published English posts:")
    posts = db.get_posts(language='en', status='published')
    for post in posts:
        print(f"   - {post['title']} ({post['publish_date'][:10]})")
    
    print("\n2. Get all posts (any language, any status):")
    all_posts = db.get_posts()
    print(f"   Total posts in database: {len(all_posts)}")
    
    print("\n3. Update scheduled posts:")
    updated = db.update_scheduled_posts()
    print(f"   Updated {updated} scheduled post(s) to published")
    
    print("\n✅ Database utility is ready for backend development!")
