#!/usr/bin/env python3
"""
Database Export Script
Exports SQLite database to JSON format for backup purposes.

Usage:
    python export_db.py backup.json --database ../blog.db
"""

import sqlite3
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime


def get_table_names(cursor):
    """Get all table names from the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']


def export_table(cursor, table_name):
    """Export a single table to a dictionary."""
    # Get column names
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Get all rows
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    # Convert to list of dictionaries
    return {
        'columns': columns,
        'rows': [dict(zip(columns, row)) for row in rows]
    }


def export_database(db_path, output_file):
    """Export entire database to JSON."""
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        tables = get_table_names(cursor)
        
        if not tables:
            print("⚠️  No tables found in database", file=sys.stderr)
            return False
        
        # Export data
        export_data = {
            'metadata': {
                'export_date': datetime.now().isoformat(),
                'database': str(db_path),
                'tables_count': len(tables)
            },
            'tables': {}
        }
        
        print(f"📊 Exporting {len(tables)} table(s)...")
        
        for table in tables:
            print(f"  → {table}...", end=" ")
            export_data['tables'][table] = export_table(cursor, table)
            row_count = len(export_data['tables'][table]['rows'])
            print(f"✓ ({row_count} rows)")
        
        # Write to JSON file
        output_path = Path(output_file)
        with output_path.open('w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
        
        conn.close()
        
        print(f"\n✅ Database exported successfully to: {output_file}")
        print(f"📦 File size: {output_path.stat().st_size / 1024:.2f} KB")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}", file=sys.stderr)
        return False
    except IOError as e:
        print(f"❌ File error: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Export SQLite database to JSON backup file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python export_db.py backup.json --database ../blog.db
  python export_db.py data/backup-2026.json --database /path/to/blog.db
        """
    )
    
    parser.add_argument(
        'output',
        help='Output JSON file path'
    )
    
    parser.add_argument(
        '--database',
        required=True,
        help='Path to SQLite database file'
    )
    
    args = parser.parse_args()
    
    # Validate database exists
    db_path = Path(args.database)
    if not db_path.exists():
        print(f"❌ Error: Database file not found: {args.database}", file=sys.stderr)
        sys.exit(1)
    
    # Export database
    success = export_database(db_path, args.output)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
