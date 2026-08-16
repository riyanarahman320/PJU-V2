"""Blueprint API ASEP-JAGA beserta helper bersama.

Semua endpoint memakai helper di file ini supaya bentuk respons dan
cara autentikasi konsisten.

Bentuk respons sukses:
    {"success": true, "data": {...}}

Bentuk respons gagal:
    {"success": false, "error": "pesan", "details": [...]}
"""

import hmac
from functools import wraps

from flask import current_app, jsonify, request


def ok(data=None, status: int = 200):
    """Respons sukses."""
    return jsonify({"success": True, "data": data if data is not None else {}}), status


def fail(message: str, status: int = 400, details=None):
    """Respons gagal."""
    body = {"success": False, "error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def require_device_api_key(view):
    """Lindungi endpoint yang dipanggil perangkat (ESP32 / simulator).

    API key dikirim lewat header:
        X-API-Key: <DEVICE_API_KEY>

    Catatan keamanan: ini autentikasi tingkat dasar untuk prototype.
    Semua perangkat memakai satu kunci yang sama, dan tanpa HTTPS kunci
    tersebut terbaca di jaringan. Untuk penggunaan nyata dibutuhkan
    kunci per perangkat dan koneksi HTTPS.

    Endpoint dashboard TIDAK dilindungi API key. Selama server hanya
    dijalankan di jaringan lokal atau lewat ngrok untuk pengujian, hal
    ini masih dapat diterima. Bila server dipublikasikan, dashboard
    perlu login terlebih dahulu.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = current_app.config.get("DEVICE_API_KEY")
        provided = request.headers.get("X-API-Key", "")

        if not expected:
            return fail("DEVICE_API_KEY belum dikonfigurasi di server.", 500)
        if provided != expected:
            return fail("API key tidak valid atau tidak dikirim.", 401)
        return view(*args, **kwargs)

    return wrapper


def require_operator_api_key(view):
    """Lindungi endpoint yang dipanggil operator lewat dashboard.

    API key dikirim lewat header:
        X-Operator-Key: <DEVICE_CONFIG_API_KEY>

    Kunci dibaca dari environment (DEVICE_CONFIG_API_KEY) dan TIDAK
    memiliki nilai default di dalam kode. Bila variabel tersebut belum
    diisi, endpoint menolak seluruh request dengan HTTP 500 — bukan
    membuka akses. Ini disengaja: kunci kosong tidak boleh berarti
    "tanpa autentikasi".

    Perbandingan memakai hmac.compare_digest agar lamanya proses tidak
    bergantung pada seberapa banyak karakter yang cocok.

    Catatan keamanan untuk prototype: ini satu kunci bersama untuk semua
    operator, tanpa identitas per pengguna dan tanpa masa berlaku. Tanpa
    HTTPS, kunci terbaca di jaringan. Untuk penggunaan nyata dibutuhkan
    login per operator, dan sebaiknya pencatatan siapa mengubah apa.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = (current_app.config.get("DEVICE_CONFIG_API_KEY") or "").strip()
        provided = request.headers.get("X-Operator-Key", "")

        if not expected:
            return fail(
                "DEVICE_CONFIG_API_KEY belum dikonfigurasi di server. "
                "Isi variabel tersebut di .env sebelum memakai endpoint ini.",
                500,
            )
        if not provided:
            return fail(
                "Header 'X-Operator-Key' tidak dikirim.",
                401,
            )
        if not hmac.compare_digest(provided, expected):
            return fail("Operator key tidak valid.", 403)
        return view(*args, **kwargs)

    return wrapper


def get_json_body():
    """Ambil body JSON tanpa memunculkan exception bila formatnya salah.
    Mengembalikan None bila body bukan JSON yang sah.
    """
    return request.get_json(silent=True)


def offline_timeout() -> int:
    """Ambil batas waktu offline dari konfigurasi aplikasi."""
    return current_app.config.get("DEVICE_OFFLINE_TIMEOUT", 60)


def register_blueprints(app):
    """Daftarkan seluruh blueprint API ke aplikasi Flask."""
    from backend.routes.commands import commands_bp
    from backend.routes.devices import devices_bp
    from backend.routes.emergencies import emergencies_bp
    from backend.routes.health import health_bp
    from backend.routes.history import history_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(emergencies_bp)
    app.register_blueprint(commands_bp)
    app.register_blueprint(history_bp)
