"""Tests for the AI layer: the Ollama client, the narrator, and Brain wiring.

No real model is needed - a FakeAiClient stands in, and the Ollama HTTP path is
exercised with a stubbed urlopen. This keeps the suite fast and offline.
"""

import json

import pytest

from kivo.ai import AiError, AiNarrator, FakeAiClient, OllamaClient
from kivo.brain import Brain, LightMood, ShowText, WorldState
from kivo.device import DeviceClient, SensorReading
from kivo.transport import FakeTransport


# -- OllamaClient (stubbed HTTP) ---------------------------------------------


def test_ollama_builds_request_and_parses_response(monkeypatch):
    captured = {}

    class _Resp:
        def __init__(self, data): self._data = data
        def read(self): return self._data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _Resp(json.dumps({"response": "  Hi there \n"}).encode())

    monkeypatch.setattr(
        "kivo.ai.urllib.request.urlopen", fake_urlopen
    )
    out = OllamaClient(model="llama3").generate("hello", system="be brief")

    assert out == "Hi there"  # trimmed
    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["model"] == "llama3"
    assert captured["body"]["system"] == "be brief"
    assert captured["body"]["stream"] is False


def test_ollama_wraps_connection_errors_as_aierror(monkeypatch):
    import urllib.error

    def boom(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("kivo.ai.urllib.request.urlopen", boom)
    with pytest.raises(AiError):
        OllamaClient().generate("hi")


def test_ollama_404_points_at_a_missing_model(monkeypatch):
    import urllib.error

    def boom(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("kivo.ai.urllib.request.urlopen", boom)
    with pytest.raises(AiError) as info:
        OllamaClient(model="llama3.2:3b").generate("hi")
    message = str(info.value)
    assert "404" in message
    assert "llama3.2:3b" in message
    assert "ollama pull" in message


# -- AiNarrator (pure, with a fake model) ------------------------------------


# The narrator generates off the loop, so a trigger returns nothing and the line
# is delivered on the next tick. Tests use background=False so generation runs
# inline (deterministic); the delivery contract via on_tick is identical.


def test_narrator_greets_on_start():
    ai = FakeAiClient(lambda prompt, system: "Hey you")
    narrator = AiNarrator(ai, background=False)
    assert narrator.on_start(WorldState()) == []  # nothing shown synchronously
    assert narrator.on_tick(WorldState()) == [ShowText(0, "Hey you")]


def test_narrator_keeps_the_whole_line_for_the_screen_to_scroll():
    # The narrator no longer truncates: it hands the full sentence on, and the
    # Brain's marquee scrolls whatever doesn't fit. No word is dropped.
    text = "this is way too long for the screen"
    ai = FakeAiClient(lambda prompt, system: text)
    narrator = AiNarrator(ai, background=False)
    narrator.on_start(WorldState())
    (action,) = narrator.on_tick(WorldState())
    assert action.text == text


def test_narrator_flattens_whitespace_but_never_cuts_a_word():
    ai = FakeAiClient(lambda prompt, system: "  Hello   Beautiful\nDay  ")
    narrator = AiNarrator(ai, background=False)
    narrator.on_start(WorldState())
    (action,) = narrator.on_tick(WorldState())
    assert action.text == "Hello Beautiful Day"  # collapsed, complete


def test_narrator_caps_only_absurdly_long_replies_at_a_word_boundary():
    long_reply = "word " * 40  # 200 chars - pathological, far past the cap
    ai = FakeAiClient(lambda prompt, system: long_reply)
    narrator = AiNarrator(ai, background=False)
    narrator.on_start(WorldState())
    (action,) = narrator.on_tick(WorldState())
    assert len(action.text) <= 80
    assert not action.text.endswith("wor")  # never a half word


def test_narrator_primes_silently_then_speaks_on_change():
    ai = FakeAiClient(lambda prompt, system: "hmm")
    narrator = AiNarrator(ai, dark_below=300, bright_above=700, background=False)
    world = WorldState()
    primed = narrator.on_sensor(SensorReading("light", 100), world)  # dark: silent
    assert primed == []  # greeting is not clobbered by the first reading
    assert narrator.on_tick(world) == []  # nothing generated yet

    narrator.on_sensor(SensorReading("light", 950), world)  # bright: speaks
    assert narrator.on_tick(world) == [ShowText(0, "hmm")]

    narrator.on_sensor(SensorReading("light", 960), world)  # still bright
    assert narrator.on_tick(world) == []  # unchanged mood => silence


def test_narrator_stays_quiet_when_ai_unavailable():
    ai = FakeAiClient(fail=True)
    narrator = AiNarrator(ai, background=False)
    narrator.on_start(WorldState())
    assert narrator.on_tick(WorldState()) == []


def test_narrator_greeting_reflects_the_time_of_day():
    from datetime import datetime

    seen = {}

    def responder(prompt, system):
        seen["prompt"] = prompt
        return "hi"

    morning = lambda: datetime(2026, 7, 30, 8, 15)  # noqa: E731
    AiNarrator(FakeAiClient(responder), now=morning, background=False).on_start(
        WorldState()
    )
    assert "morning" in seen["prompt"]
    assert "8:15" in seen["prompt"]


def test_narrator_ignores_unrelated_sensors():
    ai = FakeAiClient()
    narrator = AiNarrator(ai, sensor="light", background=False)
    assert narrator.on_sensor(SensorReading("temp", 900), WorldState()) == []
    assert narrator.on_tick(WorldState()) == []


def test_narrator_welcomes_when_you_come_near():
    seen = {}

    def responder(prompt, system):
        seen["prompt"] = prompt
        return "Hey, welcome"

    narrator = AiNarrator(FakeAiClient(responder), near_cm=120, background=False)
    world = WorldState()
    narrator.on_sensor(SensorReading("distance", 300), world)  # prime far
    assert narrator.on_tick(world) == []
    narrator.on_sensor(SensorReading("distance", 40), world)  # come near -> welcome
    assert narrator.on_tick(world) == [ShowText(0, "Hey, welcome")]
    assert "came back" in seen["prompt"]


def test_narrator_farewells_only_when_you_are_truly_far():
    clock = [0.0]
    narrator = AiNarrator(
        FakeAiClient(lambda p, s: "Bye now"),
        near_cm=120,
        motion_grace=8.0,
        clock=lambda: clock[0],
        background=False,
    )
    world = WorldState()
    narrator.on_sensor(SensorReading("distance", 40), world)  # prime near (present)
    assert narrator.on_tick(world) == []  # still here -> silent
    narrator.on_sensor(SensorReading("distance", 300), world)  # moved away
    assert narrator.on_tick(world) == [ShowText(0, "Bye now")]


def test_narrator_speaks_to_your_facial_expression():
    from kivo.vision import FakeEmotionSource

    seen = {}

    def responder(prompt, system):
        seen["prompt"] = prompt
        return "You okay?"

    face = FakeEmotionSource(None)
    narrator = AiNarrator(FakeAiClient(responder), emotion=face, background=False)
    world = WorldState()
    assert narrator.on_tick(world) == []  # no face -> nothing to react to
    face.set("sad")
    assert narrator.on_tick(world) == [ShowText(0, "You okay?")]
    assert "sad" in seen["prompt"]
    # A steady expression doesn't repeat.
    assert narrator.on_tick(world) == []


def test_narrator_reacts_only_when_a_person_leans_in_close():
    narrator = AiNarrator(
        FakeAiClient(lambda p, s: "So close!"),
        close_below=20,
        close_margin=10,
        background=False,
    )
    world = WorldState()
    narrator.on_sensor(SensorReading("distance", 90), world)  # at the desk, not close
    assert narrator.on_tick(world) == []
    narrator.on_sensor(SensorReading("distance", 10), world)  # lean in -> speaks
    assert narrator.on_tick(world) == [ShowText(0, "So close!")]
    narrator.on_sensor(SensorReading("distance", 90), world)  # pull back -> quiet
    assert narrator.on_tick(world) == []


# -- end to end: Brain speaking through the (fake) AI -------------------------


def test_brain_with_ai_narrator_paints_the_screen():
    def responder(prompt, system):
        return "bright vibes" if "bright" in prompt else "hello there"

    transport = FakeTransport()
    with DeviceClient(transport) as client:
        brain = Brain(
            client,
            [
                AiNarrator(FakeAiClient(responder), row=0, background=False),
                LightMood(row=1),
            ],
            sensors=["light"],
        )
        brain.start()
        transport.set_sensor("light", 950)  # -> bright
        brain.step()  # reacts, then on_tick delivers the generated AI line

    assert transport.screen[0].startswith("bright vibes")
    assert "bright" in transport.screen[1]
