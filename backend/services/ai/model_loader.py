"""Pemuat random_forest_pipeline.pkl.

Tanggung jawab file ini:

1. Memuat pipeline HANYA saat pertama kali dibutuhkan (lazy), bukan saat
   import. File model berukuran ~79 MB, jadi memuatnya saat import akan
   memperlambat startup Flask dan membuat seluruh server gagal jalan bila
   file tidak ada.
2. Menyimpan hasil load di cache (satu proses = satu kali load).
3. Tidak pernah melempar exception ke pemanggil yang tidak siap. Status
   pemuatan dapat dibaca lewat `model_status()` untuk /api/health.
4. Membaca lokasi file dari konfigurasi RF_MODEL_PATH.

CATATAN VERSI (penting, jangan diabaikan)
-----------------------------------------
Pipeline ini di-pickle memakai scikit-learn 1.7.2 (terbaca dari atribut
`_sklearn_version` di dalam file). Memuatnya dengan versi scikit-learn lain
dapat memunculkan InconsistentVersionWarning atau, pada perbedaan versi
besar, gagal total. Karena itu requirements.txt me-pin scikit-learn==1.7.2.

scikit-learn 1.7.2 belum mendukung Python 3.14, sehingga project dijalankan
memakai virtualenv Python 3.13 (lihat README).
"""

import threading
from pathlib import Path

# Status pemuatan model, dibaca oleh /api/health.
_state = {
    "loaded": False,
    "status": "NOT_LOADED",  # NOT_LOADED | OK | ERROR
    "error": None,
    "path": None,
    "sklearn_version_runtime": None,
    "sklearn_version_model": None,
    "warnings": [],
}

_pipeline = None
_lock = threading.Lock()

# Lokasi default: backend/models_store/random_forest_pipeline.pkl
_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "models_store"
    / "random_forest_pipeline.pkl"
)

_configured_path = None


def configure(model_path=None) -> None:
    """Tentukan lokasi file model. Dipanggil dari create_app().

    Memanggil ini akan mereset cache, sehingga model dimuat ulang dari path
    baru pada pemakaian berikutnya.
    """
    global _configured_path, _pipeline
    with _lock:
        _configured_path = Path(model_path) if model_path else None
        _pipeline = None
        _state.update(
            loaded=False, status="NOT_LOADED", error=None, warnings=[],
            path=str(resolve_path()),
        )


def resolve_path() -> Path:
    """Path file model yang sedang dipakai."""
    return _configured_path or _DEFAULT_PATH


def _load() -> None:
    """Muat pipeline. Mengisi _state, tidak melempar exception."""
    global _pipeline

    import warnings as _warnings

    path = resolve_path()
    _state["path"] = str(path)

    try:
        import sklearn

        _state["sklearn_version_runtime"] = sklearn.__version__
    except Exception:  # noqa: BLE001
        _state["sklearn_version_runtime"] = None

    if not path.exists():
        _pipeline = None
        _state.update(
            loaded=False,
            status="ERROR",
            error=(
                f"File model tidak ditemukan: {path}. "
                "Letakkan random_forest_pipeline.pkl di lokasi tersebut atau "
                "set RF_MODEL_PATH di .env (lihat README)."
            ),
        )
        return

    try:
        import joblib

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            loaded = joblib.load(path)
            pesan = [f"{w.category.__name__}: {w.message}" for w in caught]

        # Pipeline harus punya predict & predict_proba agar dapat dipakai.
        if not hasattr(loaded, "predict") or not hasattr(loaded, "predict_proba"):
            raise TypeError(
                "Objek yang dimuat bukan estimator scikit-learn dengan "
                "predict()/predict_proba()."
            )

        _pipeline = loaded
        _state.update(
            loaded=True,
            status="OK",
            error=None,
            warnings=pesan,
            sklearn_version_model=getattr(loaded, "_sklearn_version", None),
        )

    except Exception as error:  # noqa: BLE001 - fail-safe
        _pipeline = None
        _state.update(
            loaded=False,
            status="ERROR",
            error=f"{type(error).__name__}: {error}",
        )


def get_rf_pipeline():
    """Kembalikan pipeline yang sudah dimuat.

    Melempar RuntimeError bila model tidak tersedia. Pemanggil (hotspot
    service) menangkap ini dan mengubahnya menjadi status terstruktur.
    """
    global _pipeline

    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                _load()

    if _pipeline is None:
        raise RuntimeError(_state["error"] or "Model Random Forest tidak tersedia.")

    return _pipeline


def try_load() -> bool:
    """Coba muat model tanpa melempar exception. True bila berhasil.

    Dipakai saat startup untuk mencatat status lebih awal, dan oleh test.
    """
    try:
        get_rf_pipeline()
        return True
    except Exception:  # noqa: BLE001
        return False


def model_status() -> dict:
    """Status pemuatan model untuk /api/health dan dashboard."""
    return {
        "loaded": _state["loaded"],
        "status": _state["status"],
        "error": _state["error"],
        "path": _state["path"] or str(resolve_path()),
        "sklearn_runtime": _state["sklearn_version_runtime"],
        "sklearn_model": _state["sklearn_version_model"],
        "load_warnings": list(_state["warnings"]),
    }


def model_metadata() -> dict:
    """Metadata pipeline (nama fitur, kelas target, jenis estimator).

    Dibaca langsung dari objek model, tidak ada nilai yang ditulis manual.
    Mengembalikan {"available": False, ...} bila model belum dapat dimuat.
    """
    try:
        pipeline = get_rf_pipeline()
    except Exception as error:  # noqa: BLE001
        return {"available": False, "error": str(error)}

    feature_names = getattr(pipeline, "feature_names_in_", None)
    classes = getattr(pipeline, "classes_", None)

    info = {
        "available": True,
        "estimator": type(pipeline).__name__,
        "feature_names": [str(name) for name in feature_names]
        if feature_names is not None
        else [],
        "n_features_in": int(getattr(pipeline, "n_features_in_", 0) or 0),
        "classes": [str(label) for label in classes] if classes is not None else [],
    }

    # Langkah pipeline, bila memang berupa Pipeline.
    steps = getattr(pipeline, "steps", None)
    if steps:
        info["steps"] = [
            {"name": str(name), "type": type(step).__name__} for name, step in steps
        ]

    classifier = None
    named = getattr(pipeline, "named_steps", {}) or {}
    for step in named.values():
        if hasattr(step, "n_estimators"):
            classifier = step
            break
    if classifier is not None:
        info["n_estimators"] = int(getattr(classifier, "n_estimators", 0) or 0)

    return info


def expected_features() -> list[str]:
    """Nama fitur sesuai urutan yang diharapkan pipeline.

    Diambil dari model itu sendiri (feature_names_in_), tidak ditulis manual,
    supaya tidak ada kemungkinan salah tebak.
    """
    meta = model_metadata()
    return meta.get("feature_names", []) if meta.get("available") else []


def category_vocabulary() -> dict:
    """Kosakata tiap fitur kategorikal, dibaca dari OneHotEncoder di dalam
    pipeline. Dipakai untuk memvalidasi nilai konteks sebelum prediksi.

    Return {} bila model belum dapat dimuat atau strukturnya tidak dikenali.
    """
    try:
        pipeline = get_rf_pipeline()
    except Exception:  # noqa: BLE001
        return {}

    vocab: dict[str, list[str]] = {}
    named = getattr(pipeline, "named_steps", {}) or {}

    for step in named.values():
        transformers = getattr(step, "transformers_", None)
        if not transformers:
            continue
        for _name, trans, cols in transformers:
            if not isinstance(cols, (list, tuple)):
                continue
            categories = getattr(trans, "categories_", None)
            if categories is None and hasattr(trans, "steps"):
                for _sn, sub in trans.steps:
                    if hasattr(sub, "categories_"):
                        categories = sub.categories_
                        break
            if categories is None:
                continue
            for col, cats in zip(cols, categories):
                vocab[str(col)] = [str(value) for value in cats]

    return vocab
