"""Local, free webcam emotion sensing.

Kivo's kit sensors can't see your face, but the host's webcam can. This module
reads the camera on a background thread, finds a face, and classifies the facial
expression with a small **local** ONNX model (FER+), so Kivo can mirror and react
to how you look. It's free and offline by the project's hard rule - OpenCV runs
the models on the CPU; there is no paid API and nothing leaves the machine.

Face detection adapts to the installed OpenCV: the classic Haar cascade on
OpenCV 4, or the modern YuNet DNN detector on OpenCV 5 (which dropped cascades).

Everything degrades gracefully: if OpenCV isn't installed/usable, a model file is
missing, or no camera is available, :func:`build_source` returns ``None`` (with a
clear message) and Kivo runs exactly as before, just without face-driven mood.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Protocol, runtime_checkable

_log = logging.getLogger(__name__)

# FER+ output order, mapped to the short labels Kivo uses everywhere else.
_FERPLUS_LABELS = (
    "neutral", "happy", "surprise", "sad", "angry", "disgust", "fear", "contempt",
)
_NEUTRAL = "neutral"

# Emotions Kivo reacts to (contempt is folded into neutral - rare and unreliable).
EMOTIONS = ("neutral", "happy", "surprise", "sad", "angry", "disgust", "fear")

# An emotion registers only if its own softmax probability reaches this floor;
# otherwise the face reads as neutral. This is the sensitivity <-> stickiness dial:
# LOWER catches subtler emotions but is stickier and more false-positive; HIGHER
# means only clear expressions and a quick, clean return to neutral when you relax.
DEFAULT_MIN_PROB = 0.35


def classify_scores(scores, *, min_prob: float = DEFAULT_MIN_PROB) -> str:
    """Turn raw FER+ logits into an emotion label (pure, so it's unit-testable).

    Softmaxes the scores and reports the strongest *non-neutral* emotion, but only
    if its probability clears ``min_prob`` - otherwise ``neutral``. Judging an
    emotion by its own magnitude (not by beating an over-predicted "neutral") is
    what lets a relaxed face return to neutral instead of staying stuck on the
    last expression, while a clearly-held sad/angry still registers.
    """
    values = list(scores)
    if not values:
        return _NEUTRAL
    top = max(values)
    exps = [math.exp(v - top) for v in values]
    total = sum(exps) or 1.0
    probs = [e / total for e in exps]

    best_label, best_prob = _NEUTRAL, 0.0
    for i, prob in enumerate(probs):
        label = _FERPLUS_LABELS[i] if i < len(_FERPLUS_LABELS) else _NEUTRAL
        if label in (_NEUTRAL, "contempt"):
            continue  # neutral is the fallback; contempt is unreliable
        if prob > best_prob:
            best_label, best_prob = label, prob
    return best_label if best_prob >= min_prob else _NEUTRAL

EMOTION_MODEL_NAME = "emotion-ferplus-8.onnx"
FACE_MODEL_NAME = "face_detection_yunet_2023mar.onnx"  # YuNet, for OpenCV 5


class VisionError(Exception):
    """The camera / models could not be set up."""


@runtime_checkable
class EmotionSource(Protocol):
    """The latest detected emotion label, or ``None`` if no face is seen."""

    def current(self) -> str | None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class FakeEmotionSource:
    """In-memory emotion source for tests and offline demos."""

    def __init__(self, emotion: str | None = None) -> None:
        self._emotion = emotion

    def set(self, emotion: str | None) -> None:
        self._emotion = emotion

    def current(self) -> str | None:
        return self._emotion

    def start(self) -> None:  # pragma: no cover - trivial
        pass

    def stop(self) -> None:  # pragma: no cover - trivial
        pass


def _model_dir() -> Path:
    return Path(os.environ.get("KIVO_MODEL_DIR", str(Path.home() / ".kivo")))


def emotion_model_path() -> Path:
    override = os.environ.get("KIVO_EMOTION_MODEL")
    return Path(override) if override else _model_dir() / EMOTION_MODEL_NAME


def face_model_path() -> Path:
    override = os.environ.get("KIVO_FACE_MODEL")
    return Path(override) if override else _model_dir() / FACE_MODEL_NAME


# -- face detectors: adapt to whichever OpenCV is installed -------------------


class _HaarDetector:
    """OpenCV 4 face detection via the bundled Haar cascade."""

    def __init__(self, cv2, xml_path: str) -> None:
        self._cascade = cv2.CascadeClassifier(xml_path)
        if self._cascade.empty():
            raise VisionError("could not load the OpenCV Haar face cascade")

    def detect(self, frame_bgr, gray) -> list[tuple[int, int, int, int]]:
        faces = self._cascade.detectMultiScale(gray, 1.3, 5, minSize=(80, 80))
        return [tuple(int(v) for v in f) for f in faces]


class _YuNetDetector:
    """OpenCV 5 face detection via the YuNet DNN model."""

    def __init__(self, cv2, model_path: Path) -> None:
        self._det = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), 0.7, 0.3, 5000
        )

    def detect(self, frame_bgr, gray) -> list[tuple[int, int, int, int]]:
        h, w = frame_bgr.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(frame_bgr)
        if faces is None:
            return []
        out = []
        for f in faces:
            x, y, fw, fh = int(f[0]), int(f[1]), int(f[2]), int(f[3])
            out.append((max(0, x), max(0, y), fw, fh))
        return out


def _build_detector(cv2):
    """Pick a face detector for the installed OpenCV, or raise VisionError."""
    haar_xml = ""
    if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
        haar_xml = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if hasattr(cv2, "CascadeClassifier") and haar_xml and os.path.exists(haar_xml):
        return _HaarDetector(cv2, haar_xml)
    if hasattr(cv2, "FaceDetectorYN"):
        model = face_model_path()
        if not model.exists():
            raise VisionError(
                f"face detector model not found at {model}. Your OpenCV "
                f"({getattr(cv2, '__version__', '?')}) uses YuNet - download the "
                "free 'face_detection_yunet_2023mar.onnx' from the OpenCV Zoo "
                "(opencv/opencv_zoo, face_detection_yunet) and put it there, or "
                "set KIVO_FACE_MODEL."
            )
        return _YuNetDetector(cv2, model)
    raise VisionError(
        "this OpenCV build has no usable face detector (no Haar cascade and no "
        "FaceDetectorYN)"
    )


class CameraEmotion:
    """Webcam emotion sensing via OpenCV + local ONNX models.

    Runs on a daemon thread so the Brain's loop is never blocked. Reads a frame
    every ``interval`` seconds, detects the largest face, and classifies its
    expression with FER+; the latest confident label is exposed via
    :meth:`current`. When no face has been seen for ``forget_after`` seconds the
    label clears to ``None``.
    """

    def __init__(
        self,
        *,
        camera_index: int = 0,
        interval: float = 0.4,
        min_prob: float = DEFAULT_MIN_PROB,
        smooth_window: int = 3,
        smooth_min: int = 2,
        forget_after: float = 2.0,
        model: Path | None = None,
    ) -> None:
        self._camera_index = camera_index
        self._interval = interval
        self._min_prob = min_prob
        self._smooth_min = smooth_min
        self._forget_after = forget_after
        self._model = model or emotion_model_path()
        self._recent: deque[str] = deque(maxlen=max(1, smooth_window))
        self._latest: str | None = None
        self._last_seen = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cv2 = None
        self._np = None
        self._detector = None
        self._net = None

    def start(self) -> None:
        """Load the models + camera and begin sensing. Raises :class:`VisionError`
        if OpenCV, a model, or the camera is unavailable."""
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            raise VisionError(
                "OpenCV/numpy not installed. Enable the webcam with: "
                "pip install -e .[vision]"
            ) from exc
        # cv2 can import as a shell whose native module failed to load - then the
        # DNN entry points are missing. Catch that with a clear message.
        if not hasattr(cv2, "dnn") or not hasattr(cv2.dnn, "readNetFromONNX"):
            raise VisionError(
                "OpenCV imported but its native module isn't usable (no cv2.dnn) - "
                "opencv-python likely has no working build for your Python version; "
                "run Kivo under Python 3.12/3.13 or reinstall opencv-python."
            )
        if not self._model.exists():
            raise VisionError(
                f"emotion model not found at {self._model}. Download the free FER+ "
                "model 'emotion-ferplus-8.onnx' from the ONNX Model Zoo (onnx/models, "
                "emotion_ferplus) and put it there, or set KIVO_EMOTION_MODEL."
            )
        detector = _build_detector(cv2)
        net = cv2.dnn.readNetFromONNX(str(self._model))

        self._cv2, self._np, self._detector, self._net = cv2, np, detector, net
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kivo-vision", daemon=True)
        self._thread.start()
        _log.info(
            "webcam emotion sensing started (%s face detector, %s)",
            type(detector).__name__, self._model.name,
        )

    def current(self) -> str | None:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- background worker ----------------------------------------------------

    def _run(self) -> None:
        cv2 = self._cv2
        cap = cv2.VideoCapture(self._camera_index)
        if not cap or not cap.isOpened():
            _log.warning("could not open camera %d; emotion sensing disabled",
                         self._camera_index)
            return
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if ok:
                    self._process(frame)
                if self._latest is not None and (
                    time.monotonic() - self._last_seen > self._forget_after
                ):
                    with self._lock:
                        self._latest = None
                    self._recent.clear()  # face gone: drop stale votes
                self._stop.wait(self._interval)
        finally:
            cap.release()

    def _process(self, frame) -> None:
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detect(frame, gray)
        if not faces:
            return
        # The nearest / most prominent face is the biggest one.
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        face = gray[y : y + h, x : x + w]
        if face.size == 0:
            return
        face = cv2.equalizeHist(face)  # normalise lighting so the expression shows
        blob = cv2.dnn.blobFromImage(face, 1.0, (64, 64))  # FER+ wants 64x64 gray
        self._net.setInput(blob)
        scores = self._net.forward().flatten().tolist()
        label = classify_scores(scores, min_prob=self._min_prob)
        # Vote over the last few frames so a steady subtle emotion registers and
        # single-frame flicker doesn't.
        self._recent.append(label)
        winner, votes = Counter(self._recent).most_common(1)[0]
        smoothed = winner if votes >= self._smooth_min else _NEUTRAL
        with self._lock:
            self._latest = smoothed
            self._last_seen = time.monotonic()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def build_source(*, camera_index: int = 0) -> EmotionSource | None:
    """Try to start webcam emotion sensing; return ``None`` (logging why) if it
    can't, so the caller keeps running without face-driven mood.

    Tunable (env): ``KIVO_EMOTION_MIN_PROB`` - the probability an emotion must
    reach to register. Lower = more sensitive to subtle emotions (but stickier);
    higher = only clear expressions and a faster return to neutral.
    """
    camera = CameraEmotion(
        camera_index=camera_index,
        min_prob=_env_float("KIVO_EMOTION_MIN_PROB", DEFAULT_MIN_PROB),
    )
    try:
        camera.start()
    except Exception as exc:  # optional feature: never crash the companion for it
        _log.warning("webcam mood off: %s", exc)
        print(f"note: webcam mood disabled ({exc})")
        return None
    return camera
