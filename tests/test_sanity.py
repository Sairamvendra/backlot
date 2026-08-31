import world_builder as wb


def test_module_imports_and_constants_exist():
    assert wb.RESOLUTIONS["R1080"] == (1920, 1080)
    assert wb.GLM_ID.startswith("z-ai/")
    assert callable(wb.director_system)
