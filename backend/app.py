"""Titik masuk aplikasi ASEP-JAGA.

Menjalankan server:
    python -m backend.app
atau:
    python backend/app.py

Kedua cara didukung; lihat penyesuaian sys.path di bagian bawah file.
"""

import sys
from pathlib import Path

# Supaya `python backend/app.py` tetap dapat mengimpor paket `backend`,
# root project ditambahkan ke sys.path sebelum import lokal dijalankan.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template  # noqa: E402

from backend.config import DATA_DIR, Config  # noqa: E402
from backend.database import init_db  # noqa: E402
from backend.routes import register_blueprints  # noqa: E402


def create_app(config_object=Config) -> Flask:
    """Application factory. Dipakai juga oleh pytest dengan TestConfig."""
    app = Flask(
        __name__,
        template_folder=config_object.TEMPLATE_DIR,
        static_folder=config_object.STATIC_DIR,
    )
    app.config.from_object(config_object)

    # Folder data/ dibuat lebih dulu supaya SQLite tidak gagal membuat file.
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    init_db(app)
    init_ai(app)
    register_blueprints(app)
    register_pages(app)
    register_error_handlers(app)

    return app


def init_ai(app: Flask) -> None:
    """Siapkan lapisan AI: tentukan lokasi random_forest_pipeline.pkl.

    Model TIDAK pernah dimuat pada level import. Bila RF_PRELOAD aktif,
    model dimuat sekarang supaya kesalahan konfigurasi (file hilang, versi
    scikit-learn tidak cocok) terlihat saat startup, bukan saat kejadian
    darurat pertama.

    Kegagalan memuat model TIDAK menghentikan server. Alur emergency tetap
    berjalan tanpa hotspot risk; verifikasi tahap 2 menyesuaikan bobotnya.
    """
    from backend.services.ai import model_loader

    model_loader.configure(app.config.get("RF_MODEL_PATH"))

    if not app.config.get("RF_PRELOAD", False):
        return

    # Saat pytest berjalan, model tidak dimuat otomatis.
    # Alasannya: `app = create_app()` di bawah file ini dieksekusi pada level
    # modul memakai Config biasa (RF_PRELOAD=True), sehingga setiap import
    # `backend.app` akan memuat file 79 MB — termasuk saat pengumpulan test.
    # Test yang memang menguji model memuatnya sendiri lewat model_loader.
    if "pytest" in sys.modules:
        app.logger.info("[RF_MODEL] preload dilewati karena pytest terdeteksi.")
        return

    if model_loader.try_load():
        meta = model_loader.model_metadata()
        app.logger.info(
            "[RF_MODEL] dimuat: %s, %s fitur, kelas %s",
            meta.get("estimator"),
            meta.get("n_features_in"),
            meta.get("classes"),
        )
        for pesan in model_loader.model_status().get("load_warnings", []):
            app.logger.warning("[RF_MODEL] %s", pesan)
    else:
        # Dicatat sebagai error, tetapi server tetap dijalankan.
        app.logger.error(
            "[RF_MODEL] gagal dimuat: %s", model_loader.model_status().get("error")
        )


def register_pages(app: Flask) -> None:
    """Halaman dashboard (HTML). Data diambil JavaScript lewat REST API."""

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/incidents")
    def incidents():
        return render_template("incidents.html")

    @app.get("/incidents/<incident_id>")
    def incident_detail(incident_id: str):
        return render_template("incident_detail.html", incident_id=incident_id)

    @app.get("/devices")
    def devices():
        return render_template("devices.html")

    @app.get("/history")
    def history():
        return render_template("history.html")


def register_error_handlers(app: Flask) -> None:
    """Error handler agar request ke /api/* selalu menerima JSON,
    bukan halaman HTML error bawaan Flask."""

    from flask import request

    def wants_json() -> bool:
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(error):
        if wants_json():
            return jsonify({"success": False, "error": "Endpoint tidak ditemukan."}), 404
        return render_template("index.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        if wants_json():
            return (
                jsonify({"success": False, "error": "Metode HTTP tidak diizinkan."}),
                405,
            )
        return "Metode tidak diizinkan", 405

    @app.errorhandler(500)
    def server_error(error):
        # Rollback supaya session database tidak tertinggal dalam
        # keadaan rusak setelah terjadi error.
        from backend.database import db

        db.session.rollback()
        if wants_json():
            return (
                jsonify({"success": False, "error": "Terjadi kesalahan di server."}),
                500,
            )
        return "Terjadi kesalahan di server", 500


app = create_app()


if __name__ == "__main__":
    print("=" * 60)
    print("  ASEP-JAGA COMMAND CENTER")
    print("=" * 60)
    print(f"  Dashboard : http://127.0.0.1:{Config.PORT}/dashboard")
    print(f"  API health: http://127.0.0.1:{Config.PORT}/api/health")
    print(f"  Database  : {Config.SQLALCHEMY_DATABASE_URI}")
    print("=" * 60)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
