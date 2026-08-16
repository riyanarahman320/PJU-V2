import joblib
import pandas as pd

pipeline = joblib.load("ai/random_forest_pipeline.pkl")


def predict_risk(data):

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

        "risk_level": prediction,

        "confidence": round(confidence,2),

        "priority": priority,

        "status_color": color,

        "recommendation": recommendation,

        "probability": {

            pipeline.classes_[0]: round(float(probability[0]*100),2),

            pipeline.classes_[1]: round(float(probability[1]*100),2),

            pipeline.classes_[2]: round(float(probability[2]*100),2)

        }

    }