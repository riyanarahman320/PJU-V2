def evaluate_emergency(
    sos,
    audio_confidence,
    hotspot_risk
):
    """
    Menentukan status keadaan darurat berdasarkan:
    - SOS dari tombol
    - confidence Audio AI
    - risk hotspot dari Random Forest

    Output:
    NORMAL
    SUSPICIOUS
    EMERGENCY
    """

    # Normalisasi
    sos = bool(sos)

    try:
        audio_confidence = float(
            audio_confidence or 0
        )
    except:
        audio_confidence = 0.0

    hotspot_risk = str(
        hotspot_risk or "Low"
    ).lower()

    # ==================================================
    # 1. SOS + AUDIO DISTRESS KUAT
    # ==================================================

    if sos and audio_confidence >= 0.70:

        return {
            "emergency_state": "EMERGENCY",
            "confidence": round(
                audio_confidence * 100,
                2
            ),
            "reason": "SOS dan Audio AI menunjukkan indikasi distress",
            "local_action": True,
            "server_confirmation": True
        }

    # ==================================================
    # 2. SOS SAJA
    # ==================================================

    if sos:

        return {
            "emergency_state": "SUSPICIOUS",
            "confidence": round(
                audio_confidence * 100,
                2
            ),
            "reason": "SOS diterima tetapi Audio AI belum mengkonfirmasi distress",
            "local_action": True,
            "server_confirmation": False
        }

    # ==================================================
    # 3. AUDIO DISTRESS TANPA SOS
    # ==================================================

    if audio_confidence >= 0.85:

        if hotspot_risk in [
            "high",
            "medium"
        ]:

            return {
                "emergency_state": "SUSPICIOUS",
                "confidence": round(
                    audio_confidence * 100,
                    2
                ),
                "reason": "Audio AI mendeteksi distress pada lokasi berisiko",
                "local_action": False,
                "server_confirmation": True
            }

    # ==================================================
    # 4. NORMAL
    # ==================================================

    return {
        "emergency_state": "NORMAL",
        "confidence": round(
            audio_confidence * 100,
            2
        ),
        "reason": "Tidak terdapat indikasi keadaan darurat yang cukup kuat",
        "local_action": False,
        "server_confirmation": False
    }