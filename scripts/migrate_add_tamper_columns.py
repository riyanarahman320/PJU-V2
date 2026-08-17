"""Migrasi: tambah kolom sensor tamper ke tabel devices.

MENGAPA SKRIP INI ADA
---------------------
Project ini memakai Flask-SQLAlchemy tanpa Alembic. `db.create_all()` hanya
MEMBUAT tabel yang belum ada; ia TIDAK menambah kolom pada tabel yang sudah
ada. Database yang sudah dipakai (berisi device dan incident) perlu
disesuaikan agar kolom tamper tersedia.

Tanpa migrasi ini, POST /api/device/tamper akan gagal dengan OperationalError
"no such column: devices.tamper" pada database lama.

Skrip memakai ALTER TABLE ADD COLUMN, yang pada SQLite:
  - tidak menyalin ulang tabel,
  - tidak menghapus data yang sudah ada,
  - aman dijalankan berulang (kolom yang sudah ada dilewati).

Jalankan:
    .venv\\Scripts\\python.exe scripts\\migrate_add_tamper_columns.py

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

# Kolom baru: (nama_kolom, tipe SQL, definisi tambahan)
#
# `tamper` memakai DEFAULT 0 karena kolomnya NOT NULL dan baris yang sudah ada
# harus punya nilai. Nilai 0 (belum tamper) dipilih sadar: menandai seluruh
# perangkat lama sebagai tamper akan memunculkan peringatan palsu di dashboard
# untuk perangkat yang sebenarnya utuh.
#
# `tamper_since` dan `tamper_last_report` tanpa DEFAULT: NULL berarti belum
# pernah ada laporan, dan itu memang keadaan yang benar untuk data lama.
KOLOM_BARU = {
    "devices": [
        ("tamper", "BOOLEAN", "NOT NULL DEFAULT 0"),
        ("tamper_since", "DATETIME", ""),
        ("tamper_last_report", "DATETIME", ""),
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
