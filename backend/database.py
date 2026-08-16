"""Inisialisasi SQLAlchemy.

Objek `db` dipisahkan dari app.py supaya models.py dan services/
dapat mengimpornya tanpa circular import.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Hubungkan SQLAlchemy ke app Flask lalu buat tabel bila belum ada."""
    db.init_app(app)

    # Import models di dalam fungsi agar tabel sudah terdaftar
    # di metadata sebelum create_all() dipanggil.
    from backend import models  # noqa: F401

    with app.app_context():
        db.create_all()


def reset_db(app):
    """Hapus semua tabel lalu buat ulang. Dipakai untuk development."""
    from backend import models  # noqa: F401

    with app.app_context():
        db.drop_all()
        db.create_all()
