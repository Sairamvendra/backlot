# SPDX-License-Identifier: GPL-3.0-or-later
# World Builder — prompt-to-world building, refining, and filming inside Blender.
# Copyright (C) 2026 Sairam (sairamvendra)
#
# Dual-licensed: distributed under the GNU General Public License v3 or later
# (see LICENSE); commercial licenses for closed-source use are available from
# the copyright holder (see LICENSE-COMMERCIAL.md).
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for details.

bl_info = {
    "name": "World Builder",
    "author": "Sairam (sairamvendra)",
    "version": (3, 4),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > World Builder",
    "description": "Prompt an LLM (OpenRouter) to build, critique, and refine 3D worlds in the current scene",
    "category": "3D View",
}

import base64
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import bpy

DEFAULT_PROJECT_DIR = os.path.expanduser("~/Documents/WorldBuilder")


def _find_claude():
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude",
              os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude")):
        if os.path.exists(p):
            return p
    return "claude"


def get_dirs(prefs):
    """(project_root, renders_dir, worlds_dir) from preferences; main thread only."""
    root = os.path.expanduser(prefs.project_dir).rstrip("/") if prefs.project_dir.strip() else DEFAULT_PROJECT_DIR
    return root, os.path.join(root, "renders"), os.path.join(root, "worlds")


# Standalone socket helper written into the project folder for the Claude Code backend to use.
EXEC_HELPER_SRC = '''#!/usr/bin/env python3
"""Pipe Python to the open Blender via its MCP socket (localhost:9876).

Usage:  python3 wb_exec.py script.py     |     echo 'import bpy; result={...}' | python3 wb_exec.py
The code runs on Blender's main thread and must set `result` to a dict.
"""
import json, os, socket, sys
code = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
s = socket.create_connection((os.environ.get("BLENDER_HOST", "localhost"),
                              int(os.environ.get("BLENDER_PORT", "9876"))), timeout=600)
s.sendall(json.dumps({"type": "execute", "code": code, "strict_json": False}).encode() + b"\\0")
buf = b""
while not buf.endswith(b"\\0"):
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk
resp = json.loads(buf.rstrip(b"\\0"))
print(json.dumps(resp, indent=2))
sys.exit(0 if resp.get("status") in (None, "ok") else 1)
'''


def ensure_exec_helper(project_root):
    """Write the socket helper into the project folder (main thread only). Returns its path."""
    path = os.path.join(project_root, "wb_exec.py")
    try:
        os.makedirs(project_root, exist_ok=True)
        if not os.path.exists(path) or open(path).read() != EXEC_HELPER_SRC:
            with open(path, "w") as f:
                f.write(EXEC_HELPER_SRC)
    except OSError:
        pass
    return path

GLM_ID = "z-ai/glm-5.3-flash"  # revealed identity of stealth/ox-alpha
PRICING = {GLM_ID: (0.075e-6, 0.25e-6)}  # $/token (prompt, completion)
MAX_TURNS = {"QUICK": 20, "STANDARD": 40, "DETAILED": 60}
CLAUDE_TURNS = {"QUICK": 25, "STANDARD": 50, "DETAILED": 80}

# ---------------------------------------------------------------- prompts

SCENE_RULES = """- ALWAYS set `result` to a small JSON-serializable dict: what you created (names, counts, rough positions).
- Prefer bpy.data over bpy.ops where practical; ops that need UI context fail here.
- Put each group in its own collection. Ground is at z=0; use sensible real-world scale (a house is 4-6m).
- Vary duplicated objects (rotation, scale, position jitter) so nothing looks copy-pasted, and place
  objects so they don't intersect each other or float above the ground.
- Lighting: one sun (or moon/fill lights) matched to the requested mood, plus a fitting world background color.
- Camera: name it 'Camera', set scene.camera, frame the WHOLE scene from a pleasing 3/4 elevated angle.
- If you get a traceback back, fix that step and re-run it before moving on.

Structure everything so the user can easily move and edit individual objects afterwards:
- Every compound object (a tree, house, bench, well, cart...) gets a root EMPTY named for it
  ('Tree_1', 'House_3'...) placed at its base. Parent all its part meshes to that empty and name the
  parts '<Root>_<part>' ('Tree_1_Leaves', 'Tree_1_Trunk', 'House_3_Roof'...).
- Parent with: part.parent = root; part.matrix_parent_inverse = root.matrix_world.inverted()
  (otherwise parts jump). Moving the root empty must move the whole object.
- Keep logical parts as SEPARATE meshes — never join a compound object into one mesh.
- Simple single-mesh props need no empty; just name them clearly."""

BASE_RULES = ("""You are a 3D artist building a world in a live Blender session via the run_blender tool.

Rules for every call:
- bpy is available; code runs on Blender's main thread. Keep each call under ~80 lines.
""" + SCENE_RULES + """

When the world is complete reply with plain text only: DONE: <one-line summary>. No tool call.""")

FLOW_REPLACE = """
Build incrementally, one logical group per call:
1. clear the default scene, then ground/terrain
2+. structures and props, one group per call (all buildings, then all trees, then props...)
then lighting, then camera last."""

FLOW_ADD = """
Do NOT clear or delete anything that already exists. First call: inspect the existing scene
(object names, bounding boxes, collections) and set `result` to that summary. Then add the new
content in free space, matching the existing scale, style, and lighting. Camera: only adjust it
if the new content is not visible."""

STYLES = {
    "LOWPOLY": "Style: clean low-poly. Principled BSDF materials with distinct flat base colors; no image textures.",
    "STYLIZED": "Style: stylized and playful — chunky exaggerated proportions, saturated colors, soft toon-like lighting; no image textures.",
    "REALISTIC": "Style: believable proportions and materials — vary roughness/metallic, use bevels and light subdivision where cheap, muted natural palette; no image textures.",
    "CUSTOM": "",
}

DETAILS = {
    "QUICK": "Scope: quick sketch — aim for 4-6 tool calls total, essential forms only.",
    "STANDARD": "Scope: standard — aim for 6-12 tool calls total.",
    "DETAILED": "Scope: detailed — aim for 12-20 tool calls: more object variety, small props, subtle per-object color variation.",
}

CRITIQUE_MSG = """Here is a render of the current scene. Compare it against the original request and requirements.
Identify the top issues — camera framing/composition, color and contrast, lighting mood, object spacing
(overlaps, floating objects), missing or malformed elements — and FIX them now with run_blender calls.
Then reply DONE: <summary> again."""

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_blender",
        "description": "Execute Python in the running Blender. The code MUST set `result` to a JSON-serializable dict.",
        "parameters": {
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "One-line description of this build step"},
                "code": {"type": "string", "description": "Python code using bpy"},
            },
            "required": ["step", "code"],
        },
    },
}]

CAMERA_FALLBACK = """
import bpy
from mathutils import Vector
scene = bpy.context.scene
if scene.camera is None:
    pts = [o.matrix_world @ Vector(c) for o in scene.objects if o.type == 'MESH' for c in o.bound_box] or [Vector()]
    lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    center, size = (lo + hi) / 2, max((hi - lo).length, 10)
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    scene.collection.objects.link(cam)
    cam.location = center + Vector((0.9, -0.9, 0.6)) * size
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
"""

CRITIQUE_RENDER = CAMERA_FALLBACK + """
import os
os.makedirs(__DIR__, exist_ok=True)
scene.render.resolution_x, scene.render.resolution_y = __W__, __H__
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = 'IMAGE'
scene.render.image_settings.file_format = 'JPEG'
scene.render.image_settings.quality = 85
scene.render.filepath = os.path.join(__DIR__, __NAME__)
bpy.ops.render.render(write_still=True)
result = {"render": scene.render.filepath}
"""

FINAL_RENDER = CAMERA_FALLBACK + """
import os
os.makedirs(__DIR__, exist_ok=True)
scene.render.resolution_x, scene.render.resolution_y = __W__, __H__
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = 'IMAGE'
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = os.path.join(__DIR__, __NAME__)
try:
    with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
except Exception:
    bpy.ops.render.render(write_still=True)
result = {"render": scene.render.filepath}
"""

VERIFY_ANIM = """
import bpy
scene = bpy.context.scene
cam = scene.camera
def kf(o):
    ad = getattr(o, "animation_data", None)
    if not (ad and ad.action):
        return False
    act = ad.action
    if hasattr(act, "fcurves"):  # Blender <= 4.x legacy API
        return bool(len(act.fcurves))
    try:  # Blender 5.x layered actions
        return any(len(cb.fcurves) for layer in act.layers
                   for strip in layer.strips for cb in strip.channelbags)
    except AttributeError:
        return True  # has an action at all — assume animated
markers_cam = sum(1 for m in scene.timeline_markers if m.camera)
cam_anim = bool(cam and (kf(cam) or kf(cam.data)
                or any(c.type in ('FOLLOW_PATH', 'TRACK_TO') for c in cam.constraints)
                or (cam.parent and kf(cam.parent)))) or markers_cam >= 2
result = {"camera": bool(cam), "camera_animated": cam_anim, "camera_markers": markers_cam,
          "any_animated": sum(1 for o in scene.objects if kf(o)), "frame_end": scene.frame_end}
"""

STILLS_CODE = """
import bpy, os
scene = bpy.context.scene
os.makedirs(__DIR__, exist_ok=True)
scene.render.resolution_x, scene.render.resolution_y = __W__, __H__
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = 'IMAGE'
scene.render.image_settings.file_format = 'JPEG'
scene.render.image_settings.quality = 85
paths = []
for tag, fr in (("start", scene.frame_start), ("mid", (scene.frame_start + scene.frame_end) // 2), ("end", scene.frame_end)):
    scene.frame_set(fr)
    p = os.path.join(__DIR__, __SLUG__ + "-anim-" + tag + ".jpg")
    scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    paths.append(p)
scene.frame_set(scene.frame_start)
result = {"stills": paths}
"""

RECORD_CODE = """
import bpy, os, sys
wb = sys.modules[__MODULE__]
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = __FRAMES__
scene.frame_current = 1
scene.render.fps = __FPS__
scene.render.resolution_x, scene.render.resolution_y = __W__, __H__
os.makedirs(os.path.dirname(__PATH__), exist_ok=True)
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = 'VIDEO'  # Blender 5.x
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'HIGH'
scene.render.filepath = __PATH__
for handlers, fn in ((bpy.app.handlers.render_complete, wb._on_render_complete),
                     (bpy.app.handlers.render_cancel, wb._on_render_cancel)):
    if fn not in handlers:
        handlers.append(fn)
try:
    with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
        bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
    result = {"recording": "modal", "frames": __FRAMES__}
except Exception:
    bpy.ops.render.render(animation=True)
    wb.state["record_done"] = True
    result = {"recording": "blocking-done", "frames": __FRAMES__}
"""

OPENGL_RECORD_CODE = """
import bpy, os, sys
wb = sys.modules[__MODULE__]
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = __FRAMES__
scene.frame_current = 1
scene.render.fps = __FPS__
scene.render.resolution_x, scene.render.resolution_y = __W__, __H__
os.makedirs(os.path.dirname(__PATH__), exist_ok=True)
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = 'VIDEO'
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'HIGH'
scene.render.filepath = __PATH__
win = bpy.context.window_manager.windows[0]
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
space = area.spaces.active
space.region_3d.view_perspective = 'CAMERA'
overlays = space.overlay.show_overlays
space.overlay.show_overlays = False
try:
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.render.opengl(animation=True, view_context=True)
finally:
    space.overlay.show_overlays = overlays
wb.state["record_done"] = True
result = {"recording": "viewport-done", "frames": __FRAMES__}
"""

# A replace-mode build clears objects but leaves old collections as empty husks; sweep them.
PURGE_COLLECTIONS = """
import bpy
removed = []
def is_empty(col):
    return not col.objects and all(is_empty(c) for c in col.children)
changed = True
while changed:
    changed = False
    for col in list(bpy.data.collections):
        if is_empty(col):
            removed.append(col.name)
            bpy.data.collections.remove(col)
            changed = True
result = {"removed_empty_collections": removed}
"""

SHOT_CRITIQUE_MSG = """Here are renders of the shot's start, middle, and end frames. Check: is the subject
visible and well composed in ALL three? Does the camera clip into geometry? Does the motion actually cover
what was requested? Fix any issues by editing the keyframes via run_blender, then reply DONE again."""


def shot_motion_extras(cfg):
    parts = []
    if cfg.get("multicut"):
        n = str(cfg["multicut_n"]) if cfg.get("multicut_n") else "a number you judge fits the duration (2-6 typical)"
        parts.append(
            f"MULTI-CUT: structure the shot as {n} distinct cuts — hard transitions where the view jumps to a "
            "new position/angle/shot-size (vary wide/medium/close), not one continuous drift. Implement cuts "
            "with CONSTANT-interpolation camera keyframes at the cut frames, or with camera-bound markers.")
    if cfg.get("multicam"):
        n = str(cfg["multicam_n"]) if cfg.get("multicam_n") else "a number you judge fits (2-4 typical)"
        parts.append(
            f"MULTI-CAM (required): you MUST create {n} separate NEW cameras with clearly different angles "
            "and focal lengths, and bind timeline markers so the active camera actually switches during the "
            "shot: m = scene.timeline_markers.new('F<frame>', frame=<frame>); m.camera = <cam>. Bind a marker "
            "at frame 1 too. Do NOT implement this with a single camera — a single-camera result is wrong. "
            "If multi-cut is also requested, each cut switches to a different camera via its marker.")
    return parts


def glm_shot_system(cfg):
    frames = max(int(cfg["duration"] * cfg["fps"]), 1)
    extras = "".join("\n\n" + p for p in shot_motion_extras(cfg))
    return f"""You are a cinematographer programming a camera shot in an EXISTING live Blender scene via the run_blender tool.

First call: inspect the scene (object names, rough bounding boxes, current camera) and set `result` to that
summary. Do NOT delete or rebuild the scene content.

Then program the requested motion: set scene.frame_start = 1 and scene.frame_end = {frames}
({cfg['duration']}s at {cfg['fps']} fps) and keyframe the camera:
- Use the existing scene camera, or create 'ShotCam' and set scene.camera.
- Pick the right technique: location/rotation keyframes with BEZIER easing; a TRACK_TO constraint aimed at
  the subject (or an animated empty) for tracking shots; FOLLOW_PATH on a circle/curve for orbits and
  dollies (animate the constraint's offset_factor with use_fixed_location=True).
- Keep the subject well framed for the WHOLE shot and never clip through geometry.
- Animate scene objects too if the motion request asks for it (spinning, opening, floating).
- bpy is available; every call MUST set `result` to a small JSON-serializable dict; tracebacks come back —
  fix and re-run.{extras}

When the animation is fully programmed reply with plain text only: DONE: <one-line summary>.
Do NOT render the video — the addon records it."""


# ------------------------------------------------- shared state & bridge

state = {"running": False, "cancel": False, "status": "idle", "log": [],
         "messages": [], "can_refine": False, "last_render": None,
         "usage": {"prompt": 0, "completion": 0}, "cost": 0.0, "started": 0.0,
         "proc": None, "claude_session": None, "built_with": None,
         "recording": False, "record_done": False}
code_q = queue.Queue()  # worker thread -> main thread: (code, reply_queue)


def log(line):
    state["log"] = (state["log"] + [line])[-60:]


def api_key(prefs):
    if prefs.api_key:
        return prefs.api_key
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env_file = (os.path.expanduser(prefs.env_path) if prefs.env_path.strip()
                else os.path.join(get_dirs(prefs)[0], ".env"))
    try:
        for line in open(env_file):
            if line.strip().startswith("OPENROUTER_API_KEY"):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def build_system(cfg):
    parts = [BASE_RULES, FLOW_ADD if cfg["add_mode"] else FLOW_REPLACE,
             STYLES[cfg["style"]], DETAILS[cfg["detail"]]]
    if cfg["extra"].strip():
        parts.append("Additional user requirements (high priority): " + cfg["extra"].strip())
    return "\n".join(p for p in parts if p)


def chat(messages, key, cfg):
    """Backend dispatch — add new backends (e.g. Claude Code) as branches on cfg['model']."""
    model_id = cfg["custom_model"].strip() if cfg["model"] == "CUSTOM" else GLM_ID
    reasoning = {"enabled": False} if cfg["reasoning"] == "OFF" else {"effort": cfg["reasoning"].lower()}
    body = json.dumps({"model": model_id, "messages": messages, "tools": TOOLS,
                       "reasoning": reasoning}).encode()
    for attempt in range(3):
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.loads(r.read())
            usage = data.get("usage") or {}
            state["usage"]["prompt"] += usage.get("prompt_tokens", 0)
            state["usage"]["completion"] += usage.get("completion_tokens", 0)
            price = PRICING.get(model_id)
            if price:
                state["cost"] += usage.get("prompt_tokens", 0) * price[0] + usage.get("completion_tokens", 0) * price[1]
            return data["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code != 429 and e.code < 500:
                raise RuntimeError(f"API error {e.code}: {detail}")
            err = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = str(e)
        if state["cancel"] or attempt == 2:
            raise RuntimeError(err)
        log(f"retrying: {err[:70]}")
        time.sleep(5 * (attempt + 1))


def exec_on_main(code, timeout=600):
    """Worker thread: hand code to the main thread, block until its JSON result returns."""
    reply = queue.Queue(1)
    code_q.put((code, reply))
    return reply.get(timeout=timeout)


def _on_render_complete(scene, _=None):
    state["record_done"] = True


def _on_render_cancel(scene, _=None):
    state["record_done"] = "cancelled"


def run_code(code):
    """Main thread only: exec model code with bpy, capture result/stdout/traceback."""
    ns = {"bpy": bpy}
    out = StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(out):
            exec(compile(code, "<world_builder>", "exec"), ns)
        resp = {"status": "ok", "result": ns.get("result")}
    except Exception:
        resp = {"status": "error", "traceback": traceback.format_exc()}
    if out.getvalue():
        resp["stdout"] = out.getvalue()[-2000:]
    try:
        return json.dumps(resp)
    except (TypeError, ValueError):
        resp["result"] = repr(resp.get("result"))[:2000]
        return json.dumps(resp)


def pump():
    """Timer on the main thread: execute queued code, keep the UI redrawing."""
    try:
        code, reply = code_q.get_nowait()
    except queue.Empty:
        pass
    else:
        reply.put(run_code(code))
    if state.get("recording"):
        try:
            sc = bpy.context.scene
            state["status"] = f"recording frame {sc.frame_current}/{sc.frame_end}"
        except Exception:
            pass
    try:
        for window in bpy.data.window_managers[0].windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass
    if not state["running"] and code_q.empty():
        return None
    return 0.2


# ------------------------------------------------------------ the loop

def strip_old_images(messages):
    """Keep only the newest render in context — old ones just bloat the payload."""
    for m in messages:
        if isinstance(m.get("content"), list):
            texts = [p.get("text", "") for p in m["content"] if p.get("type") == "text"]
            m["content"] = "\n".join(texts) + "\n[earlier render omitted]"


def image_part(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    kind = "png" if path.endswith(".png") else "jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:image/{kind};base64,{b64}"}}


def render_to(template, cfg, suffix, half=False):
    w, h = cfg["resolution"]
    if half:
        w, h = w // 2, h // 2
    name = f"{cfg['slug']}-{suffix}-{int(time.time())}." + ("png" if template is FINAL_RENDER else "jpg")
    code = (template.replace("__DIR__", json.dumps(cfg["render_dir"])).replace("__NAME__", json.dumps(name))
            .replace("__W__", str(w)).replace("__H__", str(h)))
    resp = json.loads(exec_on_main(code))
    return resp.get("result", {}).get("render") if resp.get("status") == "ok" else None


def handle_tool_calls(msg, messages):
    """Execute one assistant message's run_blender calls, appending tool results (both GLM loops)."""
    for call in msg["tool_calls"]:
        if state["cancel"]:
            break
        try:
            args = json.loads(call["function"]["arguments"])
            step = args.get("step", "build step")
            state["status"] = step
            log("> " + step)
            result = exec_on_main(args["code"])
        except (ValueError, KeyError) as e:
            result = f"ERROR: bad tool arguments: {e}"
        except queue.Empty:
            result = "ERROR: execution timed out"
        log("    ok" if '"status": "ok"' in result else "    error -> sent back to fix")
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result[:8000]})


def render_stills(cfg):
    """Worker thread: render start/mid/end half-res stills; returns list of paths or None."""
    w, h = cfg["resolution"][0] // 2, cfg["resolution"][1] // 2
    code = (STILLS_CODE.replace("__DIR__", json.dumps(cfg["render_dir"]))
            .replace("__SLUG__", json.dumps(cfg["slug"]))
            .replace("__W__", str(w)).replace("__H__", str(h)))
    try:
        resp = json.loads(exec_on_main(code, timeout=900))
    except queue.Empty:
        return None
    return (resp.get("result") or {}).get("stills") if resp.get("status") == "ok" else None


def verify_anim():
    """Worker thread: check the scene actually has camera/object animation; logs verifier errors."""
    try:
        resp = json.loads(exec_on_main(VERIFY_ANIM))
    except queue.Empty:
        return {}
    if resp.get("status") != "ok":
        log("verify error: " + str(resp.get("traceback", ""))[-80:])
    return resp.get("result") or {}


def record_shot(cfg):
    """Worker thread: verify animation exists, then record the frame range to MP4."""
    verify = verify_anim()
    if not (verify.get("camera_animated") or verify.get("any_animated")):
        log("no animation found — nothing to record")
        return None
    w, h = cfg["resolution"]
    frames = max(int(cfg["duration"] * cfg["fps"]), 1)
    name = f"{cfg['slug']}-shot-{int(time.time())}.mp4"
    path = os.path.join(cfg["render_dir"], name)
    template = RECORD_CODE if cfg.get("final_quality") else OPENGL_RECORD_CODE
    code = (template.replace("__W__", str(w)).replace("__H__", str(h))
            .replace("__FPS__", str(cfg["fps"])).replace("__FRAMES__", str(frames))
            .replace("__PATH__", json.dumps(path)).replace("__MODULE__", json.dumps(__name__)))
    state["record_done"] = False
    state["recording"] = True
    budget = frames * 20 + 300
    try:
        resp = json.loads(exec_on_main(code, timeout=budget))
        if resp.get("status") != "ok":
            log("record error: " + str(resp.get("traceback", ""))[-90:])
            return None
        deadline = time.time() + budget
        while not state["record_done"] and time.time() < deadline:
            if state["cancel"]:
                log("cancel requested — press ESC in the render window to stop the recording")
                break
            time.sleep(2)
    finally:
        state["recording"] = False
    if state["record_done"] is True and os.path.exists(path):
        log("shot saved: renders/" + name)
        return path
    if state["record_done"] == "cancelled":
        log("recording cancelled in the render window")
    return None


def worker_shot(task_text, key, cfg, resume=False):
    """OpenRouter backend, shot mode: fresh conversation that animates the CURRENT scene, then records."""
    try:
        state["started"] = time.time()
        messages = [{"role": "system", "content": glm_shot_system(cfg)},
                    {"role": "user", "content": task_text}]
        passes_left = cfg["passes"]
        nudges = anim_retries = 0
        for turn in range(1, 31):
            if state["cancel"]:
                log("cancelled")
                break
            state["status"] = f"thinking (turn {turn})..."
            raw = chat(messages, key, cfg)
            msg = {"role": "assistant", "content": raw.get("content")}
            if raw.get("tool_calls"):
                msg["tool_calls"] = raw["tool_calls"]
            messages.append(msg)
            content = (raw.get("content") or "").strip()
            if msg.get("tool_calls"):
                handle_tool_calls(msg, messages)
                continue
            if content.upper().startswith("DONE"):
                log(content[:120])
                verify = verify_anim()
                if not (verify.get("camera_animated") or verify.get("any_animated")):
                    anim_retries += 1
                    if anim_retries > 2:
                        log("still no keyframes after retries; stopping")
                        break
                    messages.append({"role": "user", "content":
                                     "Verification found no keyframes or animated camera constraints — the "
                                     "animation is missing. Add it, then reply DONE again."})
                    continue
                if passes_left > 0 and not state["cancel"]:
                    passes_left -= 1
                    state["status"] = "rendering check frames..."
                    stills = render_stills(cfg)
                    if stills:
                        log(f"* shot critique pass ({cfg['passes'] - passes_left}/{cfg['passes']})")
                        strip_old_images(messages)
                        messages.append({"role": "user", "content":
                                         [{"type": "text", "text": SHOT_CRITIQUE_MSG}]
                                         + [image_part(p) for p in stills]})
                        nudges = 0
                        continue
                break
            if content:
                log(content[:120])
            nudges += 1
            if nudges > 2:
                log("model stopped without DONE")
                break
            messages.append({"role": "user", "content":
                             "Continue with run_blender, or reply DONE: <summary> if finished."})
        if not state["cancel"]:
            record_shot(cfg)
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["running"] = False


def worker(task_text, key, cfg, resume=False):
    try:
        state["started"] = time.time()
        if resume:
            messages = state["messages"]
            strip_old_images(messages)
            content = [{"type": "text", "text":
                        f"User feedback on the current world: {task_text}\n"
                        "Modify the existing scene accordingly — do NOT clear or rebuild from scratch "
                        "unless the feedback asks for it. When finished reply DONE: <summary>."}]
            if state["last_render"] and os.path.exists(state["last_render"]):
                content.append(image_part(state["last_render"]))
            messages.append({"role": "user", "content": content})
        else:
            messages = [{"role": "system", "content": build_system(cfg)},
                        {"role": "user", "content": task_text}]
        passes_left = cfg["passes"]
        nudges = 0
        for turn in range(1, MAX_TURNS[cfg["detail"]] + 1):
            if state["cancel"]:
                log("cancelled")
                break
            state["status"] = f"thinking (turn {turn})..."
            raw = chat(messages, key, cfg)
            msg = {"role": "assistant", "content": raw.get("content")}
            if raw.get("tool_calls"):
                msg["tool_calls"] = raw["tool_calls"]
            messages.append(msg)
            content = (raw.get("content") or "").strip()
            if msg.get("tool_calls"):
                handle_tool_calls(msg, messages)
                continue
            if content.upper().startswith("DONE"):
                log(content[:120])
                if passes_left > 0 and not state["cancel"]:
                    passes_left -= 1
                    state["status"] = "rendering for critique..."
                    path = render_to(CRITIQUE_RENDER, cfg, "critique", half=True)
                    if path:
                        log(f"* critique pass ({cfg['passes'] - passes_left}/{cfg['passes']})")
                        strip_old_images(messages)
                        messages.append({"role": "user",
                                         "content": [{"type": "text", "text": CRITIQUE_MSG}, image_part(path)]})
                        nudges = 0
                        continue
                break
            blocks = re.findall(r"```(?:python)?\n(.*?)```", content, re.S)
            if blocks:  # fallback if the model answers with a code block instead of a tool call
                log("> code block")
                result = exec_on_main(blocks[0])
                messages.append({"role": "user",
                                 "content": f"Execution result:\n{result[:8000]}\nContinue, or reply DONE: <summary>."})
                continue
            if content:
                log(content[:120])
            nudges += 1
            if nudges > 2:
                log("model stopped without DONE")
                break
            messages.append({"role": "user",
                             "content": "Continue building with run_blender, or reply DONE: <summary> if finished."})
        if not state["cancel"]:
            if not cfg["add_mode"] and not resume:
                try:
                    exec_on_main(PURGE_COLLECTIONS)
                except queue.Empty:
                    pass
            state["status"] = "final render..."
            path = render_to(FINAL_RENDER, cfg, "final")
            if path:
                state["last_render"] = path
                log("render saved: renders/" + os.path.basename(path))
        state["messages"] = messages
        state["can_refine"] = True
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["running"] = False


def claude_transport(cfg):
    helper = cfg["exec_helper"]
    return (
        "You are working with the user's ALREADY-OPEN Blender via its live socket. "
        "Never launch Blender yourself and never import bpy in your own process.\n\n"
        "Run Blender Python ONLY through this helper (the code executes inside the live Blender; "
        "stdout/stderr and tracebacks come back to you):\n"
        f"  echo '<python code>' | python3 \"{helper}\"\n"
        f"  or: write steps/step.py with your Write tool, then: python3 \"{helper}\" steps/step.py "
        "(keep helper .py files in the steps/ subfolder)")


def claude_prompt(task, cfg):
    parts = [
        claude_transport(cfg),
        "Build incrementally — one logical group per script run. Rules for the Blender code:\n" + SCENE_RULES,
        FLOW_ADD if cfg["add_mode"] else FLOW_REPLACE,
        STYLES[cfg["style"]],
        DETAILS[cfg["detail"]].replace("tool calls", "script runs"),
    ]
    if cfg["extra"].strip():
        parts.append("Additional user requirements (high priority): " + cfg["extra"].strip())
    if cfg["passes"]:
        parts.append(
            f"After building, self-review {cfg['passes']} time(s): render a 640x360 JPEG preview to "
            f"{cfg['render_dir']}/{cfg['slug']}-critique-N.jpg (via the helper: set scene.render.filepath and "
            "resolution, scene.render.image_settings.file_format='JPEG', then "
            "bpy.ops.render.render(write_still=True)), Read that image file, critique it (camera framing, "
            "lighting mood, colors, overlapping or floating objects, missing elements), and fix the issues "
            "with more Blender scripts.")
    parts.append("When satisfied, end your final message with one line: DONE: <one-line summary>.")
    parts.append("TASK — build this world: " + task)
    return "\n\n".join(parts)


def run_claude(prompt, cfg, resume_sid=None, max_turns=None):
    """Worker thread: spawn headless claude, stream events into the log. Returns (ok, session_id)."""
    cmd = [cfg["claude_bin"], "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns or CLAUDE_TURNS[cfg["detail"]]),
           "--allowedTools", "Bash(python3:*),Bash(echo:*),Read,Write,Glob,Grep"]
    if resume_sid:
        cmd += ["--resume", resume_sid]
    if cfg["claude_model"] != "DEFAULT":
        cmd += ["--model", cfg["claude_model"].lower()]
    env = {"HOME": os.path.expanduser("~"), "USER": os.environ.get("USER", ""),
           "PATH": os.path.dirname(cfg["claude_bin"]) + ":/usr/local/bin:/usr/bin:/bin"}
    errf = tempfile.NamedTemporaryFile("w+", suffix=".err", delete=False)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf,
                            cwd=cfg["project_dir"], text=True, env=env)
    state["proc"] = proc
    state["status"] = "claude code starting..."
    ok, session_id = False, resume_sid
    for line in proc.stdout:
        if state["cancel"]:
            proc.terminate()
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "system" and e.get("subtype") == "init":
            session_id = e.get("session_id")
            log(f"claude session up ({e.get('model', '?')})")
        elif t == "assistant":
            for b in (e.get("message") or {}).get("content", []):
                if b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    step = str(inp.get("description") or inp.get("command")
                               or inp.get("file_path") or b.get("name", "tool"))
                    step = step.split("\n")[0][:70]
                    state["status"] = step
                    log("> " + step)
                elif b.get("type") == "text" and (b.get("text") or "").strip():
                    log(b["text"].strip().split("\n")[0][:90])
        elif t == "result":
            ok = e.get("subtype") == "success"
            if e.get("total_cost_usd"):
                state["cost"] += e["total_cost_usd"]
            u = e.get("usage") or {}
            state["usage"]["prompt"] += u.get("input_tokens", 0)
            state["usage"]["completion"] += u.get("output_tokens", 0)
            log(str(e.get("result", ""))[:120])
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    state["proc"] = None
    errf.close()
    if not ok and not state["cancel"]:
        try:
            tail = open(errf.name).read().strip()
            if tail:
                log("stderr: " + tail[-100:])
        except OSError:
            pass
    os.unlink(errf.name)
    return ok, session_id


def worker_claude(task_text, cfg, resume):
    """Claude Code backend: headless `claude -p` drives Blender through the socket helper itself."""
    try:
        state["started"] = time.time()
        if resume:
            prompt = (f"User feedback on the world you built: {task_text}\n"
                      + (f"The current render is at {state['last_render']} — Read it first.\n"
                         if state.get("last_render") else "")
                      + "Modify the existing scene via the Blender helper (do NOT clear or rebuild from "
                        "scratch unless the feedback asks for it). End with one line: DONE: <summary>.")
        else:
            prompt = claude_prompt(task_text, cfg)
        ok, sid = run_claude(prompt, cfg, resume_sid=state.get("claude_session") if resume else None)
        if sid:
            state["claude_session"] = sid
        if not state["cancel"]:
            if not cfg["add_mode"] and not resume:
                try:
                    exec_on_main(PURGE_COLLECTIONS)
                except queue.Empty:
                    pass
            state["status"] = "final render..."
            path = render_to(FINAL_RENDER, cfg, "final")
            if path:
                state["last_render"] = path
                log("render saved: renders/" + os.path.basename(path))
        state["can_refine"] = bool(state.get("claude_session"))
        state["status"] = "cancelled" if state["cancel"] else ("done" if ok else "failed")
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def claude_shot_prompt(task, cfg):
    frames = max(int(cfg["duration"] * cfg["fps"]), 1)
    parts = [
        claude_transport(cfg),
        "An existing 3D scene is open in Blender. First run a script that inspects it (object names, rough "
        "bounds, current camera) and reports via `result`. Do NOT delete or rebuild the scene content.",
        f"Then program this camera shot: set scene.frame_start = 1 and scene.frame_end = {frames} "
        f"({cfg['duration']}s at {cfg['fps']} fps) and keyframe the camera:\n"
        "- Use the existing scene camera, or create 'ShotCam' and set scene.camera.\n"
        "- Pick the right technique: location/rotation keyframes with BEZIER easing; a TRACK_TO constraint "
        "aimed at the subject (or an animated empty) for tracking shots; FOLLOW_PATH on a circle/curve for "
        "orbits and dollies (animate the constraint's offset_factor with use_fixed_location=True).\n"
        "- Keep the subject well framed for the WHOLE shot and never clip through geometry.\n"
        "- Animate scene objects too if the motion request asks for it.\n"
        "- Every script MUST set `result` to a JSON-serializable dict.",
    ]
    parts.extend(shot_motion_extras(cfg))
    if cfg["passes"]:
        parts.append(
            f"Verify visually {cfg['passes']} time(s): render half-res JPEG stills of the start, middle, and "
            "end frames into the steps/ folder (scene.frame_set(f) then render with write_still=True), Read "
            "them, and fix framing or clipping problems with more keyframe edits.")
    parts.append("Do NOT render the video — the addon records it after you finish. "
                 "End your final message with one line: DONE: <one-line summary>.")
    parts.append("MOTION REQUEST: " + task)
    return "\n\n".join(parts)


def worker_shot_claude(task_text, cfg, resume=False):
    """Claude Code backend, shot mode: fresh session animates the CURRENT scene, then the addon records."""
    try:
        state["started"] = time.time()
        ok, _sid = run_claude(claude_shot_prompt(task_text, cfg), cfg, max_turns=40)
        if not state["cancel"]:
            record_shot(cfg)
        state["status"] = "cancelled" if state["cancel"] else ("done" if ok else "failed")
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def start_worker(context, task_text, resume):
    """Main thread: capture settings (threads must never touch bpy), then launch."""
    s = context.scene.world_builder
    prefs = context.preferences.addons[__name__].preferences
    kind = "CLAUDE_CODE" if s.model == "CLAUDE_CODE" else "OPENROUTER"
    if resume and state.get("built_with") != kind:
        return "This world was built with the other backend — switch Model back, or rebuild"
    res = {"R720": (1280, 720), "R1080": (1920, 1080), "SQUARE": (1080, 1080)}[s.resolution]
    root, render_dir, _ = get_dirs(prefs)
    cfg = {"model": s.model, "custom_model": s.custom_model, "reasoning": s.reasoning,
           "passes": s.vision_passes, "resolution": res, "style": s.style, "detail": s.detail,
           "add_mode": s.add_mode, "extra": s.extra,
           "claude_model": s.claude_model, "claude_bin": prefs.claude_path,
           "project_dir": root, "render_dir": render_dir,
           "slug": re.sub(r"[^a-z0-9]+", "-", (s.prompt or "world").lower())[:40].strip("-") or "world"}
    if kind == "CLAUDE_CODE":
        if not os.path.exists(prefs.claude_path):
            return "claude CLI not found — set its path in Add-on Preferences"
        cfg["exec_helper"] = ensure_exec_helper(root)
        target, args = worker_claude, (task_text, cfg, resume)
    else:
        key = api_key(prefs)
        if not key:
            return "No API key — set it in Add-on Preferences or the .env file"
        target, args = worker, (task_text, key, cfg, resume)
    state.update(running=True, cancel=False, log=[] if not resume else state["log"], status="starting...")
    if not resume:
        state.update(messages=[], can_refine=False, last_render=None, claude_session=None,
                     built_with=kind, usage={"prompt": 0, "completion": 0}, cost=0.0)
    threading.Thread(target=target, args=args, daemon=True).start()
    bpy.app.timers.register(pump, first_interval=0.2)
    return None


def start_shot(context, task_text):
    """Main thread: capture settings and launch a shot worker on the current scene."""
    s = context.scene.world_builder
    prefs = context.preferences.addons[__name__].preferences
    res = {"R720": (1280, 720), "R1080": (1920, 1080), "SQUARE": (1080, 1080)}[s.resolution]
    root, render_dir, _ = get_dirs(prefs)
    cfg = {"model": s.model, "custom_model": s.custom_model, "reasoning": s.reasoning,
           "passes": s.vision_passes, "resolution": res, "style": s.style, "detail": s.detail,
           "add_mode": s.add_mode, "extra": s.extra,
           "claude_model": s.claude_model, "claude_bin": prefs.claude_path,
           "project_dir": root, "render_dir": render_dir,
           "duration": s.shot_duration, "fps": int(s.shot_fps), "final_quality": s.shot_final,
           "multicut": s.shot_multicut, "multicut_n": s.shot_cuts,
           "multicam": s.shot_multicam, "multicam_n": s.shot_cams,
           "slug": re.sub(r"[^a-z0-9]+", "-", task_text.lower())[:40].strip("-") or "shot"}
    if s.model == "CLAUDE_CODE":
        if not os.path.exists(prefs.claude_path):
            return "claude CLI not found — set its path in Add-on Preferences"
        cfg["exec_helper"] = ensure_exec_helper(root)
        target, args = worker_shot_claude, (task_text, cfg)
    else:
        key = api_key(prefs)
        if not key:
            return "No API key — set it in Add-on Preferences or the .env file"
        target, args = worker_shot, (task_text, key, cfg)
    state.update(running=True, cancel=False, log=[], status="starting shot...", record_done=False)
    threading.Thread(target=target, args=args, daemon=True).start()
    bpy.app.timers.register(pump, first_interval=0.2)
    return None


# ------------------------------------------------------------ operators

class WB_OT_build(bpy.types.Operator):
    bl_idname = "world_builder.build"
    bl_label = "Build World?"
    bl_description = "Send the prompt to the LLM and build the world"

    @classmethod
    def poll(cls, context):
        return not state["running"]

    def invoke(self, context, event):
        if context.scene.world_builder.add_mode:
            return self.execute(context)  # additive builds don't destroy anything
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.world_builder
        if not s.prompt.strip():
            self.report({'ERROR'}, "Type a world description first")
            return {'CANCELLED'}
        if not s.add_mode and s.backup and len(context.scene.objects) > 0:
            worlds = get_dirs(context.preferences.addons[__name__].preferences)[2]
            os.makedirs(worlds, exist_ok=True)
            try:
                bpy.ops.wm.save_as_mainfile(
                    filepath=os.path.join(worlds, f"backup-{int(time.time())}.blend"), copy=True)
            except RuntimeError:
                pass  # unsaved images etc. — don't block the build over a backup
        err = start_worker(context, s.prompt.strip(), resume=False)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        return {'FINISHED'}


class WB_OT_refine(bpy.types.Operator):
    bl_idname = "world_builder.refine"
    bl_label = "Refine"
    bl_description = "Send feedback about the built world; the model sees the last render and edits the scene"

    @classmethod
    def poll(cls, context):
        return not state["running"] and state["can_refine"]

    def execute(self, context):
        s = context.scene.world_builder
        if not s.refine_text.strip():
            self.report({'ERROR'}, "Type refine feedback first")
            return {'CANCELLED'}
        err = start_worker(context, s.refine_text.strip(), resume=True)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        s.refine_text = ""
        return {'FINISHED'}


class WB_OT_shot(bpy.types.Operator):
    bl_idname = "world_builder.shot"
    bl_label = "Program & Record Shot"
    bl_description = ("The model programs the camera animation on the current scene, "
                      "then the addon records it to MP4 at the Settings resolution")

    @classmethod
    def poll(cls, context):
        return not state["running"]

    def execute(self, context):
        s = context.scene.world_builder
        if not s.shot_prompt.strip():
            self.report({'ERROR'}, "Describe the camera motion first")
            return {'CANCELLED'}
        err = start_shot(context, s.shot_prompt.strip())
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        return {'FINISHED'}


class WB_OT_clear_rig(bpy.types.Operator):
    bl_idname = "world_builder.clear_shot_rig"
    bl_label = "Clear Shot Rig"
    bl_description = ("Remove shot markers and shot cameras (ShotCam / Cam_*), clear camera animation, "
                      "and restore a single static camera")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        removed = len(scene.timeline_markers)
        scene.timeline_markers.clear()
        cams = [o for o in scene.objects if o.type == 'CAMERA']
        original = bpy.data.objects.get("Camera")
        keep = (original if original in cams else None) or scene.camera or (cams[0] if cams else None)
        for o in cams:
            if o is keep:
                continue
            if o.name.startswith("ShotCam") or (o.name.startswith("Cam") and o.name != "Camera"):
                bpy.data.objects.remove(o, do_unlink=True)
                removed += 1
        if keep:
            keep.animation_data_clear()
            if keep.data:
                keep.data.animation_data_clear()
            for c in list(keep.constraints):
                if c.type in ('TRACK_TO', 'FOLLOW_PATH'):
                    keep.constraints.remove(c)
            scene.camera = keep
        scene.frame_set(scene.frame_start)
        self.report({'INFO'}, f"Shot rig cleared ({removed} markers/cameras removed)")
        return {'FINISHED'}


class WB_OT_cancel(bpy.types.Operator):
    bl_idname = "world_builder.cancel"
    bl_label = "Cancel"
    bl_description = "Stop after the current step"

    def execute(self, context):
        state["cancel"] = True
        proc = state.get("proc")
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        return {'FINISHED'}


class WB_OT_open_renders(bpy.types.Operator):
    bl_idname = "world_builder.open_renders"
    bl_label = "Renders"
    bl_description = "Open the renders folder"

    def execute(self, context):
        renders = get_dirs(context.preferences.addons[__name__].preferences)[1]
        os.makedirs(renders, exist_ok=True)
        bpy.ops.wm.path_open(filepath=renders)
        return {'FINISHED'}


class WB_OT_save_world(bpy.types.Operator):
    bl_idname = "world_builder.save_world"
    bl_label = "Save World"
    bl_description = "Save a .blend copy of this world into the worlds folder"

    def execute(self, context):
        worlds = get_dirs(context.preferences.addons[__name__].preferences)[2]
        os.makedirs(worlds, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", (context.scene.world_builder.prompt or "world").lower())[:40].strip("-") or "world"
        path = os.path.join(worlds, f"{slug}-{int(time.time())}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        self.report({'INFO'}, "Saved " + os.path.basename(path))
        return {'FINISHED'}


# ------------------------------------------------------------ UI

class WB_PT_panel(bpy.types.Panel):
    bl_idname = "WB_PT_panel"
    bl_label = "World Builder"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"

    def draw(self, context):
        s = context.scene.world_builder
        col = self.layout.column()
        col.prop(s, "prompt", text="")
        row = col.row(align=True)
        row.prop(s, "style", text="")
        row.prop(s, "detail", text="")
        col.prop(s, "add_mode")
        col.prop(s, "extra", text="", icon='TEXT')
        col.separator()
        if state["running"]:
            col.operator("world_builder.cancel", icon='X')
            mins, secs = divmod(int(time.time() - state["started"]), 60)
            col.label(text=f"{state['status'][:44]} · {mins}:{secs:02d}")
        else:
            col.operator("world_builder.build", text="Build World", icon='PLAY')
            col.label(text="Status: " + state["status"][:48])
        if state["log"]:
            box = col.box().column(align=True)
            for line in state["log"][-12:]:
                box.label(text=line[:55])
        if state["can_refine"] and not state["running"]:
            col.separator()
            col.label(text="Refine the world:")
            row = col.row(align=True)
            row.prop(s, "refine_text", text="")
            row.operator("world_builder.refine", text="", icon='CHECKMARK')
        u = state["usage"]
        if u["prompt"]:
            cost = f" · ${state['cost']:.4f}" if state["cost"] else ""
            col.label(text=f"tokens {u['prompt']:,} in / {u['completion']:,} out{cost}")


class WB_PT_shot(bpy.types.Panel):
    bl_idname = "WB_PT_shot"
    bl_label = "Camera Shot"
    bl_parent_id = "WB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"

    def draw(self, context):
        s = context.scene.world_builder
        col = self.layout.column()
        col.prop(s, "shot_prompt", text="")
        row = col.row(align=True)
        row.prop(s, "shot_duration")
        row.prop(s, "shot_fps", text="")
        row = col.row(align=True)
        row.prop(s, "shot_multicut")
        sub = row.row(align=True)
        sub.active = s.shot_multicut
        sub.prop(s, "shot_cuts", text="")
        row = col.row(align=True)
        row.prop(s, "shot_multicam")
        sub = row.row(align=True)
        sub.active = s.shot_multicam
        sub.prop(s, "shot_cams", text="")
        col.prop(s, "shot_final")
        col.operator("world_builder.shot", icon='RENDER_ANIMATION')
        col.operator("world_builder.clear_shot_rig", icon='TRASH')
        col.label(text="Records MP4 at the Settings resolution")


class WB_PT_settings(bpy.types.Panel):
    bl_idname = "WB_PT_settings"
    bl_label = "Settings"
    bl_parent_id = "WB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.world_builder
        col = self.layout.column()
        col.prop(s, "model")
        if s.model == "CUSTOM":
            col.prop(s, "custom_model", text="Model ID")
        if s.model == "CLAUDE_CODE":
            col.prop(s, "claude_model")
        else:
            col.prop(s, "reasoning")
        col.prop(s, "vision_passes")
        col.prop(s, "resolution")
        col.prop(s, "backup")
        row = col.row(align=True)
        row.operator("world_builder.open_renders", icon='FILE_FOLDER')
        row.operator("world_builder.save_world", icon='FILE_BLEND')


class WBSettings(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="World prompt", default="",
        description="Describe the world to build, e.g. 'a cozy medieval village at dusk'")
    style: bpy.props.EnumProperty(
        name="Style", default="LOWPOLY",
        items=[("LOWPOLY", "Low Poly", "Clean flat-shaded low-poly look"),
               ("STYLIZED", "Stylized", "Chunky playful proportions, saturated colors"),
               ("REALISTIC", "Realistic-ish", "Believable proportions and material variation"),
               ("CUSTOM", "Custom", "No style preset — describe it in Extra instructions")])
    detail: bpy.props.EnumProperty(
        name="Detail", default="STANDARD",
        items=[("QUICK", "Quick", "4-6 build steps, essential forms"),
               ("STANDARD", "Standard", "6-12 build steps"),
               ("DETAILED", "Detailed", "12-20 build steps, more variety and props")])
    add_mode: bpy.props.BoolProperty(
        name="Add to current scene", default=False,
        description="Build into the existing scene instead of replacing it")
    extra: bpy.props.StringProperty(
        name="Extra instructions", default="",
        description="Optional extra requirements, e.g. 'night time, no cacti, add a river'")
    refine_text: bpy.props.StringProperty(
        name="Refine", default="",
        description="Feedback for the built world, e.g. 'raise the camera and add more trees'")
    shot_prompt: bpy.props.StringProperty(
        name="Motion", default="",
        description="Camera motion to program, e.g. 'slow 360 orbit around the village, gently descending'")
    shot_duration: bpy.props.FloatProperty(
        name="Seconds", default=5.0, min=1.0, max=60.0,
        description="Shot duration in seconds")
    shot_fps: bpy.props.EnumProperty(
        name="FPS", default="24",
        items=[("24", "24 fps", ""), ("30", "30 fps", ""), ("60", "60 fps", "")])
    shot_final: bpy.props.BoolProperty(
        name="Final quality render", default=False,
        description="Record with the full render engine (slow). Off = fast OpenGL viewport capture "
                    "in the viewport's current shading")
    shot_multicut: bpy.props.BoolProperty(
        name="Multi-cut", default=False,
        description="Break the shot into multiple hard cuts with varied angles and shot sizes")
    shot_cuts: bpy.props.IntProperty(
        name="Cuts", default=0, min=0, max=12,
        description="Number of cuts; 0 = the model chooses")
    shot_multicam: bpy.props.BoolProperty(
        name="Multi-cam", default=False,
        description="Use multiple cameras switched via timeline markers")
    shot_cams: bpy.props.IntProperty(
        name="Cameras", default=0, min=0, max=8,
        description="Number of cameras; 0 = the model chooses")
    model: bpy.props.EnumProperty(
        name="Model", default="GLM_FLASH",
        items=[("GLM_FLASH", "GLM 5.3 Flash", "z-ai/glm-5.3-flash via OpenRouter (was ox-alpha)"),
               ("CLAUDE_CODE", "Claude Code", "Local headless Claude Code — runs on your subscription"),
               ("CUSTOM", "Custom OpenRouter", "Any OpenRouter model ID")])
    claude_model: bpy.props.EnumProperty(
        name="Claude model", default="SONNET",
        items=[("DEFAULT", "CLI default", "Whatever your claude CLI defaults to"),
               ("OPUS", "Opus", "Most capable"),
               ("SONNET", "Sonnet", "Fast and strong (recommended)"),
               ("HAIKU", "Haiku", "Fastest")])
    custom_model: bpy.props.StringProperty(
        name="Custom model ID", default="",
        description="OpenRouter model ID, e.g. 'anthropic/claude-sonnet-5'")
    reasoning: bpy.props.EnumProperty(
        name="Reasoning", default="LOW",
        items=[("OFF", "Off", "Fastest, no thinking"),
               ("LOW", "Low", "Quick thinking (recommended)"),
               ("MEDIUM", "Medium", "More planning, slower"),
               ("HIGH", "High", "Deep planning — can take minutes per turn")])
    vision_passes: bpy.props.IntProperty(
        name="Vision critique passes", default=1, min=0, max=3,
        description="After building, render the scene and let the model critique and fix it this many times")
    resolution: bpy.props.EnumProperty(
        name="Resolution", default="R720",
        items=[("R720", "1280 × 720", ""), ("R1080", "1920 × 1080", ""), ("SQUARE", "1080 × 1080", "")])
    backup: bpy.props.BoolProperty(
        name="Backup scene before replacing", default=True,
        description="Save a .blend copy to the worlds folder before a replace-mode build")


class WB_prefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    project_dir: bpy.props.StringProperty(
        name="Project folder", subtype='DIR_PATH', default=DEFAULT_PROJECT_DIR,
        description="Where renders/, worlds/, steps/, and .env live")
    api_key: bpy.props.StringProperty(
        name="OpenRouter API Key", subtype='PASSWORD',
        description="Leave empty to use the OPENROUTER_API_KEY env var or a .env file")
    env_path: bpy.props.StringProperty(
        name=".env path", subtype='FILE_PATH', default="",
        description="Optional; empty = <project folder>/.env")
    claude_path: bpy.props.StringProperty(
        name="claude CLI path", subtype='FILE_PATH', default=_find_claude())

    def draw(self, context):
        self.layout.prop(self, "project_dir")
        self.layout.prop(self, "api_key")
        self.layout.prop(self, "env_path")
        self.layout.prop(self, "claude_path")


classes = (WBSettings, WB_OT_build, WB_OT_refine, WB_OT_shot, WB_OT_clear_rig, WB_OT_cancel,
           WB_OT_open_renders, WB_OT_save_world, WB_PT_panel, WB_PT_shot, WB_PT_settings, WB_prefs)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.world_builder = bpy.props.PointerProperty(type=WBSettings)


def unregister():
    del bpy.types.Scene.world_builder
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
