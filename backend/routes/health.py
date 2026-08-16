"""Endpoint kesehatan server dan statistik dashboard."""

from flask import Blueprint, current_app

from backend.models import utcnow
from backend.routes import ok, offline_timeout
from backend.services import verification
from backend.services.ai import audio_service, model_loader
from backend.services.device_service import refresh_offline_status
from backend.services.incident_service import build_statistics

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.get("/health")
def health():
    """GET /api/health

    Dipakai ESP32, simulator, dan dashboard untuk memastikan server hidup.
    Sengaja tidak memerlukan API key supaya mudah diuji dari browser.
    """
    return ok(
        {
            "status": "OK",
            "service": "ASEP-JAGA",
            "version": "0.1.0",
            "server_time": utcnow().isoformat(),
            "database": current_app.config["SQLALCHEMY_DATABASE_URI"],
            "verification": {
                # Dilaporkan apa adanya: verifikasi tahap 2 adalah
                # RULE-BASED, bukan model AI. Lihat services/verification.py.
                "method": (
                    "EXTERNAL_MODULE"
                    if verification.ai_verifier_active()
                    else "RULE_BASED_SECOND_LEVEL"
                ),
                "external_module_loaded": verification.ai_verifier_active(),
                "is_ai_model": False,
                "note": (
                    "Keputusan CONFIRMED/FALSE_ALARM dihasilkan aturan dan "
                    "pembobotan manual, bukan model machine learning."
                ),
                "server_confirm_threshold": current_app.config[
                    "SERVER_CONFIRM_THRESHOLD"
                ],
                "audio_confidence_min": current_app.config["AUDIO_CONFIDENCE_MIN"],
            },
            "ai": {
                "mode": current_app.config.get("AI_MODE", "real"),
                # Audio: adapter feature-based, BUKAN CNN/TinyML.
                "audio": audio_service.model_info(),
                # Hotspot: RandomForestClassifier scikit-learn (model nyata).
                "hotspot_model": model_loader.model_status(),
                "hotspot_metadata": model_loader.model_metadata(),
            },
            "context_services": {
                "weather": {
                    "provider": "Open-Meteo",
                    "requires_api_key": False,
                    "status": "CONFIGURED",
                },
                "traffic": {
                    "provider": "TomTom",
                    "requires_api_key": True,
                    # Hanya melaporkan ADA/TIDAK, bukan nilai API key.
                    "api_key_present": current_app.config.get(
                        "TOMTOM_API_KEY_PRESENT", False
                    ),
                    "status": (
                        "CONFIGURED"
                        if current_app.config.get("TOMTOM_API_KEY_PRESENT")
                        else "FALLBACK_NO_API_KEY"
                    ),
                },
                "lighting": {
                    "provider": "internal",
                    "status": "ESTIMATED",
                    "note": "Diperkirakan dari jam dan cuaca, bukan sensor cahaya.",
                },
                "history": {
                    "provider": "database sendiri",
                    "status": "REAL_OWN_DATABASE",
                },
            },
            "device_offline_timeout": offline_timeout(),
        }
    )


@health_bp.get("/statistics")
def statistics():
    """GET /api/statistics — angka untuk kartu di dashboard."""
    timeout = offline_timeout()
    # Status offline disegarkan lebih dahulu supaya angka yang tampil
    # sesuai kondisi terkini tanpa perlu scheduler terpisah.
    refresh_offline_status(timeout)
    return ok(build_statistics(timeout))
