"""Lapisan AI ASEP-JAGA.


Struktur:

    core/                 file asli milik pengguna
        ai_models.py           adapter audio feature-based (bukan CNN/TinyML)
        rf_predictor.py        pemakai random_forest_pipeline.pkl

    model_loader.py       pemuat .pkl (lazy, ter-cache, anti-crash)
    audio_service.py      adapter audio untuk backend

CATATAN JUJUR TENTANG "AI" DI SINI
----------------------------------
1. Audio (ai_models.AudioDistressModel) BUKAN CNN, BUKAN neural network,
   BUKAN TinyML, dan BUKAN deep learning. Implementasinya murni Python:
   fitur ringkas diubah menjadi probabilitas lewat pembobotan manual dan
   softmax. Docstring file aslinya juga menyatakan hal yang sama.
   Bila perangkat mengirim `class_probabilities` dari model di sisi
   perangkat, nilai itu dipakai langsung (source='hardware-model-output').

2. Random Forest (random_forest_pipeline.pkl) ADALAH model machine learning
   sungguhan: scikit-learn RandomForestClassifier dengan 300 pohon, dilatih
   di luar project ini. Model tidak di-retrain dan tidak diganti.

3. Keputusan akhir CONFIRMED/FALSE_ALARM TIDAK diambil oleh AI mana pun.
   Keputusan diambil oleh verifikasi tahap 2 yang rule-based
   (lihat services/verification.py).
"""

from backend.services.ai import model_loader  # noqa: F401
