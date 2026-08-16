"""Migrasi: tambah kolom konteks & konfigurasi device.

MENGAPA SKRIP INI ADA
---------------------
Project ini memakai Flask-SQLAlchemy tanpa Alembic. `db.create_all()` hanya
MEMBUAT tabel yang belum ada; ia TIDAK menambah kolom pada tabel yang sudah
ada. Karena FASE 7 menambah banyak kolom, database yang sudah pernah dibuat
perlu disesuaikan.

Skrip ini memakai ALTER TABLE ADD COLUMN, yang pada SQLite:
  - tidak menyalin ulang tabel,
  - tidak menghapus data yang sudah ada,
  - aman dijalankan berulang (kolom yang sudah ada dilewati).

Jalankan:
    .venv\\Scripts\\python.exe scripts\\migrate_add_context_columns.py

Skrip ini TIDAK menghapus tabel dan TIDAK menghapus baris.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.database import db  # noqa: E402

# Kolom baru per tabel: (nama_kolom, tipe SQL, definisi tambahan)
KOLOM_BARU = {
    "devices": [
        ("village", "VARCHAR(64)", ""),
        ("road_type", "VARCHAR(32)", ""),
        ("area_type", "VARCHAR(32)", ""),
        ("nearby_cctv", "VARCHAR(8)", ""),
        ("nearby_police_post", "VARCHAR(8)", ""),
        # Tanpa DEFAULT: NULL berarti NOT_AVAILABLE dan itu memang disengaja.
        ("population_density", "FLOAT", ""),
        ("public_event", "VARCHAR(8)", "DEFAULT 'No'"),
        ("holiday", "VARCHAR(8)", "DEFAULT 'No'"),
    ],
    "incidents": [
        ("audio_distress_probability", "FLOAT", ""),
        ("ai_status", "VARCHAR(16)", ""),
        ("audio_model", "VARCHAR(64)", ""),
        ("audio_source", "VARCHAR(48)", ""),
        ("hotspot_level", "VARCHAR(16)", ""),
        ("hotspot_confidence", "FLOAT", ""),
        ("hotspot_status", "VARCHAR(32)", ""),
        ("temperature", "FLOAT", ""),
        ("rainfall", "FLOAT", ""),
        ("traffic_level", "VARCHAR(32)", ""),
        ("lighting_condition", "VARCHAR(32)", ""),
        ("context_snapshot", "TEXT", ""),
        ("verification_method", "VARCHAR(48)", ""),
    ],
}


def main() -> int:
    app = create_app()

    with app.app_context():
        # Tabel yang belum ada dibuat lebih dulu (database baru).
        db.create_all()

        inspector = inspect(db.engine)
        tabel_ada = set(inspector.get_table_names())

        total_ditambah = 0

        for tabel, kolom_kolom in KOLOM_BARU.items():
            if tabel not in tabel_ada:
                print(f"[LEWAT] tabel '{tabel}' tidak ada.")
                continue

            kolom_sekarang = {
                kolom["name"] for kolom in inspector.get_columns(tabel)
            }

            for nama, tipe, tambahan in kolom_kolom:
                if nama in kolom_sekarang:
                    print(f"[ADA]   {tabel}.{nama}")
                    continue

                sql = f"ALTER TABLE {tabel} ADD COLUMN {nama} {tipe}"
                if tambahan:
                    sql += f" {tambahan}"

                db.session.execute(text(sql))
                total_ditambah += 1
                print(f"[BARU]  {tabel}.{nama} {tipe} {tambahan}".rstrip())

        db.session.commit()

        print("-" * 60)
        print(f"Selesai. {total_ditambah} kolom ditambahkan.")

        # Tampilkan jumlah baris supaya terbukti tidak ada data yang hilang.
        for tabel in ("devices", "incidents", "commands", "logs"):
            if tabel in tabel_ada:
                jumlah = db.session.execute(
                    text(f"SELECT COUNT(*) FROM {tabel}")
                ).scalar()
                print(f"  {tabel}: {jumlah} baris")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
