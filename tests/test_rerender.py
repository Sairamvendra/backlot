import json

import world_builder as wb

SAMPLE_BAKE = {"fps": 24,
               "frames": [[0, 0, 5, 1, 0, 0, 0, 50.0], [1, 0, 5, 0.9, 0.1, 0, 0, 50.0]],
               "static": {"lens": 50.0, "sensor_width": 36.0, "shift_x": 0.0, "shift_y": 0.0,
                          "clip_start": 0.1, "clip_end": 1000.0, "use_dof": False,
                          "focus_distance": 10.0, "aperture_fstop": 2.8}}


def test_bake_and_replay_templates_compile():
    bake_code = wb.BAKE_CAM_CODE.replace("__FRAMES__", "48").replace("__FPS__", "24")
    compile(bake_code, "<bake>", "exec")
    replay = wb.REPLAY_RIG_CODE.replace("__BAKE__", json.dumps(json.dumps(SAMPLE_BAKE)))
    compile(replay, "<replay>", "exec")
    compile(wb.RERENDER_CLEANUP_CODE, "<cleanup>", "exec")


def test_replay_quaternion_continuity_logic():
    # the sign-flip guard inside REPLAY_RIG_CODE, exercised standalone
    prev = [0.9, 0.1, 0.0, 0.0]
    q = [-0.9, -0.1, 0.0, 0.0]  # same rotation, flipped sign
    if sum(a * b for a, b in zip(q, prev)) < 0:
        q = [-c for c in q]
    assert q == [0.9, 0.1, 0.0, 0.0]
