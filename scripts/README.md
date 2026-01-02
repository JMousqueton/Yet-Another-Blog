# Database Backup Scripts

This directory contains utilities for backing up and restoring the blog database.

## Scripts

### export_db.py
Exports the entire SQLite database to a JSON backup file.

**Usage:**
```bash
python export_db.py backup.json --database ../blog.db
```

**Features:**
- Exports all tables with full data
- Includes metadata (export date, table count)
- Human-readable JSON format
- Progress indicators

### import_db.py
Imports a JSON backup file into the SQLite database.

**Usage:**
```bash
# Standard import (appends data)
python import_db.py backup.json --database ../blog.db

# Force wipe before import (WARNING: deletes all existing data)
python import_db.py backup.json --database ../blog.db -F
```

**Features:**
- Validates JSON format before import
- Optional force wipe with confirmation prompt
- Skips duplicate entries (integrity protection)
- Progress indicators
- Error handling

## Examples

```bash
# Export current database
python scripts/export_db.py backups/backup-2026-01-02.json --database blog.db

# Import backup (safe mode)
python scripts/import_db.py backups/backup-2026-01-02.json --database blog.db

# Fresh import (wipe first)
python scripts/import_db.py backups/backup-2026-01-02.json --database blog.db -F
```

## JSON Format

The backup JSON file structure:
```json
{
  "metadata": {
    "export_date": "2026-01-02T10:30:00",
    "database": "blog.db",
    "tables_count": 5
  },
  "tables": {
    "posts": {
      "columns": ["id", "title", "content", ...],
      "rows": [
        {"id": 1, "title": "...", ...},
        ...
      ]
    },
    ...
  }
}
```

## Safety Features

- **Import validation**: Checks JSON structure before modifying database
- **Force wipe confirmation**: Requires explicit 'y' confirmation before wiping
- **Integrity protection**: Skips rows that violate database constraints
- **Transaction safety**: Uses SQLite transactions
- **Error handling**: Graceful error messages and exit codes
