"""Kivo's AI voice - a free, **local** language model behind a narrow port.

By hard rule Kivo's AI is free and offline: it talks to a local
`Ollama <https://ollama.com>`_ server, never a paid/hosted API. The rest of the
system depends only on the :class:`AiClient` protocol, so the model is swappable
(a different local backend, or a fake in tests). Implemented with the standard
library only (``urllib``) - no extra dependency.

This module holds the client and :class:`AiNarrator`, the behaviour that lets the
model speak as Kivo. Generation runs on a **background thread** so it never
blocks the Brain's loop; finished lines are delivered on the loop via
:meth:`AiNarrator.on_tick`.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from .brain import (
    Action,
    Behavior,
    LightClassifier,
    PresenceEstimator,
    ProximityGate,
    ShowText,
    WorldState,
    part_of_day,
)
from .device import SensorReading

_log = logging.getLogger(__name__)

# Defaults for a local Ollama install. Overridable via Settings / env.
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"
# Generous for a warm small/medium model; a cold load of a large model can exceed
# this, in which case the caller degrades gracefully and the next reaction (model
# now resident) succeeds.
DEFAULT_TIMEOUT = 60.0
DEFAULT_KEEP_ALIVE = "10m"  # keep the model loaded between reactions
DEFAULT_NUM_PREDICT = 24  # keep replies short: fast, and it drives a tiny LCD
DEFAULT_TEMPERATURE = 0.8


class AiError(Exception):
    """The local model could not be reached or returned nothing usable."""


@runtime_checkable
class AiClient(Protocol):
    """Generate a completion for a prompt. Raises :class:`AiError` on failure."""

    def generate(self, prompt: str, *, system: str | None = None) -> str: ...


class OllamaClient:
    """:class:`AiClient` backed by a local Ollama server (``/api/generate``)."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        num_predict: int = DEFAULT_NUM_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._num_predict = num_predict
        self._temperature = temperature

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "num_predict": self._num_predict,
                "temperature": self._temperature,
            },
        }
        if system is not None:
            payload["system"] = system

        request = urllib.request.Request(
            f"{self._url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Reached Ollama, but it rejected the request. A 404 almost always
            # means the model isn't pulled - say so, with the fix.
            hint = (
                f" - is it pulled? try: ollama pull {self._model}"
                if exc.code == 404
                else ""
            )
            raise AiError(
                f"Ollama returned HTTP {exc.code} for model {self._model!r}{hint}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AiError(f"could not reach Ollama at {self._url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AiError(f"invalid response from Ollama: {exc}") from exc

        return str(body.get("response", "")).strip()


class FakeAiClient:
    """Deterministic in-memory :class:`AiClient` for tests and offline demos."""

    def __init__(self, responder=None, *, fail: bool = False) -> None:
        self._responder = responder or (lambda prompt, system: "hello")
        self._fail = fail
        self.calls: list[tuple[str, str | None]] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        if self._fail:
            raise AiError("fake failure")
        return self._responder(prompt, system)


# -- the AI narrator ---------------------------------------------------------

# Kivo's persona. The LCD scrolls long lines now, so we ask for a short but
# *complete* thought rather than a hard character count (which produced clipped
# fragments). A dozen-ish words scrolls by in a second or two.
_SYSTEM = (
    "You are Kivo, a warm and witty desk companion with a small scrolling LCD. "
    "Reply with ONE short, complete line - a few words, no more than about a "
    "dozen. No quotes, no emoji, no trailing punctuation."
)

# A safety cap only. Normal replies are far shorter; this stops a runaway response
# from scrolling forever. Trimmed at a word boundary so a word is never cut.
_MAX_CHARS = 80


def one_line(text: str, limit: int = _MAX_CHARS) -> str:
    """Flatten to a single line; trim only if absurdly long, at a word boundary."""
    text = " ".join(text.split())  # flatten newlines/extra spaces to one line
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    if " " in clipped:
        clipped = clipped[: clipped.rfind(" ")]
    return clipped.rstrip()


class AiNarrator(Behavior):
    """Kivo's AI voice: a time-aware greeting on wake, and fresh short lines when
    the light changes, someone arrives/leaves, or you lean in close.

    Generation runs off the Brain's loop (a background thread), so a trigger never
    blocks Kivo; the finished line is delivered on the next tick. Degrades to
    silence if the model is unreachable. ``background=False`` generates inline
    (tests); the line is still delivered via :meth:`on_tick`.
    """

    def __init__(
        self,
        client: AiClient,
        *,
        sensor: str = "light",
        presence_sensor: str = "presence",
        distance_sensor: str = "distance",
        row: int = 0,
        max_chars: int = _MAX_CHARS,
        dark_below: int = 300,
        bright_above: int = 700,
        margin: int = 40,
        close_below: int = 20,
        close_margin: int = 10,
        near_cm: int = 120,
        near_margin: int = 30,
        motion_grace: float = 8.0,
        emotion=None,
        memory=None,
        now: Callable[[], datetime] | None = None,
        clock: Callable[[], float] | None = None,
        background: bool = True,
    ) -> None:
        self._client = client
        self._sensor = sensor
        self._distance_sensor = distance_sensor
        self._row = row
        self._max_chars = max_chars
        self._now = now or datetime.now
        self._classifier = LightClassifier(
            dark_below=dark_below, bright_above=bright_above, margin=margin
        )
        self._gate = ProximityGate(close_below=close_below, margin=close_margin)
        self._presence = PresenceEstimator(
            distance_sensor=distance_sensor,
            motion_sensor=presence_sensor,
            near_cm=near_cm,
            margin=near_margin,
            motion_grace=motion_grace,
            now=clock,
        )
        self._emotion = emotion
        self._memory = memory
        self._last_mood: str | None = None
        self._primed = False
        self._was_present: bool | None = None
        self._was_close: bool | None = None
        self._last_emotion: str | None = None
        self._background = background
        self._requests: queue.Queue[str] = queue.Queue()
        self._results: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

    # -- Behaviour hooks ------------------------------------------------------

    def on_start(self, world: WorldState) -> list[Action]:
        clock, part = self._time_phrase()
        context = self._memory.session_context() if self._memory is not None else ""
        extra = f" What you remember: {context}." if context else ""
        self._request(
            f"It's {clock}, {part}.{extra} Greet your human with a short, fresh, "
            "unique welcome that naturally reflects any shared history - make it "
            "different every time."
        )
        return []  # the greeting arrives via on_tick once generated

    def on_sensor(self, reading: SensorReading, world: WorldState) -> list[Action]:
        if reading.name == self._sensor:
            self._on_light(reading.value)
        if reading.name == self._distance_sensor:
            self._on_distance(reading.value)  # a lean-in is a separate reaction
        if self._presence.handles(reading.name):
            self._presence.feed(reading)
            self._settle_presence()
        return []  # any resulting line arrives via on_tick

    def on_tick(self, world: WorldState) -> list[Action]:
        # Re-check presence each tick so the time-based "gone" transition fires
        # even when a still, empty room is sending no readings.
        self._settle_presence()
        self._settle_emotion()
        # Show the most recent finished line, discarding any older (stale) ones.
        line = None
        while True:
            try:
                line = self._results.get_nowait()
            except queue.Empty:
                break
        if not line:
            return []
        return [ShowText(self._row, line)]

    # -- reactions ------------------------------------------------------------

    def _on_light(self, value: int) -> None:
        mood = self._classifier.classify(value)
        if not self._primed:
            # Record the starting state silently so the wake greeting persists.
            self._primed = True
            self._last_mood = mood
            return
        if mood == self._last_mood:
            return
        self._last_mood = mood
        clock, _ = self._time_phrase()
        self._request(
            f"It's {clock}. The room just became {mood}. Say one short, fresh line "
            "about it, in character."
        )

    def _settle_presence(self) -> None:
        present = self._presence.evaluate()
        if self._was_present is None:
            self._was_present = present  # prime silently on the first evaluation
            return
        if present == self._was_present:
            return
        self._was_present = present
        clock, _ = self._time_phrase()
        if present:
            context = self._memory.visit_context() if self._memory is not None else ""
            extra = f" You recall: {context}." if context else ""
            self._request(
                f"It's {clock}. Your human just came back to the desk.{extra} Greet "
                "them warmly with one short, fresh line."
            )
        else:
            self._request(
                f"It's {clock}. Your human just left the desk. Say one short, warm "
                "goodbye line."
            )

    def _settle_emotion(self) -> None:
        if self._emotion is None:
            return
        emotion = self._emotion.current()
        if emotion == self._last_emotion:
            return
        self._last_emotion = emotion
        # Only speak up for a real, non-neutral expression appearing.
        if emotion is None or emotion == "neutral":
            return
        clock, _ = self._time_phrase()
        self._request(
            f"It's {clock}. You can see your human looks {emotion} right now. "
            "Respond to how they're feeling with one short, warm, in-character line."
        )

    def _on_distance(self, value: int) -> None:
        close = self._gate.update(value)
        if self._was_close is None:
            self._was_close = close  # prime silently
            return
        if close == self._was_close:
            return
        self._was_close = close
        if not close:
            return  # only react to the deliberate lean-in, not pulling back
        self._request(
            "Your human just leaned in close to you. React with one short, "
            "delighted line, in character."
        )

    # -- generation (off the Brain's loop) ------------------------------------

    def _request(self, prompt: str) -> None:
        """Queue a line to generate. Never blocks the Brain loop when threaded."""
        if self._background:
            self._ensure_worker()
            self._requests.put(prompt)
        else:
            self._generate(prompt)  # inline; still delivered via on_tick

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._run, name="kivo-ai", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            prompt = self._requests.get()
            # If newer requests piled up while busy, skip to the latest so we
            # never show a line about a state the room has already left.
            while True:
                try:
                    prompt = self._requests.get_nowait()
                except queue.Empty:
                    break
            self._generate(prompt)

    def _generate(self, prompt: str) -> None:
        try:
            text = self._client.generate(prompt, system=_SYSTEM)
        except AiError as exc:
            _log.warning("AI unavailable, staying quiet: %s", exc)
            return
        line = one_line(text, self._max_chars)
        if line:
            _log.info("Kivo (AI) says: %r", line)
            self._results.put(line)

    def _time_phrase(self) -> tuple[str, str]:
        now = self._now()
        clock = now.strftime("%I:%M %p").lstrip("0")  # e.g. "9:47 PM"
        return clock, part_of_day(now.hour)
