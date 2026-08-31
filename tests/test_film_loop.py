import world_builder as wb


def test_worker_film_survives_a_crashing_take(monkeypatch):
    """A take that raises (e.g. API 402 mid-run) is skipped; later takes and assembly still run."""
    calls = {"assembled": False}
    monkeypatch.setattr(wb, "director_brief", lambda *a: "brief")
    monkeypatch.setattr(wb, "parse_shot_plan", lambda b: [
        {"name": "a", "seconds": 3.0, "prompt": "one"},
        {"name": "b", "seconds": 3.0, "prompt": "two"}])
    monkeypatch.setattr(wb, "exec_on_main", lambda *a, **k: '{"status": "ok"}')

    def fake_shoot(task, key, scfg, brief):
        if task.endswith("one"):
            raise RuntimeError("API error 402")
        return "/tmp/b.mp4"

    monkeypatch.setattr(wb, "shoot", fake_shoot)
    monkeypatch.setattr(wb, "assemble_film", lambda cfg: calls.__setitem__("assembled", True))
    wb.state.update(cancel=False, shots=[], running=True)
    wb.worker_film("film it", "k", {"model": "GLM_FLASH", "slug": "smoke", "duration": 6.0})
    assert wb.state["shots"][0]["path"] is None
    assert wb.state["shots"][1]["path"] == "/tmp/b.mp4"
    assert calls["assembled"] is True
    assert wb.state["running"] is False
