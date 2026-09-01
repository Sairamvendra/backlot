import world_builder as wb

BASE_CFG = {"style": "LOWPOLY", "detail": "QUICK", "extra": "", "passes": 0,
            "render_dir": "/tmp", "slug": "x", "project_dir": "/tmp",
            "exec_helper": "/tmp/wb_exec.py", "duration": 5.0, "fps": 24}


def test_build_system_picks_flow_by_mode():
    assert wb.FLOW_REPLACE in wb.build_system({**BASE_CFG, "mode": "REPLACE"})
    assert wb.FLOW_ADD in wb.build_system({**BASE_CFG, "mode": "ADD"})
    assert wb.FLOW_REMASTER in wb.build_system({**BASE_CFG, "mode": "REMASTER"})
    assert wb.FLOW_REPLACE in wb.build_system(BASE_CFG)  # missing mode falls back to replace


def test_claude_prompt_remaster_flow_and_scene_shot():
    cfg = {**BASE_CFG, "mode": "REMASTER", "scene_shot": "/tmp/before.jpg"}
    out = wb.claude_prompt("upgrade the temple", cfg)
    assert "REMASTER the existing scene" in out
    assert "CURRENT SCENE RENDER: /tmp/before.jpg" in out
    assert "CURRENT SCENE RENDER" not in wb.claude_prompt("a village", {**BASE_CFG, "mode": "REPLACE"})


def test_director_task_notes_by_mode():
    assert "REMASTERS an existing scene" in wb.director_task("t", {**BASE_CFG, "mode": "REMASTER"}, "scene")
    assert "ADDS to an existing scene" in wb.director_task("t", {**BASE_CFG, "mode": "ADD"}, "scene")
    plain = wb.director_task("t", {**BASE_CFG, "mode": "REPLACE"}, "scene")
    assert "REMASTERS" not in plain and "ADDS" not in plain
