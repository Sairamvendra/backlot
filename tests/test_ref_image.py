import base64

import world_builder as wb


def test_strip_old_images_keeps_first_user_message():
    ref_msg = {"role": "user", "content": [{"type": "text", "text": "build it"},
                                           {"type": "image_url", "image_url": {"url": "data:..."}}]}
    later = {"role": "user", "content": [{"type": "text", "text": "feedback"},
                                         {"type": "image_url", "image_url": {"url": "data:..."}}]}
    messages = [{"role": "system", "content": "sys"}, ref_msg, later]
    wb.strip_old_images(messages)
    assert isinstance(messages[1]["content"], list)      # reference image survives
    assert isinstance(messages[2]["content"], str)       # old render stripped
    assert "[earlier render omitted]" in messages[2]["content"]


def test_image_part_kind_case_insensitive(tmp_path):
    png = tmp_path / "ref.PNG"
    png.write_bytes(b"fakepng")
    part = wb.image_part(str(png))
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(part["image_url"]["url"].split(",", 1)[1]) == b"fakepng"
    jpg = tmp_path / "ref.jpg"
    jpg.write_bytes(b"fakejpg")
    assert wb.image_part(str(jpg))["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_claude_prompt_mentions_ref_image_only_when_set():
    cfg = {"add_mode": False, "style": "LOWPOLY", "detail": "QUICK", "extra": "",
           "passes": 0, "render_dir": "/tmp", "slug": "x", "project_dir": "/tmp",
           "exec_helper": "/tmp/wb_exec.py"}
    assert "REFERENCE IMAGE" not in wb.claude_prompt("a village", cfg)
    cfg["ref_image"] = "/tmp/ref.jpg"
    out = wb.claude_prompt("a village", cfg)
    assert "REFERENCE IMAGE" in out and "/tmp/ref.jpg" in out
