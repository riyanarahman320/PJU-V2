def get_lighting_condition(hour, weather, rainfall):
    """
    Estimasi kondisi pencahayaan berdasarkan
    jam, cuaca, dan curah hujan.

    Output:
    Good
    Moderate
    Poor
    """

    # Normalisasi input
    weather = str(weather).lower()

    try:
        rainfall = float(rainfall or 0)
    except:
        rainfall = 0

    # ============================================
    # 1. TENTUKAN SIANG / TRANSISI / MALAM
    # ============================================

    if 6 <= hour < 17:
        period = "day"

    elif 17 <= hour < 19:
        period = "transition"

    else:
        period = "night"

    # ============================================
    # 2. SIANG
    # ============================================

    if period == "day":

        # Hujan deras / kondisi sangat gelap
        if rainfall >= 10:
            lighting = "Moderate"

        else:
            lighting = "Good"

    # ============================================
    # 3. MASA TRANSISI
    # ============================================

    elif period == "transition":

        if rainfall >= 10:
            lighting = "Poor"

        else:
            lighting = "Moderate"

    # ============================================
    # 4. MALAM
    # ============================================

    else:

        lighting = "Poor"

    # ============================================
    # 5. STATUS GELAP
    # ============================================

    is_dark = period in [
        "transition",
        "night"
    ]

    return {
        "lighting_condition": lighting,
        "is_dark": is_dark,
        "period": period,
        "source": "estimated"
    }