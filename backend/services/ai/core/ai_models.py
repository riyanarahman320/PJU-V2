"""AI adapters that run without physical hardware or third-party packages.

The interfaces in this module are intentionally hardware-shaped:

* audio nodes may send class probabilities or compact audio features;
* vibration nodes may send tap count, interval and amplitude scores;
* the hotspot predictor trains on deterministic synthetic data.

The pure-Python implementations make the prototype runnable now. They can be
replaced by a TensorFlow Lite CNN / scikit-learn RandomForest later while the
HTTP contract stays the same.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any


AUDIO_CLASSES = ("Normal", "Scream/Teriakan", "Help/Distress", "Impact/Benturan")
HOTSPOT_FEATURES = ("hour", "weekday", "grid", "history_count", "weather_risk", "event_factor")


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if not math.isfinite(number):
        return low
    return max(low, min(high, number))


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    largest = max(scores.values())
    values = {key: math.exp(value - largest) for key, value in scores.items()}
    total = sum(values.values()) or 1.0
    return {key: round(value / total, 6) for key, value in values.items()}


class AudioDistressModel:
    """Hardware-compatible audio inference adapter.

    A real edge node can send ``class_probabilities`` from its TinyML model.
    During development, compact features are converted into stable mock
    probabilities so the complete ECS flow can run without a microphone.
    """

    model_name = "audio-feature-adapter-v1"

    def predict(self, features: dict[str, Any] | None = None) -> dict[str, Any]:
        features = features or {}
        supplied = features.get("class_probabilities")
        if isinstance(supplied, dict) and supplied:
            probabilities = {label: _clamp(supplied.get(label, 0)) for label in AUDIO_CLASSES}
            total = sum(probabilities.values()) or 1.0
            probabilities = {label: round(value / total, 6) for label, value in probabilities.items()}
            source = "hardware-model-output"
        else:
            # These are compact features that an ESP32-side preprocessor can
            # calculate without sending raw audio to the server.
            energy = _clamp(features.get("energy"))
            peak = _clamp(features.get("peak"))
            zero_crossing_rate = _clamp(features.get("zero_crossing_rate"))
            dominant_frequency = _clamp(float(features.get("dominant_frequency", 2500)) / 8000)
            duration = _clamp(float(features.get("duration_ms", 1000)) / 5000)
            impact = max(peak, min(1.0, energy * 1.2)) if duration < 0.35 else energy * 0.35
            scream = (energy * 0.45) + (zero_crossing_rate * 0.30) + (dominant_frequency * 0.25)
            help_distress = (energy * 0.55) + (zero_crossing_rate * 0.15) + (1.0 - duration) * 0.30
            normal = max(0.05, 1.0 - max(scream, help_distress, impact))
            probabilities = _softmax({
                "Normal": normal * 2.5,
                "Scream/Teriakan": scream * 4.0,
                "Help/Distress": help_distress * 3.5,
                "Impact/Benturan": impact * 4.0,
            })
            source = "feature-fallback"

        distress_probability = round(1.0 - probabilities["Normal"], 6)
        return {
            "model": self.model_name,
            "source": source,
            "class_probabilities": probabilities,
            "audio_distress_probability": distress_probability,
            "assumption": "A = 1 - P(Normal)",
        }


def vibration_pattern_score(features: dict[str, Any] | None = None) -> float:
    """Score the reference pattern: three taps, ~1s intervals, stable amplitude."""
    features = features or {}
    tap_count = float(features.get("tap_count", 0))
    interval_score = _clamp(features.get("interval_score", 0))
    amplitude_consistency = _clamp(features.get("amplitude_consistency", 0))
    count_match = max(0.0, 1.0 - abs(tap_count - 3.0) / 3.0)
    return round((count_match + interval_score + amplitude_consistency) / 3.0, 6)


@dataclass
class _TreeNode:
    value: float | None = None
    feature: int | None = None
    threshold: float | None = None
    left: "_TreeNode | None" = None
    right: "_TreeNode | None" = None


class _RandomForestLite:
    """Small deterministic regression forest using only the standard library."""

    def __init__(self, trees: int = 18, depth: int = 4, seed: int = 2026):
        self.tree_count = trees
        self.max_depth = depth
        self.seed = seed
        self.forest: list[_TreeNode] = []
        self.feature_importance: list[float] = []

    @staticmethod
    def _mse(values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / len(values)

    def fit(self, rows: list[list[float]], targets: list[float]) -> None:
        rng = random.Random(self.seed)
        self.feature_importance = [0.0] * len(rows[0])
        self.forest = []
        for _ in range(self.tree_count):
            sample_indices = [rng.randrange(len(rows)) for _ in rows]
            self.forest.append(self._build(rows, targets, sample_indices, 0, rng))
        total = sum(self.feature_importance) or 1.0
        self.feature_importance = [round(value / total, 4) for value in self.feature_importance]

    def _build(self, rows, targets, indices, depth, rng) -> _TreeNode:
        values = [targets[index] for index in indices]
        if depth >= self.max_depth or len(indices) < 6 or self._mse(values) < 0.0005:
            return _TreeNode(value=sum(values) / len(values))

        feature_count = len(rows[0])
        candidates = list(range(feature_count))
        rng.shuffle(candidates)
        candidates = candidates[:max(2, int(math.sqrt(feature_count)))]
        best = None
        parent_error = self._mse(values) * len(indices)
        for feature in candidates:
            unique = sorted({rows[index][feature] for index in indices})
            if len(unique) < 2:
                continue
            for position in range(1, len(unique)):
                threshold = (unique[position - 1] + unique[position]) / 2
                left = [index for index in indices if rows[index][feature] <= threshold]
                right = [index for index in indices if rows[index][feature] > threshold]
                if not left or not right:
                    continue
                error = self._mse([targets[index] for index in left]) * len(left)
                error += self._mse([targets[index] for index in right]) * len(right)
                gain = parent_error - error
                if best is None or gain > best[0]:
                    best = (gain, feature, threshold, left, right)
        if best is None or best[0] <= 0:
            return _TreeNode(value=sum(values) / len(values))
        _, feature, threshold, left, right = best
        self.feature_importance[feature] += best[0]
        return _TreeNode(
            feature=feature,
            threshold=threshold,
            left=self._build(rows, targets, left, depth + 1, rng),
            right=self._build(rows, targets, right, depth + 1, rng),
        )

    def _predict_tree(self, node: _TreeNode, row: list[float]) -> float:
        if node.value is not None:
            return node.value
        child = node.left if row[node.feature] <= node.threshold else node.right
        return self._predict_tree(child, row)

    def predict(self, row: list[float]) -> float:
        return sum(self._predict_tree(tree, row) for tree in self.forest) / len(self.forest)


class HotspotPredictor:
    """Synthetic-data Random Forest predictor for a runnable prototype."""

    model_name = "random-forest-lite-synthetic-v1"

    def __init__(self):
        self.model = _RandomForestLite()
        self._train_synthetic()

    @staticmethod
    def _target(hour: int, weekday: int, grid: int, history: int, weather: float, event: float) -> float:
        night = 0.80 if hour >= 19 or hour <= 4 else 0.15
        weekend = 0.15 if weekday >= 5 else 0.0
        zone = (4 - grid) * 0.10
        history_signal = min(history / 12.0, 1.0) * 0.25
        return max(0.0, min(1.0, 0.05 + night + weekend + zone + history_signal + weather * 0.12 + event * 0.18))

    def _train_synthetic(self) -> None:
        rng = random.Random(2026)
        rows = []
        targets = []
        for _ in range(360):
            hour = rng.randrange(24)
            weekday = rng.randrange(7)
            grid = rng.randrange(5)
            history = rng.randrange(16)
            weather = rng.random()
            event = rng.random() if rng.random() < 0.25 else 0.0
            rows.append([hour / 23, weekday / 6, grid / 4, history / 15, weather, event])
            targets.append(self._target(hour, weekday, grid, history, weather, event) + rng.uniform(-0.025, 0.025))
        self.model.fit(rows, targets)

    def predict(self, *, hour: int, weekday: int, grid: int, history_count: int = 0, weather_risk: float = 0.0, event_factor: float = 0.0) -> dict[str, Any]:
        row = [hour / 23, weekday / 6, grid / 4, _clamp(history_count / 15), _clamp(weather_risk), _clamp(event_factor)]
        score = round(max(0.0, min(1.0, self.model.predict(row))) * 100, 1)
        level = "Low" if score < 40 else "Medium" if score < 70 else "High"
        return {
            "risk_score": score,
            "risk_level": level,
            "model": self.model_name,
            "features": dict(zip(HOTSPOT_FEATURES, row)),
        }

    def feature_importance(self) -> dict[str, float]:
        return dict(zip(HOTSPOT_FEATURES, self.model.feature_importance))
