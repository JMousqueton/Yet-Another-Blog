#!/usr/bin/env python3
"""
Migrate existing uploaded images to WebP format.

Converts all .png, .jpg, .jpeg, .gif, .bmp, .tiff images in static/uploads/
to WebP and updates the database references in posts, pages, and authors tables.

Usage:
    python migrate_to_webp.py [--dry-run]
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Run: pip install Pillow")
    sys.exit(1)

# --- Configuration (mirrors app.py) ---
DATABASE_PATH = os.getenv('DATABASE_PATH', 'blog.db')
UPLOAD_FOLDER = os.path.join('static', 'uploads')
WEBP_QUALITY = 85
CONVERTIBLE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif'}


def _prepare_image(img, max_size=None):
    """Flatten transparency and convert to RGB."""
    if img.mode == 'P':
        img = img.convert('RGBA')
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    if max_size:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
    return img


def convert_file(filepath: Path, dry_run: bool) -> str | None:
    """
    Convert a single image file to WebP in-place.
    Returns the new filename (stem + .webp) on success, None on skip/error.
    """
    if filepath.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        return None
    webp_path = filepath.with_suffix('.webp')
    if webp_path.exists() and webp_path != filepath:
        print(f"  SKIP  {filepath.name}  →  {webp_path.name} (target already exists)")
        return None
    if dry_run:
        print(f"  DRY   {filepath.name}  →  {webp_path.name}")
        return webp_path.name
    try:
        with Image.open(filepath) as img:
            img_rgb = _prepare_image(img)
            img_rgb.save(webp_path, 'WEBP', quality=WEBP_QUALITY, method=4)
        # Remove the original only after successful write
        if filepath != webp_path:
            filepath.unlink()
        print(f"  OK    {filepath.name}  →  {webp_path.name}")
        return webp_path.name
    except Exception as e:
        print(f"  ERROR {filepath.name}: {e}")
        return None


def migrate(dry_run: bool):
    upload_dir = Path(UPLOAD_FOLDER)
    if not upload_dir.exists():
        print(f"Upload folder not found: {upload_dir.resolve()}")
        sys.exit(1)

    # --- Step 1: convert files ---
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scanning {upload_dir.resolve()} ...\n")
    conversions: dict[str, str] = {}  # old_name → new_name

    for f in sorted(upload_dir.iterdir()):
        if not f.is_file():
            continue
        new_name = convert_file(f, dry_run)
        if new_name and new_name != f.name:
            conversions[f.name] = new_name

    if not conversions:
        print("\nNothing to convert.")
        return

    print(f"\n{len(conversions)} file(s) converted.")

    # --- Step 2: update database ---
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Updating database references ...\n")

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    updates = {
        'posts':   'featured_image',
        'pages':   'featured_image',
        'authors': 'profile_image',
    }

    total_rows = 0
    for table, column in updates.items():
        # Check table/column exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cur.fetchone():
            continue
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r['name'] for r in cur.fetchall()]
        if column not in cols:
            continue

        cur.execute(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")
        rows = cur.fetchall()
        for row in rows:
            old_val = row[column]
            if old_val and old_val in conversions:
                new_val = conversions[old_val]
                if dry_run:
                    print(f"  DRY   {table}.{column} id={row['id']}: {old_val} → {new_val}")
                else:
                    cur.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (new_val, row['id']))
                    print(f"  OK    {table}.{column} id={row['id']}: {old_val} → {new_val}")
                total_rows += 1

    if not dry_run:
        conn.commit()
        print(f"\n{total_rows} database row(s) updated and committed.")
    else:
        print(f"\n{total_rows} database row(s) would be updated.")

    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate uploaded images to WebP.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making any changes.')
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
