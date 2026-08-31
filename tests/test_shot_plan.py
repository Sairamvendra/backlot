import world_builder as wb

PLAN = """INTENT: sweeping reveal of the island.
SHOTS: 1. frames 1-120: EWS aerial...
PACING: slow, BEZIER easing.

```json
{"shots": [
  {"name": "Opening Wide!", "seconds": 5, "prompt": "EWS aerial push-in toward the island, 24mm"},
  {"seconds": 99, "prompt": "orbit the volcano rim, 35mm"},
  {"name": "bad", "seconds": 4, "prompt": ""}
]}
```"""


def test_parses_and_normalizes():
    shots = wb.parse_shot_plan(PLAN)
    assert len(shots) == 2  # the empty-prompt shot is dropped
    assert shots[0] == {"name": "opening-wide", "seconds": 5.0,
                        "prompt": "EWS aerial push-in toward the island, 24mm"}
    assert shots[1]["seconds"] == 20.0        # 99 clamped
    assert shots[1]["name"] == "shot-2"       # missing name -> positional slug


def test_prose_only_returns_none():
    assert wb.parse_shot_plan("INTENT: moody.\nSHOTS: 1. wide orbit.") is None
    assert wb.parse_shot_plan("```json\nnot json\n```") is None
    assert wb.parse_shot_plan("") is None
    assert wb.parse_shot_plan(None) is None


def test_caps_at_eight_shots():
    import json
    block = json.dumps({"shots": [{"name": f"s{i}", "seconds": 3, "prompt": "orbit"}
                                  for i in range(12)]})
    assert len(wb.parse_shot_plan(f"```json\n{block}\n```")) == 8


def test_film_mode_task_asks_for_json():
    cfg = {"duration": 20.0, "fps": 24, "film": True}
    text = wb.director_task("island flyby", cfg, "shot")
    assert '"shots"' in text and "MULTI-SHOT FILM" in text


def test_single_shot_task_unchanged():
    cfg = {"duration": 5.0, "fps": 24}
    text = wb.director_task("orbit", cfg, "shot")
    assert "MULTI-SHOT FILM" not in text and "frames 1-120" in text
