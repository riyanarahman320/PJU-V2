"""Hotspot risk predictor — CORE (milik pengguna, logika dipertahankan).

Berasal dari AI/model/rf_predictor.py.

SATU-SATUNYA perubahan terhadap file asli:

1. Model TIDAK lagi dimuat saat import.
   File asli menjalankan `joblib.load("ai/random_forest_pipeline.pkl")` pada
   level modul. Akibatnya:
     - path relatif terhadap current working directory (salah bila Flask
       dijalankan dari folder lain),
     - path aslinya tidak sesuai lokasi nyata file (AI/model/...),
     - proses Flask gagal start total bila file model tidak ada.
   Sekarang pipeline diambil lewat model_loader (lazy + cache + path env).

2. Mapping probability dibuat aman untuk jumlah kelas apa pun.
   File asli mengakses pipeline.classes_[0], [1], [2] secara hardcode.
   Model nyata memang punya 3 kelas ['High', 'Low', 'Medium'], jadi hasilnya
   sama, tetapi versi ini tidak pecah bila kelas berubah.

LOGIKA PREDIKSI, THRESHOLD, PRIORITY, WARNA, DAN REKOMENDASI TIDAK DIUBAH.
Model tidak di-retrain dan tidak diganti.
"""

import pandas as pd

from backend.services.ai.model_loader import get_rf_pipeline


def predict_risk(data):
    """Prediksi tingkat kerawanan lokasi memakai random_forest_pipeline.pkl.

    Parameter
    ---------
    data : dict
        Berisi 18 fitur sesuai pipeline.feature_names_in_. Penyusunan dict
        ini adalah tanggung jawab context/hotspot_service.py, bukan file ini.

    Return
    ------
    dict dengan kunci: risk_level, confidence, priority, status_color,
    recommendation, probability.
    """
    pipeline = get_rf_pipeline()

    df = pd.DataFrame([data])

    prediction = pipeline.predict(df)[0]

    probability = pipeline.predict_proba(df)[0]

    confidence = float(max(probability) * 100)

    if prediction == "High":

        priority = "HIGH"

        color = "#FF0000"

        recommendation = [
            "Prioritaskan patroli",
            "Aktifkan monitoring CCTV",
            "Kirim unit terdekat"
        ]

    elif prediction == "Medium":

        priority = "MEDIUM"

        color = "#FFC107"

        recommendation = [
            "Monitoring berkala",
            "Siapkan patroli"
        ]

    else:

        priority = "LOW"

        color = "#28A745"

        recommendation = [
            "Monitoring normal"
        ]

    return {

        "risk_level": str(prediction),

        "confidence": round(confidence, 2),

        "priority": priority,

        "status_color": color,

        "recommendation": recommendation,

        # Dibuat dinamis (asli: indeks 0/1/2 hardcode).
        "probability": {
            str(label): round(float(value * 100), 2)
            for label, value in zip(pipeline.classes_, probability)
        },
    }
