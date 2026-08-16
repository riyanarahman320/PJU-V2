import os
import requests


def get_traffic(latitude, longitude):

    api_key = os.getenv("TOMTOM_API_KEY")

    if not api_key:
        return {
            "traffic_level": "Low",
            "current_speed": None,
            "free_flow_speed": None,
            "speed_ratio": None,
            "confidence": None,
            "status": "fallback",
            "message": "TOMTOM_API_KEY belum tersedia"
        }

    url = (
        "https://api.tomtom.com/"
        "traffic/services/4/"
        "flowSegmentData/"
        "relative/"
        "10/"
        "json"
    )

    params = {
        "key": api_key,
        "point": f"{latitude},{longitude}",
        "unit": "kmph"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        flow = data.get(
            "flowSegmentData",
            {}
        )

        current_speed = flow.get(
            "currentSpeed"
        )

        free_flow_speed = flow.get(
            "freeFlowSpeed"
        )

        confidence = flow.get(
            "confidence"
        )

        if (
            current_speed is None
            or free_flow_speed is None
            or free_flow_speed <= 0
        ):

            traffic_level = "Low"
            speed_ratio = None

        else:

            speed_ratio = (
                current_speed /
                free_flow_speed
            )

            if speed_ratio >= 0.70:

                traffic_level = "Low"

            elif speed_ratio >= 0.40:

                traffic_level = "Medium"

            else:

                traffic_level = "High"

        return {

            "traffic_level":
                traffic_level,

            "current_speed":
                current_speed,

            "free_flow_speed":
                free_flow_speed,

            "speed_ratio":
                speed_ratio,

            "confidence":
                confidence,

            "status":
                "success"
        }

    except Exception as e:

        print(
            "Traffic API error:",
            e
        )

        return {

            "traffic_level":
                "Low",

            "current_speed":
                None,

            "free_flow_speed":
                None,

            "speed_ratio":
                None,

            "confidence":
                None,

            "status":
                "error",

            "message":
                str(e)
        }
    