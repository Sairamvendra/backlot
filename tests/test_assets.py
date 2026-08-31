import world_builder as wb

PH = {
    "CheeseBox_01": {"name": "Cheese Box 01", "tags": ["wooden", "crate", "box"],
                     "categories": ["props"]},  # tag-only distractor, listed first
    "wooden_crate_01": {"name": "Wooden Crate 01", "tags": ["wood", "box", "crate"],
                        "categories": ["props"]},
    "ArmChair_01": {"name": "Arm Chair 01", "tags": ["chair", "furniture"],
                    "categories": ["furniture", "seating"]},
}
PP = {"results": [
    {"Title": "Old Barrel", "Download": "https://static.poly.pizza/abc.glb"},
    {"Title": "No download here"},
]}


def test_ph_pick_matches_tags_and_name():
    assert wb.ph_pick(PH, "wooden crate") == "wooden_crate_01"
    assert wb.ph_pick(PH, "armchair chair") == "ArmChair_01"
    assert wb.ph_pick(PH, "spaceship") is None
    assert wb.ph_pick({}, "crate") is None


def test_pp_pick_takes_first_downloadable():
    assert wb.pp_pick(PP) == {"title": "Old Barrel", "url": "https://static.poly.pizza/abc.glb"}
    assert wb.pp_pick({"results": []}) is None
    assert wb.pp_pick({}) is None


def test_env_lookup_reads_env_file(tmp_path, monkeypatch):
    class P:  # minimal prefs stand-in
        project_dir = str(tmp_path)
        env_path = ""
        api_key = ""
        polypizza_key = ""
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=or-123\nPOLYPIZZA_API_KEY='pp-456'\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("POLYPIZZA_API_KEY", raising=False)
    assert wb.env_lookup(P(), "OPENROUTER_API_KEY") == "or-123"
    assert wb.polypizza_key(P()) == "pp-456"
    assert wb.api_key(P()) == "or-123"
