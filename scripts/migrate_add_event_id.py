"""Migrasi: menambahkan kolom `event_id` ke tabel incidents.

MENGAPA PERLU
-------------
Skema database dibuat dengan db.create_all(), yang hanya membuat tabel yang
belum ada. Perintah itu TIDAK menambahkan kolom baru ke tabel yang sudah
terbentuk. Database yang sudah berisi incident karena itu tidak memiliki
kolom `event_id`, dan setiap query ke tabel incidents akan gagal dengan
"no such column: incidents.event_id" sampai migrasi ini dijalankan.

Database yang masih kosong tidak memerlukan skrip ini: create_all() akan
membuat tabel lengkap beserta kolom dan indexnya.

YANG DILAKUKAN
--------------
1. ALTER TABLE incidents ADD COLUMN event_id VARCHAR(64)
2. CREATE UNIQUE INDEX uq_incident_device_event ON incidents(device_id, event_id)

Keduanya aman diulang: skrip memeriksa lebih dulu dan melewati langkah yang
sudah selesai (idempotent).

CATATAN SQLITE
--------------
SQLite tidak mendukung ALTER TABLE ... ADD CONSTRAINT, jadi keunikan dijaga
lewat UNIQUE INDEX. Dua baris dengan event_id NULL tidak dianggap bertabrakan
karena SQLite tidak memperlakukan NULL sebagai nilai yang sama, sehingga
incident lama yang tidak memiliki event_id tetap valid.

CARA PAKAI
----------
    python scripts/migrate_add_event_id.py
    python scripts/migrate_add_event_id.py --dry-run

Disarankan menyalin file database lebih dulu sebagai cadangan.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

NAMA_INDEX = "uq_incident_device_event"


def lokasi_database() -> Path | None:
    """Ambil path file SQLite dari konfigurasi aplikasi.

    Dibaca dari Config, bukan ditebak, supaya skrip ini selalu menyasar
    database yang sama dengan yang dipakai server.
    """
    from backend.config import Config

    uri = Config.SQLALCHEMY_DATABASE_URI
    if not uri.startswith("sqlite:"):
        print(f"Database bukan SQLite: {uri}")
        print("Skrip ini hanya menangani SQLite. Untuk database lain,")
        print("jalankan perintah berikut secara manual:")
        print("  ALTER TABLE incidents ADD COLUMN event_id VARCHAR(64);")
        print(f"  CREATE UNIQUE INDEX {NAMA_INDEX}")
        print("    ON incidents (device_id, event_id);")
        return None

    # sqlite:///C:/path/file.db  ->  C:/path/file.db
    path = uri.replace("sqlite:///", "", 1)
    if path in ("", ":memory:"):
        print("Database in-memory; tidak ada yang perlu dimigrasikan.")
        return None

    return Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tambahkan kolom event_id ke tabel incidents."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tampilkan rencana perubahan tanpa mengubah database.",
    )
    argumen = parser.parse_args()

    import sqlite3

    berkas = lokasi_database()
    if berkas is None:
        return 0

    print(f"Database : {berkas}")

    if not berkas.exists():
        print("File database belum ada.")
        print("Tidak perlu migrasi: db.create_all() akan membuat tabel")
        print("lengkap beserta kolom event_id saat server pertama dijalankan.")
        return 0

    koneksi = sqlite3.connect(str(berkas))
    try:
        kursor = koneksi.cursor()

        # Tabel incidents mungkin belum ada bila server belum pernah jalan.
        kursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'incidents'"
        )
        if kursor.fetchone() is None:
            print("Tabel 'incidents' belum ada; tidak ada yang dimigrasikan.")
            return 0

        kursor.execute("PRAGMA table_info(incidents)")
        kolom = [baris[1] for baris in kursor.fetchall()]
        ada_kolom = "event_id" in kolom

        kursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND name = ?",
            (NAMA_INDEX,),
        )
        ada_index = kursor.fetchone() is not None

        kursor.execute("SELECT COUNT(*) FROM incidents")
        jumlah = kursor.fetchone()[0]

        print(f"Incident tersimpan : {jumlah}")
        print(f"Kolom event_id     : {'sudah ada' if ada_kolom else 'BELUM ADA'}")
        print(f"Index {NAMA_INDEX} : {'sudah ada' if ada_index else 'BELUM ADA'}")

        if ada_kolom and ada_index:
            print()
            print("Migrasi sudah pernah dijalankan. Tidak ada perubahan.")
            return 0

        rencana = []
        if not ada_kolom:
            rencana.append(
                "ALTER TABLE incidents ADD COLUMN event_id VARCHAR(64)"
            )
        if not ada_index:
            rencana.append(
                f"CREATE UNIQUE INDEX {NAMA_INDEX} "
                "ON incidents (device_id, event_id)"
            )

        print()
        print("Rencana perubahan:")
        for perintah in rencana:
            print(f"  {perintah};")

        if argumen.dry_run:
            print()
            print("--dry-run: database TIDAK diubah.")
            return 0

        print()
        for perintah in rencana:
            kursor.execute(perintah)
            print(f"[OK] {perintah}")

        koneksi.commit()

        print()
        print("Migrasi selesai.")
        print(f"{jumlah} incident lama tetap tersimpan dengan event_id = NULL,")
        print("yang berarti 'dibuat tanpa idempotency key' — bukan kesalahan.")
        return 0

    except sqlite3.Error as error:
        koneksi.rollback()
        print(f"GAGAL: {error}")
        print("Database tidak diubah (rollback).")
        return 1
    finally:
        koneksi.close()


if __name__ == "__main__":
    sys.exit(main())