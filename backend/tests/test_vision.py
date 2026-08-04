"""Tests for the emotion classifier's decision logic.

The camera/model path can't run here (no webcam/ONNX in CI), but the score->label
logic is pure and is where the "only happy/surprise" and the stickiness fixes live.
FER+ label order: neutral, happy, surprise, sad, angry, disgust, fear, contempt.
"""

from kivo.vision import DEFAULT_MIN_PROB, classify_scores


def _scores(**by_label):
    order = ["neutral", "happy", "surprise", "sad", "angry", "disgust", "fear", "contempt"]
    return [by_label.get(name, 0.0) for name in order]


def test_loud_expressions_win_clearly():
    assert classify_scores(_scores(happy=5.0)) == "happy"
    assert classify_scores(_scores(surprise=5.0)) == "surprise"


def test_a_clearly_held_sad_face_registers():
    # A firm sad expression (sad clearly the strongest) is detected.
    assert classify_scores(_scores(sad=3.0, neutral=1.0)) == "sad"


def test_a_relaxed_face_returns_to_neutral_not_stuck_on_an_emotion():
    # A resting face with only a faint residual smile must read neutral, not
    # stay "happy" - this is the stickiness bug.
    assert classify_scores(_scores(neutral=1.6, happy=1.0)) == "neutral"


def test_a_truly_neutral_face_is_neutral():
    assert classify_scores(_scores(neutral=3.0)) == "neutral"


def test_the_floor_trades_sensitivity_for_stickiness():
    # A subtle sad (below the default floor) reads neutral by default, but a lower
    # floor surfaces it - the documented sensitivity dial.
    subtle = _scores(neutral=2.0, sad=1.6)
    assert classify_scores(subtle) == "neutral"
    assert classify_scores(subtle, min_prob=0.25) == "sad"
    assert DEFAULT_MIN_PROB > 0.25


def test_contempt_is_treated_as_neutral():
    assert classify_scores(_scores(contempt=5.0)) == "neutral"
