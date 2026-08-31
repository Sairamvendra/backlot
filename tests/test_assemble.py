import world_builder as wb


def test_assemble_code_is_templated_and_escaped():
    cfg = {"fps": 24, "resolution": (1920, 1080)}
    paths = ["/tmp/a's.mp4", "/tmp/b.mp4"]
    code = wb.assemble_code(paths, cfg, "/tmp/out.mp4")
    assert '"/tmp/a\'s.mp4"' in code and '"/tmp/b.mp4"' in code  # json-escaped list
    assert "1920, 1080" in code and "= 24" in code
    assert "__PATHS__" not in code and "__OUT__" not in code and "__FPS__" not in code
    assert "WB_Edit" in code and "new_movie" in code
    compile(code, "<assemble>", "exec")  # must at least be valid python
