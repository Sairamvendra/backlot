import json
import world_builder as wb


def test_tools_list_gated_by_cfg():
    assert wb.build_tools({"assets": False}) == wb.TOOLS
    withassets = wb.build_tools({"assets": True})
    assert len(withassets) == len(wb.TOOLS) + 1
    assert withassets[-1]["function"]["name"] == "import_asset"


def test_import_asset_call_no_match(monkeypatch):
    monkeypatch.setattr(wb, "fetch_asset", lambda q, c: None)
    out = wb.import_asset_call({"query": "left-handed smoke shifter"}, {"assets": True, "style": "LOWPOLY"})
    assert "NO MATCH" in out and "primitives" in out


def test_import_asset_call_happy_path(monkeypatch):
    monkeypatch.setattr(wb, "fetch_asset", lambda q, c: {"name": "barrel", "file": "/tmp/b.glb"})
    seen = {}
    def fake_exec(code, timeout=600):
        seen["code"] = code
        return json.dumps({"status": "ok", "result": {"objects": ["Barrel"], "dimensions_m": [1, 1, 1.2]}})
    monkeypatch.setattr(wb, "exec_on_main", fake_exec)
    out = wb.import_asset_call({"query": "barrel"}, {"assets": True, "style": "LOWPOLY"})
    assert '"objects"' in out
    assert '"/tmp/b.glb"' in seen["code"] and "__PATH__" not in seen["code"]


def test_import_asset_call_soft_fails(monkeypatch):
    def boom(q, c):
        raise OSError("network down")
    monkeypatch.setattr(wb, "fetch_asset", boom)
    out = wb.import_asset_call({"query": "barrel"}, {"assets": True, "style": "LOWPOLY"})
    assert out.startswith("ERROR:") and "network down" in out
