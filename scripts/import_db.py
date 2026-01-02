#!/usr/bin/env python3
"""
Database Import Script
Imports JSON backup file into SQLite database.

Usage:
    python import_db.py backup.json --database ../blog.db
    python import_db.py backup.json --database ../blog.db -F  # Force wipe before import
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


def wipe_database(cursor):
    """Delete all data from all tables."""
    tables = get_table_names(cursor)
    
    if not tables:
        print("⚠️  No tables to wipe")
        return
    
    print(f"🗑️  Wiping {len(tables)} table(s)...")
    
    # Disable foreign keys temporarily
    cursor.execute("PRAGMA foreign_keys = OFF")
    
    for table in tables:
        print(f"  → Deleting {table}...", end=" ")
        cursor.execute(f"DELETE FROM {table}")
        row_count = cursor.rowcount
        print(f"✓ ({row_count} rows)")
    
    # Re-enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    print("✓ Database wiped")


def import_table(cursor, table_name, table_data):
    """Import data into a single table."""
    rows = table_data.get('rows', [])
    
    if not rows:
        return 0
    
    # Get columns from first row
    columns = list(rows[0].keys())
    placeholders = ','.join(['?' for _ in columns])
    column_names = ','.join(columns)
    
    # Prepare INSERT statement
    sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
    
    # Insert all rows
    inserted = 0
    for row in rows:
        try:
            values = [row.get(col) for col in columns]
            cursor.execute(sql, values)
            inserted += 1
        except sqlite3.IntegrityError as e:
            print(f"\n  ⚠️  Skipped row in {table_name}: {e}")
    
    return inserted


def import_database(db_path, input_file, force_wipe=False):
    """Import JSON backup into database."""
    try:
        # Read JSON file
        input_path = Path(input_file)
        with input_path.open('r', encoding='utf-8') as f:
            import_data = json.load(f)
        
        # Validate JSON structure
        if 'tables' not in import_data:
            print("❌ Invalid JSON format: 'tables' key not found", file=sys.stderr)
            return False
        
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Display import info
        metadata = import_data.get('metadata', {})
        print(f"📥 Importing backup from: {input_file}")
        if 'export_date' in metadata:
            print(f"📅 Exported on: {metadata['export_date']}")
        if 'tables_count' in metadata:
            print(f"📊 Tables: {metadata['tables_count']}")
        print()
        
        # Wipe database if requested
        if force_wipe:
            response = input("⚠️  Force wipe enabled. This will DELETE ALL DATA. Continue? [y/N]: ")
            if response.lower() != 'y':
                print("❌ Import cancelled")
                return False
            wipe_database(cursor)
            print()
        
        # Import tables
        tables = import_data['tables']
        print(f"📊 Importing {len(tables)} table(s)...")
        
        total_rows = 0
        for table_name, table_data in tables.items():
            print(f"  → {table_name}...", end=" ")
            try:
                row_count = import_table(cursor, table_name, table_data)
                total_rows += row_count
                print(f"✓ ({row_count} rows)")
            except sqlite3.Error as e:
                print(f"❌ Error: {e}")
        
        # Commit changes
        conn.commit()
        conn.close()
        
        print(f"\n✅ Database imported successfully!")
        print(f"📦 Total rows imported: {total_rows}")
        return True
        
    except FileNotFoundError:
        print(f"❌ Error: Input file not found: {input_file}", file=sys.stderr)
        return False
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}", file=sys.stderr)
        return False
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Import JSON backup file into SQLite database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python import_db.py backup.json --database ../blog.db
  python import_db.py backup.json --database ../blog.db -F  # Force wipe first
  python import_db.py data/backup.json --database /path/to/blog.db
        """
    )
    
    parser.add_argument(
        'input',
        help='Input JSON file path'
    )
    
    parser.add_argument(
        '--database',
        required=True,
        help='Path to SQLite database file'
    )
    
    parser.add_argument(
        '-F', '--force',
        action='store_true',
        help='Force wipe database before import (WARNING: deletes all existing data)'
    )
    
    args = parser.parse_args()
    
    # Validate input file exists
    if not Path(args.input).exists():
        print(f"❌ Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    
    # Validate database exists (unless forcing wipe)
    db_path = Path(args.database)
    if not db_path.exists() and not args.force:
        print(f"❌ Error: Database file not found: {args.database}", file=sys.stderr)
        print("💡 Use -F flag to create new database", file=sys.stderr)
        sys.exit(1)
    
    # Import database
    success = import_database(db_path, args.input, args.force)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
