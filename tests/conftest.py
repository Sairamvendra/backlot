"""Fake bpy so world_builder.py imports under plain pytest (no Blender)."""
import os
import sys
import types

_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo not in sys.path:
    sys.path.insert(0, _repo)


def _make_bpy():
    bpy = types.ModuleType("bpy")
    t = types.ModuleType("bpy.types")
    for name in ("Operator", "Panel", "PropertyGroup", "AddonPreferences"):
        setattr(t, name, type(name, (), {}))
    p = types.ModuleType("bpy.props")
    for name in ("StringProperty", "EnumProperty", "BoolProperty",
                 "IntProperty", "FloatProperty", "PointerProperty"):
        setattr(p, name, lambda *a, **k: None)
    u = types.ModuleType("bpy.utils")
    u.register_class = lambda c: None
    u.unregister_class = lambda c: None
    app = types.ModuleType("bpy.app")
    app.timers = types.SimpleNamespace(register=lambda *a, **k: None)
    app.handlers = types.SimpleNamespace(render_complete=[], render_cancel=[])
    bpy.types, bpy.props, bpy.utils, bpy.app = t, p, u, app
    bpy.data = types.SimpleNamespace()
    bpy.context = types.SimpleNamespace()
    return bpy


sys.modules.setdefault("bpy", _make_bpy())
