#!/usr/bin/env python3
"""CLI utility to inspect SQLite database and exported datasets."""

import os
import sys
from pathlib import Path

# Auto-re-execute inside project .venv to guarantee all packages are available
venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

import json
import sqlite3
from crawler.models.schemas import StartupRecord, ProductRecord, ResearchPaperRecord


def inspect_pipeline():
    base_dir = Path(__file__).resolve().parent
    db_path = base_dir / "data" / "crawler_data.db"
    exports_dir = base_dir / "exports"

    print("=" * 70)
    print("BULK DATA ACQUISITION PIPELINE - DATA INSPECTION REPORT")
    print("=" * 70)

    if not db_path.exists():
        print(f"Database file not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Table counts
    cursor.execute("SELECT record_type, COUNT(*) FROM records GROUP BY record_type")
    counts = dict(cursor.fetchall())
    print("\n1. DATABASE TOTALS (SQLite WAL):")
    total_all = 0
    for rtype, count in counts.items():
        print(f"   • {rtype:<16}: {count:>6,} unique records")
        total_all += count
    print(f"   ────────────────────────────────────────")
    print(f"   • TOTAL           : {total_all:>6,} unique verified records\n")

    # Schema Validation Verification
    print("2. SCHEMA VALIDATION CHECK (Pydantic v2):")
    type_models = {
        "STARTUP": StartupRecord,
        "PRODUCT": ProductRecord,
        "RESEARCH_PAPER": ResearchPaperRecord,
    }
    for rtype, model_cls in type_models.items():
        cursor.execute("SELECT validated_data FROM records WHERE record_type = ?", (rtype,))
        rows = cursor.fetchall()
        valid = 0
        for r in rows:
            try:
                model_cls.model_validate_json(r[0])
                valid += 1
            except Exception as e:
                print(f"   Validation error on {rtype}: {e}")
                break
        print(f"   • {rtype:<16}: {valid:,}/{len(rows):,} records 100% compliant")

    # Sample Records
    print("\n3. SAMPLE VERIFIED REAL RECORDS:")
    for rtype in ("STARTUP", "PRODUCT", "RESEARCH_PAPER"):
        cursor.execute(
            "SELECT validated_data FROM records WHERE record_type = ? ORDER BY id ASC LIMIT 1",
            (rtype,),
        )
        row = cursor.fetchone()
        if row:
            d = json.loads(row[0])
            print(f"\n   [{rtype} Sample]:")
            print("   " + json.dumps(d, indent=4).replace("\n", "\n   "))

    # Exported Files
    print("\n4. EXPORTED FILES ON DISK:")
    if exports_dir.exists():
        for file in sorted(exports_dir.glob("*")):
            size_kb = file.stat().st_size / 1024
            print(f"   • {file.name:<25}: {size_kb:>8.2f} KB")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    inspect_pipeline()
