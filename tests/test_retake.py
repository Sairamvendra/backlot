import world_builder as wb


def test_retake_task_carries_prompt_and_note():
    shot = {"name": "crater", "prompt": "orbit the crater, 35mm", "seconds": 6, "path": None}
    t = wb.retake_task(shot, "slower, and keep the rafts in frame")
    assert "orbit the crater, 35mm" in t
    assert "RETAKE" in t and "slower, and keep the rafts in frame" in t


def test_retake_operator_registered():
    assert wb.WB_OT_retake.bl_idname == "world_builder.retake"
    assert any(c.__name__ == "WB_OT_retake" for c in wb.classes)
