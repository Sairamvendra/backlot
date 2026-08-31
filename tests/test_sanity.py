import world_builder as wb


def test_module_imports_and_constants_exist():
    assert wb.RESOLUTIONS["R1080"] == (1920, 1080)
    assert wb.GLM_ID.startswith("z-ai/")
    assert callable(wb.director_system)


def test_refactor_surface():
    for fn in ("shoot", "shot_convo", "do_clear_rig", "shot_cfg", "parse_shot_plan"):
        assert callable(getattr(wb, fn))
    for k in ("shots", "film_brief", "last_film"):
        assert k in wb.state
    assert "__MODULE__" in wb.CLEAR_RIG_CODE


def test_film_surface():
    assert callable(wb.worker_film) and callable(wb.start_film) and callable(wb.assemble_film)
    assert wb.WB_OT_film.bl_idname == "world_builder.film"
    assert any(c.__name__ == "WB_OT_film" for c in wb.classes)
