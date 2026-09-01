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
    "version": (3, 7),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > World Builder",
    "description": "Prompt an LLM (OpenRouter) to build, critique, and refine 3D worlds in the current scene",
    "category": "3D View",
}

import base64
import json
import math
import os
import queue
import re
import subprocess
import tempfile
import textwrap
import threading
import time
import traceback
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import bpy

try:
    from mathutils import Vector
except ImportError:  # pytest fake-bpy environment
    Vector = None

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
RESOLUTIONS = {"R720": (1280, 720), "R1080": (1920, 1080), "SQUARE": (1080, 1080),
               "VERT916": (1080, 1920), "UW219": (2560, 1080)}

# ---------------------------------------------------------------- prompts

SCENE_RULES = """- ALWAYS set `result` to a small JSON-serializable dict: what you created (names, counts, rough positions).
- Prefer bpy.data over bpy.ops where practical; ops that need UI context fail here.
- Put each group in its own collection. Ground is at z=0; use sensible real-world scale (a house is 4-6m).
- Keep the WHOLE scene inside a ~150m footprint. Big subjects (a city, an island, a mountain range)
  become a compact diorama at reduced scale, NOT true-scale sprawl — cameras, sun angles, and clip
  distances all assume that envelope.
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

FLOW_REMASTER = """
REMASTER the existing scene: study it, then upgrade it IN PLACE to the requested style and detail.
Do NOT clear the scene. First call: inspect it (object names, bounding boxes, materials, collections)
and set `result` to that summary. The existing layout, proportions, and composition are the ground
truth — keep every object's position, footprint, and role. Then upgrade group by group, one logical
group per call: replace or refine placeholder/low-poly objects with more detailed versions in the
same spot at the same scale (real profiles, bevels, subdivision, ornament and trim, richer materials,
small supporting props), then relight to match the target style, camera only if nothing is framed."""

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

BRIEF_CHECK = """
Also grade the render against the Creative Director's brief above: is the focal point actually dominant
(size, light, accent color)? Is the palette holding 60/30/10 with saturation only at the focal? Does the
lighting match the recipe? Are clusters grounded, varied, and separated by rest areas? Fix what misses."""

SHOT_BRIEF_CHECK = """
Also check each frame against the Film Director's shot plan above: right shot size, angle, movement, and
lens per cut? Fix deviations by editing the keyframes."""

# ------------------------------------------- director knowledge bases
# Creative KB distilled from docs/art-direction-research.md (production design, concept
# art, level design, CG lighting). Film KB distilled from cinematography shot-grammar
# research (shot sizes / angles / movements / lenses) plus Blender technique mappings.

CREATIVE_KB = """ART-DIRECTION PRINCIPLES

STORY & WORLD
- Boil the request to ONE mood word; every object, color, and light must serve it.
- Give the place one line of backstory (who lives here, what just happened); let it dictate materials and wear.
- Every prop is evidence — who put it here, when, why HERE. A minimum story is 3 related props (axe + stump +
  woodpile). Stage one interrupted action (cart mid-load, tools at a half-mended fence, door left ajar).
- Materials obey geography (build from what is locally abundant); one era = one construction logic (matching
  door heights, roof pitches, ornament) unless a mismatch IS the story.

COMPOSITION — what makes the image read
- Exactly ONE focal structure; design outward from it. Stack cues on it: tallest (2-4x its neighbors, which
  stay under ~1/2 its height), brightest light, strongest value contrast, the accent color, highest detail,
  a clean isolated silhouette with a clutter-free base.
- Big/Medium/Small: 1 dominant mass, 2-4 medium supports, many small accents, in obvious 2-3x size steps;
  odd counts (3/5) for similar items; at most 1-2 secondary interest points, clearly weaker.
- Aim 1-2 leading lines at the focal: an S-curved path, fence line, stream, or tree row from a lower frame corner.
- Three depth layers from the camera: a darker simple foreground element near a frame edge, the focal in the
  lit midground, a calm desaturated background; layers overlap — no floating islands of props.
- Shape motif per mood — round = friendly/safe, square = stable/ordered, triangle/diagonal = danger/tension;
  bias the big masses toward it and break it exactly once, at the focal.
- Detail budget 70/30: the focal and the route to it carry ~70% of the detail; 30-50% of the scene stays calm
  rest area. Bring 3 hero objects to full detail rather than 30 to half.

PLACEMENT — what makes it believable
- Cluster, don't scatter: groups of 2-5 related objects with real gaps between groups (gap >= cluster width).
- Vary every organic duplicate: rotation free, scale +/-10-25%, slight tilt; manufactured repeats (posts,
  lamps) keep identical scale but get small spacing/rotation jitter; 5-10% of any man-made series is broken,
  leaning, or missing.
- Orient by use: benches face views, tools face their work, signs face the road, chairs face tables; only
  debris is random.
- Ground everything: sink bases slightly into the terrain; dress 30-60% of each building's base line with
  grass tufts, stones, or dirt; wear goes where feet and hands go (path centers worn bare with irregular
  edges, thresholds, handles).
- Human anchor in every view: door 2-2.2m, seat 0.45m, table 0.75m, fence 1m, one-story house 3-4m, mature
  trees 8-15m (taller than a cottage). Any size that can't be justified against a 1.8m human is wrong.
- Vegetation clumps boldly: dense near water and walls, bare gaps elsewhere; shrubs cluster AROUND trees;
  forest edges fade out over a band, never a hard line.

COLOR & LIGHT
- Palette 60/30/10: dominant hue family on the large surfaces (ground, sky, biggest objects), secondary on
  mids, and the saturated accent ONLY on/near the focal. 2-3 hue families plus neutrals biased toward the
  dominant; most surfaces under ~0.25 saturation.
- Value before color: the scene must read as 2-3 value masses; maximum light-dark contrast at the focal ONLY
  (light focal on dark surround, or dark on light).
- ONE shadow-casting key light, 30-60 degrees off the camera axis (3/4 backlight gives the best depth); warm
  key = cool shadows and vice versa. The world background is the fill light and tints every shadow — always
  set it deliberately, never default grey.
- Key:fill ratio is the mood dial: ~2:1 cheerful, ~4:1 drama, ~8:1 noir/tension.
- Time-of-day recipes (Blender sun): golden hour = elevation 5-15 deg, color (1.0, 0.72, 0.45), angle 2-3 deg,
  warm horizon / desaturated blue sky; midday = elevation 50-70 deg, (1.0, 0.95, 0.9), angle 0.5 deg, hard
  shadows, cool shadow fill; overcast = weak sun with angle 15 deg+, world a light cool grey
  (0.75, 0.78, 0.82), object colors dominate; night = moon (0.6, 0.7, 0.9) at low strength, elevation
  30-60 deg, world near-black blue (~0.02), keep the blue desaturated; a warm practical (1.0, 0.6, 0.35) at
  dusk or night is an instant focal accent.
- Atmosphere: near = warmer/saturated/contrasty, far = cooler/desaturated/flat; light haze separates depth
  layers better than geometry can."""

FILM_KB = """CINEMATOGRAPHY PRINCIPLES

SHOT SIZES: EWS = subject tiny in a vast environment (awe, scale, isolation) | WS = whole subject plus
surroundings (context, geography) | MS = mid distance (action, natural engagement) | MCU/CU = close on the
subject or one part (emotion, intimacy) | ECU/INSERT = a single detail fills the frame (intensity, a clue).
ANGLES: eye level ~1.6m = neutral | low, looking up = subject powerful/imposing | high, looking down =
subject small/vulnerable | bird's-eye straight down = map-like overview | worm's-eye from the ground =
overwhelming scale | Dutch roll 5-15 deg = unease, chaos | high aerial sweep = epic scope, openings/transitions.
MOVEMENTS — each with its Blender technique:
- static hold: no camera keys; let scene motion play
- push-in / pull-out: location keys toward/away from the subject (tension builds / context reveals)
- pan / tilt: rotation keys from a fixed position (survey, reveal, follow)
- tracking / truck: location keys parallel to the subject's travel; aim with TRACK_TO on an (animated) empty
- orbit / arc: FOLLOW_PATH on a circle around the subject, key offset_factor with use_fixed_location=True
  (hero moment, transformation)
- crane: Z location keys + TRACK_TO (rising = freedom/scale, descending = grounding/arrival)
- dolly zoom: counter-key camera location and cam.data.lens (background warps — dread, realization)
- rack focus: enable cam.data.dof and key focus_distance between subjects (redirects attention)
- handheld: small noise F-curve modifiers on rotation (urgency, realism)
- whip pan: very fast rotation keys (energy; use as a transition between cuts)
LENSES (cam.data.lens, mm): 18-35 wide = immersive, exaggerates depth and speed — establishing/tracking;
35-65 normal = human-eye honest; 70-200 telephoto = compresses layers, isolates the subject (romantic,
voyeuristic). Wide lens + low close camera = towering drama; long lens + distance = flattened postcard layers.
COMPOSITION IN MOTION: keep the subject at a thirds intersection with lead room in its direction of travel;
low horizon = epic sky and looming subjects, high horizon = terrain patterns; pass a foreground element near
the lens during moves for depth; start AND end every shot on a readable composition; never clip geometry.
PACING: one idea per shot; slow = contemplative/ominous, fast = urgent; always ease in/out (BEZIER handles);
at every cut change BOTH size and angle (wide -> medium -> close beats same-size cuts); hold each cut at
least 2 seconds; put the biggest size jump at the story's peak.
GENRE DEFAULTS: action = wide + tracking/handheld, low angles, fast cuts | drama = MS/MCU, eye level, slow
push-in | horror/thriller = Dutch + creeping push-in, dolly zoom, low/high mix | romance = CU, arc move,
telephoto, rack focus | epic/fantasy = EWS + crane/aerial, low angle on the hero, wide lens | documentary =
eye level, pans and tracks, normal lens."""


def director_system(kind):
    if kind == "scene":
        return ("You are the CREATIVE DIRECTOR for a 3D scene about to be built in Blender. Turn the request "
                "into a short, specific art-direction brief that a 3D artist will execute. No code, no "
                "preamble, under 350 words. Answer in exactly this format:\n"
                "MOOD: <one word> — <one-line story of this place>\n"
                "FOCAL POINT: <the one hero element>, where it sits, how it dominates (size/light/accent/detail)\n"
                "LAYOUT: big/medium/small masses; the clusters and their contents; the leading line; the "
                "foreground framing element; where the rest areas are\n"
                "PALETTE: dominant <color>, secondary <color>, accent <color> (focal only); material notes\n"
                "LIGHTING: time of day; sun elevation/angle/RGB; world color; key:fill ratio; any accent light\n"
                "CAMERA: height, lens feel, and what the frame shows (foreground / focal / background)\n"
                "STORY BEATS: 3-5 prop clusters that tell the story (objects + the why)\n"
                "AVOID: the 3 most likely mistakes for THIS scene\n\n" + CREATIVE_KB)
    return ("You are the FILM DIRECTOR planning camera work for an EXISTING 3D scene in Blender. Turn the "
            "motion request into a short shot plan that a cinematographer will keyframe. You have not seen "
            "the scene, so name subjects generically from the request — the cinematographer inspects the "
            "scene first and adapts positions. No code, no preamble, under 300 words. Answer in exactly "
            "this format:\n"
            "INTENT: what this camera work communicates\n"
            "SHOTS: one numbered line per shot/cut — frames <start-end>: <size> from <angle>, <movement + "
            "Blender technique>, lens <mm>, subject + framing\n"
            "PACING: speed and easing notes tied to the mood\n"
            "AVOID: 2-3 likely mistakes for THIS move\n\n" + FILM_KB)


def director_task(task_text, cfg, kind):
    if kind == "scene":
        parts = [STYLES[cfg["style"]] or "Style: user-defined.", DETAILS[cfg["detail"]]]
        if cfg.get("mode") == "ADD":
            parts.append("NOTE: this ADDS to an existing scene — brief only the new content and how it "
                         "ties in with what exists; do not re-plan the whole scene.")
        elif cfg.get("mode") == "REMASTER":
            parts.append("NOTE: this REMASTERS an existing scene — keep its layout, proportions, and "
                         "composition; brief how to upgrade what already exists to the target style "
                         "and detail, not a new scene.")
        if cfg["extra"].strip():
            parts.append("User requirements: " + cfg["extra"].strip())
        parts.append("SCENE REQUEST: " + task_text)
        return "\n".join(parts)
    frames = max(int(cfg["duration"] * cfg["fps"]), 1)
    if cfg.get("film"):
        parts = [
            f"Plan a MULTI-SHOT FILM of about {cfg['duration']:.0f}s total at {cfg['fps']} fps: 2-6 separate "
            "single-take shots that will be recorded individually and hard-cut together in an editor. "
            "No cuts INSIDE a shot. Vary size and angle between consecutive shots; put the biggest jump at "
            "the peak; each shot at least 2s.",
            "After the prose plan, append EXACTLY ONE fenced block in this precise shape (prompt = a "
            "self-contained instruction for that one take: size, angle, movement + Blender technique, "
            "lens mm, subject and framing):\n"
            '```json\n{"shots": [{"name": "opening-wide", "seconds": 5, "prompt": "..."}]}\n```',
            "FILM REQUEST: " + task_text,
        ]
        return "\n".join(parts)
    parts = [f"Shot duration: {cfg['duration']}s at {cfg['fps']} fps = frames 1-{frames}."]
    if cfg.get("multicut"):
        parts.append(f"Required: {cfg['multicut_n'] or 'a fitting number of'} hard cuts.")
    if cfg.get("multicam"):
        parts.append(f"Required: {cfg['multicam_n'] or 'several'} distinct cameras with marker-bound switching.")
    parts.append("MOTION REQUEST: " + task_text)
    return "\n".join(parts)


def parse_shot_plan(text):
    """Extract the film shot list from a Film Director brief. None on any failure (soft-fail)."""
    blocks = re.findall(r"```json\s*\n(.*?)```", text or "", re.S)
    if not blocks:
        return None
    try:
        raw = json.loads(blocks[-1]).get("shots") or []
    except (ValueError, AttributeError):
        return None
    shots = []
    for i, s in enumerate(raw[:8]):
        if not isinstance(s, dict):
            continue
        prompt = str(s.get("prompt") or "").strip()
        if not prompt:
            continue
        name = re.sub(r"[^a-z0-9]+", "-", str(s.get("name") or "").lower()).strip("-")
        try:
            seconds = min(max(float(s.get("seconds", 5)), 2.0), 20.0)
        except (TypeError, ValueError):
            seconds = 5.0
        shots.append({"name": name or f"shot-{i + 1}", "seconds": seconds, "prompt": prompt})
    return shots or None

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

ASSET_TOOL = {
    "type": "function",
    "function": {
        "name": "import_asset",
        "description": ("Search a CC0 model library and import the best match into the scene as a new "
                        "collection. Use for complex PROPS (furniture, vehicles, barrels, creatures, "
                        "tools) instead of modelling them from primitives. Terrain, buildings, and "
                        "simple shapes stay procedural. Returns the imported object names and "
                        "dimensions so you can place and scale them afterwards with run_blender."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "1-3 plain search words, e.g. 'barrel' or 'pine tree'"},
            },
            "required": ["query"],
        },
    },
}


def build_tools(cfg):
    return TOOLS + ([ASSET_TOOL] if cfg.get("assets") else [])


IMPORT_CODE = """
import bpy
from mathutils import Vector
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=__PATH__)
new = [o for o in bpy.data.objects if o not in before]
col = bpy.data.collections.new(__CNAME__)
bpy.context.scene.collection.children.link(col)
for o in new:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    col.objects.link(o)
root = bpy.data.objects.new(__CNAME__ + "_root", None)
col.objects.link(root)
pts = [o.matrix_world @ Vector(b) for o in new if o.type == 'MESH' for b in o.bound_box]
if pts:
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    root.location = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2])
    dims = [round(hi[i] - lo[i], 2) for i in range(3)]
else:
    dims = None
for o in new:
    if o.parent is None:
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()
result = {"objects": [o.name for o in new], "root_empty": root.name, "collection": col.name,
          "dimensions_m": dims,
          "note": "move/rotate/scale the root empty to place the asset; scale it if dimensions_m "
                  "is out of proportion with the scene"}
"""


def import_asset_call(args, cfg):
    """Worker thread: search+download (network), then import on the main thread. Returns tool-result text."""
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: empty query"
    state["status"] = f"importing asset: {query}..."
    try:
        got = fetch_asset(query, cfg)
    except Exception as e:
        return f"ERROR: asset fetch failed ({e}) — build it from primitives instead."
    if not got:
        return f"NO MATCH for '{query}' in the CC0 library — build it from primitives instead."
    code = (IMPORT_CODE.replace("__PATH__", json.dumps(got["file"]))
            .replace("__CNAME__", json.dumps("Asset_" + got["name"][:24])))
    try:
        return exec_on_main(code, timeout=300)[:8000]
    except queue.Empty:
        return "ERROR: import timed out"


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

CLEAR_RIG_CODE = """
import bpy, sys
wb = sys.modules[__MODULE__]
result = {"removed": wb.do_clear_rig(bpy.context.scene)}
"""

# Bake the EVALUATED active camera per frame (marker-bound switches resolved manually) — ground
# truth of the take's camera move no matter how the model rigged it. Lets Rerender replay it later.
BAKE_CAM_CODE = """
import bpy
scene = bpy.context.scene
frames = __FRAMES__
mk = sorted([(m.frame, m.camera) for m in scene.timeline_markers if m.camera], key=lambda t: t[0])
cur = scene.frame_current
rows, static = [], None
for f in range(1, frames + 1):
    scene.frame_set(f)
    cam = scene.camera
    for mf, mc in mk:
        if mf <= f:
            cam = mc
    if cam is None:
        break
    deps = bpy.context.evaluated_depsgraph_get()
    ce = cam.evaluated_get(deps)
    loc, rot, _ = ce.matrix_world.decompose()
    d = ce.data
    rows.append([loc.x, loc.y, loc.z, rot.w, rot.x, rot.y, rot.z, d.lens])
    if static is None:
        static = {"lens": d.lens, "sensor_width": d.sensor_width, "shift_x": d.shift_x,
                  "shift_y": d.shift_y, "clip_start": d.clip_start, "clip_end": d.clip_end,
                  "use_dof": d.dof.use_dof, "focus_distance": d.dof.focus_distance,
                  "aperture_fstop": d.dof.aperture_fstop}
scene.frame_set(cur)
result = {"bake": {"fps": __FPS__, "frames": rows, "static": static} if rows else None}
"""

# Rebuild a take's camera move from its bake onto one fresh unconstrained camera.
REPLAY_RIG_CODE = """
import bpy, json
bake = json.loads(__BAKE__)  # __BAKE__ is a JSON string literal — json booleans aren't python
scene = bpy.context.scene
old = bpy.data.objects.get("WB_Rerender")
if old:
    bpy.data.objects.remove(old, do_unlink=True)
oldd = bpy.data.cameras.get("WB_Rerender")
if oldd:
    bpy.data.cameras.remove(oldd)
camd = bpy.data.cameras.new("WB_Rerender")
st = bake["static"]
camd.lens = st["lens"]
camd.sensor_width = st["sensor_width"]
camd.shift_x, camd.shift_y = st["shift_x"], st["shift_y"]
camd.clip_start, camd.clip_end = st["clip_start"], st["clip_end"]
camd.dof.use_dof = st["use_dof"]
camd.dof.focus_distance = st["focus_distance"]
camd.dof.aperture_fstop = st["aperture_fstop"]
cam = bpy.data.objects.new("WB_Rerender", camd)
scene.collection.objects.link(cam)
cam.rotation_mode = 'QUATERNION'
rows = bake["frames"]
lenses = [r[7] for r in rows]
animate_lens = max(lenses) - min(lenses) > 1e-4
prev = None
# ponytail: per-frame keyframe_insert is O(n^2)-ish; batch via fcurve foreach_set if long takes crawl
for f, r in enumerate(rows, start=1):
    cam.location = r[0:3]
    q = r[3:7]
    if prev is not None and sum(a * b for a, b in zip(q, prev)) < 0:
        q = [-c for c in q]  # keep quaternion sign continuous so interpolation never spins
    prev = q
    cam.rotation_quaternion = q
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_quaternion", frame=f)
    if animate_lens:
        camd.lens = r[7]
        camd.keyframe_insert("lens", frame=f)
scene.camera = cam
scene.frame_set(1)
result = {"rig": cam.name, "frames": len(rows), "lens_animated": animate_lens}
"""

RERENDER_CLEANUP_CODE = """
import bpy
cam = bpy.data.objects.get("WB_Rerender")
if cam:
    bpy.data.objects.remove(cam, do_unlink=True)
camd = bpy.data.cameras.get("WB_Rerender")
if camd:
    bpy.data.cameras.remove(camd)
orig = bpy.data.objects.get("Camera")
if orig and orig.name in bpy.context.scene.objects:
    bpy.context.scene.camera = orig
result = {"cleaned": True}
"""

ASSEMBLE_CODE = """
import bpy, os
paths, out = __PATHS__, __OUT__
old = bpy.data.scenes.get("WB_Edit")
if old:
    bpy.data.scenes.remove(old)
edit = bpy.data.scenes.new("WB_Edit")
edit.render.fps = __FPS__
edit.render.resolution_x, edit.render.resolution_y = __W__, __H__
edit.sequence_editor_create()
se = edit.sequence_editor
seqs = se.strips if hasattr(se, "strips") else se.sequences  # 5.x renamed sequences -> strips (empty is falsy!)
frame = 1
for i, p in enumerate(paths):
    strip = seqs.new_movie(name="shot%02d" % (i + 1), filepath=p, channel=1, frame_start=frame)
    frame = int(strip.frame_final_end)
edit.frame_start, edit.frame_end = 1, max(frame - 1, 1)
if hasattr(edit.render.image_settings, "media_type"):
    edit.render.image_settings.media_type = 'VIDEO'
edit.render.image_settings.file_format = 'FFMPEG'
edit.render.ffmpeg.format = 'MPEG4'
edit.render.ffmpeg.codec = 'H264'
edit.render.ffmpeg.constant_rate_factor = 'HIGH'
edit.render.filepath = out
prev = bpy.context.window.scene
bpy.context.window.scene = edit
try:
    bpy.ops.render.render(animation=True)
finally:
    bpy.context.window.scene = prev
result = {"film": out, "frames": edit.frame_end, "shots": len(paths)}
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
         "recording": False, "record_done": False,
         "shots": [], "film_brief": None, "last_film": None}
code_q = queue.Queue()  # worker thread -> main thread: (code, reply_queue)


def log(line):
    state["log"] = (state["log"] + [line])[-60:]


# Fixed machine-level key file: survives Blender wiping addon prefs on disable, and lets the
# project/save folder move freely without dragging the API keys along with it.
GLOBAL_ENV = os.path.expanduser("~/.config/worldbuilder/.env")


def env_lookup(prefs, var):
    """os env, then explicit env_path, project .env, and the global .env. No bpy — any thread."""
    if os.environ.get(var):
        return os.environ[var]
    explicit = os.path.expanduser(prefs.env_path) if prefs.env_path.strip() else None
    for env_file in filter(None, [explicit, os.path.join(get_dirs(prefs)[0], ".env"), GLOBAL_ENV]):
        try:
            for line in open(env_file):
                if line.strip().startswith(var):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return None


def api_key(prefs):
    return prefs.api_key or env_lookup(prefs, "OPENROUTER_API_KEY")


def polypizza_key(prefs):
    return prefs.polypizza_key or env_lookup(prefs, "POLYPIZZA_API_KEY")


# ------------------------------------------------- CC0 asset sources
# Style routing: LOWPOLY/STYLIZED/CUSTOM -> Poly Pizza (Kenney/Quaternius packs, GLB, free key);
# REALISTIC -> PolyHaven photoscan models (glTF + 1k textures, no key). All CC0.

_ph_cache = {}


def ph_pick(assets, query):
    """Pure: best PolyHaven slug for a keyword query — name/slug hits outweigh tag/category hits."""
    words = [w for w in re.split(r"\W+", (query or "").lower()) if w]
    best, best_score = None, 0
    for slug, a in assets.items():
        names = (slug + " " + a.get("name", "")).lower()
        tags = " ".join(list(a.get("tags", [])) + list(a.get("categories", []))).lower()
        score = sum(2 if w in names else (1 if w in tags else 0) for w in words)
        if score > best_score:
            best, best_score = slug, score
    return best


def pp_pick(data):
    """Pure: first Poly Pizza result with a direct download."""
    for m in data.get("results", []) if isinstance(data, dict) else []:
        if m.get("Download"):
            return {"title": m.get("Title") or "asset", "url": m["Download"]}
    return None


_UA = {"User-Agent": "WorldBuilder-Blender-addon/3.6"}  # some CDNs 403 the default Python-urllib UA


def _download(url, dest):
    """Worker thread: download url to dest unless already cached. Returns dest."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        f.write(r.read())
    os.replace(tmp, dest)
    return dest


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_asset(query, cfg):
    """Worker thread: search + download one CC0 model routed by style. -> {name, file} or None."""
    root = cfg["project_dir"]
    if cfg["style"] == "REALISTIC":
        if not _ph_cache:
            _ph_cache.update(_get_json("https://api.polyhaven.com/assets?type=models"))
        slug = ph_pick(_ph_cache, query)
        if not slug:
            return None
        entry = _get_json(f"https://api.polyhaven.com/files/{slug}")["gltf"]["1k"]["gltf"]
        adir = os.path.join(root, "assets", "polyhaven", slug)
        main = _download(entry["url"], os.path.join(adir, os.path.basename(entry["url"])))
        for rel, meta in (entry.get("include") or {}).items():
            _download(meta["url"], os.path.join(adir, rel))
        return {"name": slug, "file": main}
    key = cfg.get("pp_key")
    if not key:
        return None
    import urllib.parse
    data = _get_json("https://api.poly.pizza/v1.1/search/" + urllib.parse.quote(query) + "?Limit=8",
                     headers={"x-auth-token": key})
    hit = pp_pick(data)
    if not hit:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", hit["title"].lower()).strip("-") or "asset"
    dest = os.path.join(root, "assets", "polypizza", slug, slug + ".glb")
    return {"name": slug, "file": _download(hit["url"], dest)}


def build_system(cfg):
    flow = {"ADD": FLOW_ADD, "REMASTER": FLOW_REMASTER}.get(cfg.get("mode"), FLOW_REPLACE)
    parts = [BASE_RULES, flow, STYLES[cfg["style"]], DETAILS[cfg["detail"]]]
    if cfg.get("assets"):
        src = "PolyHaven photoscans" if cfg["style"] == "REALISTIC" else "Kenney/Quaternius low-poly packs"
        parts.append(
            f"ASSET IMPORT: an import_asset tool searches a CC0 library ({src}) and imports the best "
            "match as a collection with a root empty. Use it for hero and complex props; keep terrain, "
            "ground, and buildings procedural. After each import, place/rotate/scale the root empty with "
            "run_blender using the returned dimensions_m, and keep the scene's style consistent.")
    if cfg["extra"].strip():
        parts.append("Additional user requirements (high priority): " + cfg["extra"].strip())
    return "\n".join(p for p in parts if p)


def chat(messages, key, cfg, tools=True):
    """Backend dispatch — add new backends (e.g. Claude Code) as branches on cfg['model']."""
    model_id = cfg["custom_model"].strip() if cfg["model"] == "CUSTOM" else GLM_ID
    reasoning = {"enabled": False} if cfg["reasoning"] == "OFF" else {"effort": cfg["reasoning"].lower()}
    # cap the completion reservation — without it OpenRouter reserves the model's full budget
    # per call, which 402s low-credit accounts even though replies are a few thousand tokens
    payload = {"model": model_id, "messages": messages, "reasoning": reasoning, "max_tokens": 16384}
    if tools:
        payload["tools"] = build_tools(cfg)
    body = json.dumps(payload).encode()
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


def director_brief(task_text, key, cfg, kind):
    """One no-tools LLM call: turn the request into an art-direction / shot brief. Never fatal."""
    role = "creative director" if kind == "scene" else "film director"
    state["status"] = f"{role} drafting brief..."
    try:
        task = director_task(task_text, cfg, kind)
        labels, imgs = [], []
        if cfg.get("scene_shot"):
            labels.append("a render of the CURRENT scene being remastered")
            imgs.append(image_part(cfg["scene_shot"]))
        if cfg.get("ref_image"):
            labels.append("the user's reference image")
            imgs.append(image_part(cfg["ref_image"]))
        if imgs:
            task = [{"type": "text", "text": task + "\n\nAttached: " + " and ".join(labels) +
                     " — ground the brief in what you see."}] + imgs
        raw = chat([{"role": "system", "content": director_system(kind)},
                    {"role": "user", "content": task}],
                   key, cfg, tools=False)
        brief = (raw.get("content") or "").strip()
        if brief:
            log(f"{role}: brief ready ({len(brief.split())} words)")
            return brief
        log(f"{role}: empty brief — building without one")
    except Exception as e:
        log(f"{role} pass skipped: {str(e)[:70]}")
    return None


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


def fit_clip():
    """Main thread: grow viewport + camera far-clip to fit the scene so big builds aren't culled.

    Only ever raises clip_end — never shrinks what the user set.
    """
    if Vector is None:
        return
    try:
        far = 0.0
        for o in bpy.context.scene.objects:
            if o.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT'):
                continue
            for c in o.bound_box:
                far = max(far, (o.matrix_world @ Vector(c)).length)
        need = min(100000.0, max(1000.0, far * 6))
        for window in bpy.data.window_managers[0].windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    sp = area.spaces.active
                    if sp.clip_end < need:
                        sp.clip_end = need
        cam = bpy.context.scene.camera
        if cam and cam.type == 'CAMERA' and cam.data.clip_end < need:
            cam.data.clip_end = need
    except Exception:
        pass  # cosmetic safety net — never let it break the pump


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
        fit_clip()  # a finished run is the moment a big build would be culled
        return None
    return 0.2


# ------------------------------------------------------------ the loop

def strip_old_images(messages):
    """Keep only the newest render in context — old ones just bloat the payload.
    Skips system + first user message so a user reference image survives refine passes."""
    for m in messages[2:]:
        if isinstance(m.get("content"), list):
            texts = [p.get("text", "") for p in m["content"] if p.get("type") == "text"]
            m["content"] = "\n".join(texts) + "\n[earlier render omitted]"


def image_part(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    kind = "png" if path.lower().endswith(".png") else "jpeg"
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


def handle_tool_calls(msg, messages, cfg):
    """Execute one assistant message's run_blender calls, appending tool results (both GLM loops)."""
    for call in msg["tool_calls"]:
        if state["cancel"]:
            break
        try:
            args = json.loads(call["function"]["arguments"])
            step = args.get("step") or args.get("query") or "build step"
            state["status"] = step
            log("> " + step)
            if call["function"]["name"] == "import_asset":
                result = import_asset_call(args, cfg)
            else:
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
    state["last_bake"] = None
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
        try:  # bake the camera move so this take can be re-recorded later without the LLM
            bake_code = (BAKE_CAM_CODE.replace("__FRAMES__", str(frames))
                         .replace("__FPS__", str(cfg["fps"])))
            resp = json.loads(exec_on_main(bake_code, timeout=frames * 2 + 120))
            state["last_bake"] = (resp.get("result") or {}).get("bake")
        except Exception as e:
            log(f"camera bake skipped: {str(e)[:60]}")
        return path
    if state["record_done"] == "cancelled":
        log("recording cancelled in the render window")
    return None


def shot_convo(messages, key, cfg, has_brief):
    """Worker thread: the GLM shot loop — converse until the take is keyframed (mutates messages)."""
    passes_left = cfg["passes"]
    nudges = anim_retries = 0
    for turn in range(1, 31):
        if state["cancel"]:
            log("cancelled")
            return
        state["status"] = f"thinking (turn {turn})..."
        raw = chat(messages, key, cfg)
        msg = {"role": "assistant", "content": raw.get("content")}
        if raw.get("tool_calls"):
            msg["tool_calls"] = raw["tool_calls"]
        messages.append(msg)
        content = (raw.get("content") or "").strip()
        if msg.get("tool_calls"):
            handle_tool_calls(msg, messages, cfg)
            continue
        if content.upper().startswith("DONE"):
            log(content[:120])
            verify = verify_anim()
            if not (verify.get("camera_animated") or verify.get("any_animated")):
                anim_retries += 1
                if anim_retries > 2:
                    log("still no keyframes after retries; stopping")
                    return
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
                    crit = SHOT_CRITIQUE_MSG + (SHOT_BRIEF_CHECK if has_brief else "")
                    messages.append({"role": "user", "content":
                                     [{"type": "text", "text": crit}]
                                     + [image_part(p) for p in stills]})
                    nudges = 0
                    continue
            return
        if content:
            log(content[:120])
        nudges += 1
        if nudges > 2:
            log("model stopped without DONE")
            return
        messages.append({"role": "user", "content":
                         "Continue with run_blender, or reply DONE: <summary> if finished."})


def shoot(task, key, scfg, brief):
    """Worker thread: keyframe ONE continuous take (backend-dispatched), record it. -> mp4 path or None."""
    if scfg["model"] == "CLAUDE_CODE":
        run_claude(claude_shot_prompt(task, scfg), scfg, max_turns=40)
    else:
        if brief:
            task += "\n\n=== FILM DIRECTOR'S SHOT PLAN (keyframe to this) ===\n" + brief
        messages = [{"role": "system", "content": glm_shot_system(scfg)},
                    {"role": "user", "content": task}]
        shot_convo(messages, key, scfg, bool(brief))
    return None if state["cancel"] else record_shot(scfg)


def assemble_code(paths, cfg, out_path):
    """Pure: fill the VSE assembly template (testable without Blender)."""
    w, h = cfg["resolution"]
    return (ASSEMBLE_CODE.replace("__PATHS__", json.dumps(paths)).replace("__OUT__", json.dumps(out_path))
            .replace("__FPS__", str(cfg["fps"])).replace("__W__", str(w)).replace("__H__", str(h)))


def assemble_film(cfg):
    """Worker thread: hard-cut the recorded takes together in a WB_Edit VSE scene. -> final mp4 or None."""
    paths = [s["path"] for s in state["shots"] if s.get("path")]
    if not paths:
        log("assembly skipped — no recorded takes")
        return None
    state["status"] = f"editing {len(paths)} takes..."
    out = os.path.join(cfg["render_dir"], f"{cfg['slug'][:32]}-film-{int(time.time())}.mp4")
    n_frames = sum(int(s["seconds"] * cfg["fps"]) for s in state["shots"] if s.get("path"))
    try:
        resp = json.loads(exec_on_main(assemble_code(paths, cfg, out), timeout=n_frames * 5 + 300))
    except queue.Empty:
        log("assembly timed out")
        return None
    if resp.get("status") != "ok":
        log("assembly error: " + str(resp.get("traceback", ""))[-90:])
        return None
    state["last_film"] = out
    log("film saved: renders/" + os.path.basename(out) + " (edit kept in the WB_Edit scene)")
    return out


def worker_film(task_text, key, cfg):
    """Both backends: Film Director plans N takes -> shoot each -> assemble the cut."""
    try:
        state["started"] = time.time()
        fcfg = {**cfg, "film": True}
        if cfg["model"] == "CLAUDE_CODE":
            state["status"] = "film director drafting plan..."
            plan_prompt = (director_system("shot").split("Answer in exactly")[0]
                           + "\n" + director_task(task_text, fcfg, "shot")
                           + "\nDo not run any tools — just answer with the prose plan then the json block.")
            _ok, _sid, brief = run_claude(plan_prompt, cfg, max_turns=4)
        else:
            brief = director_brief(task_text, key, fcfg, "shot")
        shots = parse_shot_plan(brief)
        if not shots:
            log("no parseable shot plan — falling back to a single shot")
            path = shoot(task_text, key, cfg, brief)
            state["film_brief"] = brief
            state["shots"] = [{"name": cfg["slug"][:24], "prompt": task_text,
                               "seconds": cfg["duration"], "path": path,
                               "bake": state.pop("last_bake", None)}]
            state["status"] = "cancelled" if state["cancel"] else "done"
            return
        state["film_brief"] = brief
        state["shots"] = [dict(s, path=None) for s in shots]
        log(f"shot plan: {len(shots)} takes — " + ", ".join(s["name"] for s in shots))
        for i, s in enumerate(state["shots"]):
            if state["cancel"]:
                break
            log(f"— shot {i + 1}/{len(state['shots'])}: {s['name']} ({s['seconds']:.0f}s)")
            try:
                exec_on_main(CLEAR_RIG_CODE.replace("__MODULE__", json.dumps(__name__)))
            except queue.Empty:
                pass
            scfg = {**cfg, "duration": s["seconds"], "multicut": False, "multicam": False,
                    "slug": f"{cfg['slug'][:20]}-s{i + 1:02d}-{s['name']}"[:56]}
            task = (f"Shot {i + 1} of {len(state['shots'])} of a film. THIS SHOT ONLY — one continuous "
                    f"take, no cuts, no marker cameras: {s['prompt']}")
            try:
                s["path"] = shoot(task, key, scfg, state["film_brief"])
            except Exception as e:  # a broken take never kills the film — later takes + assembly still run
                log(f"  shot error: {str(e)[:80]}")
            s["bake"] = state.pop("last_bake", None)
            log(("  recorded " + os.path.basename(s["path"])) if s["path"] else "  shot failed — continuing")
        if not state["cancel"]:
            assemble_film(cfg)
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def retake_task(shot, note):
    """Pure: the re-shoot instruction for one rejected take."""
    return (shot["prompt"] + "\n\nRETAKE — the previous take of this shot was rejected. "
            "Director's note (top priority): " + note.strip())


def worker_retake(ix, note, key, cfg):
    """Both backends: clear the rig, re-shoot ONE take fresh with the note, re-assemble if needed."""
    try:
        state["started"] = time.time()
        s = state["shots"][ix]
        log(f"retake {ix + 1}/{len(state['shots'])}: {s['name']}")
        try:
            exec_on_main(CLEAR_RIG_CODE.replace("__MODULE__", json.dumps(__name__)))
        except queue.Empty:
            pass
        scfg = {**cfg, "duration": s["seconds"], "multicut": False, "multicam": False,
                "slug": f"{cfg['slug'][:20]}-s{ix + 1:02d}-{s['name']}-rt"[:56]}
        path = shoot(retake_task(s, note), key, scfg, state.get("film_brief"))
        if path:
            s["path"] = path
            s["bake"] = state.pop("last_bake", None)
        else:
            log("retake failed — keeping the previous take")
        if len(state["shots"]) > 1 and not state["cancel"]:
            assemble_film(cfg)
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def worker_rerender(ix, cfg):
    """No-LLM re-record: replay the take's baked camera move on the current scene, replace its video."""
    try:
        state["started"] = time.time()
        s = state["shots"][ix]
        log(f"rerender {ix + 1}/{len(state['shots'])}: {s['name']}")
        bake = s.get("bake")
        if not bake:
            # take predates baking — the live scene rig is only trustworthy for the last-recorded take
            recorded = [i for i, t in enumerate(state["shots"]) if t.get("path")]
            if not recorded or ix != recorded[-1]:
                log("no saved camera move for this take — use Retake to re-plan it")
                state["status"] = "failed"
                return
            log("no saved camera move — baking the rig currently in the scene")
            frames = max(int(s["seconds"] * cfg["fps"]), 1)
            code = (BAKE_CAM_CODE.replace("__FRAMES__", str(frames))
                    .replace("__FPS__", str(cfg["fps"])))
            bake = json.loads(exec_on_main(code, timeout=frames * 2 + 120)).get("result", {}).get("bake")
            if not bake:
                log("nothing to bake — no camera in the scene")
                state["status"] = "failed"
                return
            s["bake"] = bake
        try:
            exec_on_main(CLEAR_RIG_CODE.replace("__MODULE__", json.dumps(__name__)))
        except queue.Empty:
            pass
        state["status"] = "replaying camera move..."
        exec_on_main(REPLAY_RIG_CODE.replace("__BAKE__", json.dumps(json.dumps(bake))),
                     timeout=len(bake["frames"]) + 300)
        scfg = {**cfg, "duration": len(bake["frames"]) / bake["fps"], "fps": bake["fps"],
                "slug": f"{cfg['slug'][:20]}-s{ix + 1:02d}-{s['name']}-rr"[:56]}
        path = record_shot(scfg)
        state.pop("last_bake", None)  # replay of the same bake — nothing new to keep
        try:
            exec_on_main(RERENDER_CLEANUP_CODE)
        except queue.Empty:
            pass
        if path:
            s["path"] = path
        else:
            log("rerender failed — keeping the previous video")
        if len(state["shots"]) > 1 and not state["cancel"]:
            assemble_film(cfg)
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def worker_shot(task_text, key, cfg):
    """Both backends, shot mode: animate the CURRENT scene, record, remember the take for retakes."""
    try:
        state["started"] = time.time()
        brief = None
        if cfg["model"] != "CLAUDE_CODE":  # Claude does its own Film Director pass in-prompt
            brief = director_brief(task_text, key, cfg, "shot")
        path = shoot(task_text, key, cfg, brief)
        state["film_brief"] = brief
        state["shots"] = [{"name": cfg["slug"][:24], "prompt": task_text,
                           "seconds": cfg["duration"], "path": path,
                           "bake": state.pop("last_bake", None)}]
        state["status"] = "cancelled" if state["cancel"] else "done"
    except Exception as e:
        log(f"FAILED: {e}")
        state["status"] = "failed"
    finally:
        state["proc"] = None
        state["running"] = False


def worker(task_text, key, cfg, resume=False):
    try:
        state["started"] = time.time()
        brief = None
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
            if cfg.get("mode") == "REMASTER":
                state["status"] = "rendering current scene..."
                shot = render_to(CRITIQUE_RENDER, cfg, "before", half=True)
                if shot:
                    cfg["scene_shot"] = shot
                else:
                    log("could not render the current scene — remastering from inspection only")
            brief = director_brief(task_text, key, cfg, "scene")
            if brief:
                task_text += "\n\n=== CREATIVE DIRECTOR'S BRIEF (build to this) ===\n" + brief
            intro, imgs = [], []
            if cfg.get("scene_shot"):
                intro.append("a render of the CURRENT scene you are remastering — study it and "
                             "keep its layout")
                imgs.append(image_part(cfg["scene_shot"]))
            if cfg.get("ref_image"):
                intro.append("the user's reference image — identify its key objects, layout, and "
                             "mood, and match it")
                imgs.append(image_part(cfg["ref_image"]))
            user_content = task_text
            if imgs:
                user_content = [{"type": "text", "text":
                                 "Attached: " + "; ".join(intro) + ".\n\n" + task_text}] + imgs
            messages = [{"role": "system", "content": build_system(cfg)},
                        {"role": "user", "content": user_content}]
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
                handle_tool_calls(msg, messages, cfg)
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
                        crit = CRITIQUE_MSG + (BRIEF_CHECK if brief else "")
                        messages.append({"role": "user",
                                         "content": [{"type": "text", "text": crit}, image_part(path)]})
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
            if cfg.get("mode") != "ADD" and not resume:
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
        "STEP 0 — Creative Director pass: before touching Blender, write yourself a short art-direction "
        "brief for this request (mood word + one-line place story; the ONE focal point and how it dominates; "
        "big/medium/small layout with clusters, a leading line, and rest areas; 60/30/10 palette; lighting "
        "recipe with sun elevation/color and world color; camera intent; 3-5 story prop clusters; pitfalls "
        "to avoid). Ground it in these principles:\n" + CREATIVE_KB +
        "\nThen build the scene TO THAT BRIEF and judge every critique render against it.",
        "Build incrementally — one logical group per script run. Rules for the Blender code:\n" + SCENE_RULES,
        {"ADD": FLOW_ADD, "REMASTER": FLOW_REMASTER}.get(cfg.get("mode"), FLOW_REPLACE),
        STYLES[cfg["style"]],
        DETAILS[cfg["detail"]].replace("tool calls", "script runs"),
    ]
    if cfg.get("assets"):
        if cfg["style"] == "REALISTIC":
            api = ("PolyHaven (no key): list models with "
                   "`https://api.polyhaven.com/assets?type=models` (pick a slug by name/tags), then "
                   "`https://api.polyhaven.com/files/<slug>` -> data['gltf']['1k']['gltf'] has the main "
                   "file 'url' plus an 'include' map of relative-path files — download ALL of them "
                   "preserving relative paths into assets/<slug>/.")
        else:
            api = ("Poly Pizza (key in this folder's .env as POLYPIZZA_API_KEY): GET "
                   "`https://api.poly.pizza/v1.1/search/<query>?Limit=5` with header "
                   "`x-auth-token: <key>`; download a result's 'Download' .glb into assets/.")
        parts.append(
            "ASSET IMPORT (CC0, optional): for complex props, fetch a real model instead of building "
            "primitives. " + api + " Fetch with python3 urllib or curl (send a browser-like User-Agent "
            "header — the default python UA gets 403), then import via the helper: "
            "bpy.ops.import_scene.gltf(filepath='<abs path>'), parent the new objects to a root empty, "
            "and place/scale it. Keep terrain and buildings procedural.")
    if cfg["extra"].strip():
        parts.append("Additional user requirements (high priority): " + cfg["extra"].strip())
    if cfg.get("scene_shot"):
        parts.append(
            "CURRENT SCENE RENDER: " + cfg["scene_shot"] + " — Read this image FIRST and study the "
            "existing scene before changing anything; it is what you are remastering.")
    if cfg.get("ref_image"):
        parts.append(
            "REFERENCE IMAGE: the user attached a reference photo at " + cfg["ref_image"] +
            " — Read it FIRST, identify its key objects, layout, and mood, and build the scene "
            "to match it, guided by the task and your brief.")
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
           "--allowedTools", "Bash(python3:*),Bash(echo:*),Read,Write,Glob,Grep"
                             + (",Bash(curl:*)" if cfg.get("assets") else "")]
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
    ok, session_id, result_text = False, resume_sid, ""
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
            result_text = str(e.get("result") or "")
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
    return ok, session_id, result_text


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
            if cfg.get("mode") == "REMASTER":
                state["status"] = "rendering current scene..."
                shot = render_to(CRITIQUE_RENDER, cfg, "before", half=True)
                if shot:
                    cfg["scene_shot"] = shot
            prompt = claude_prompt(task_text, cfg)
        ok, sid, _text = run_claude(prompt, cfg, resume_sid=state.get("claude_session") if resume else None)
        if sid:
            state["claude_session"] = sid
        if not state["cancel"]:
            if cfg.get("mode") != "ADD" and not resume:
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
        "STEP 0 — Film Director pass: after inspecting the scene, write yourself a short shot plan "
        "(numbered shots with frame ranges; shot size, angle, movement + technique, lens mm, subject and "
        "framing per shot; pacing/easing notes; pitfalls). Ground it in these principles:\n" + FILM_KB +
        "\nThen keyframe TO THAT PLAN and judge your check stills against it.",
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


def start_worker(context, task_text, resume):
    """Main thread: capture settings (threads must never touch bpy), then launch."""
    s = context.scene.world_builder
    prefs = context.preferences.addons[__name__].preferences
    kind = "CLAUDE_CODE" if s.model == "CLAUDE_CODE" else "OPENROUTER"
    if resume and state.get("built_with") != kind:
        return "This world was built with the other backend — switch Model back, or rebuild"
    res = RESOLUTIONS[s.resolution]
    root, render_dir, _ = get_dirs(prefs)
    cfg = {"model": s.model, "custom_model": s.custom_model, "reasoning": s.reasoning,
           "passes": s.vision_passes, "resolution": res, "style": s.style, "detail": s.detail,
           "mode": s.build_mode, "extra": s.extra,
           "claude_model": s.claude_model, "claude_bin": prefs.claude_path,
           "project_dir": root, "render_dir": render_dir,
           "slug": re.sub(r"[^a-z0-9]+", "-", (s.prompt or "world").lower())[:40].strip("-") or "world"}
    ref = bpy.path.abspath(s.ref_image).strip() if s.ref_image.strip() else ""
    if ref:
        if not os.path.isfile(ref):
            return "Reference image not found: " + ref
        if not ref.lower().endswith((".png", ".jpg", ".jpeg")):
            return "Reference image must be a .png or .jpg file"
    cfg["ref_image"] = ref
    cfg["assets"] = bool(s.use_assets)
    cfg["pp_key"] = polypizza_key(prefs)
    if cfg["assets"] and s.style != "REALISTIC" and not cfg["pp_key"]:
        cfg["assets"] = False
        log("asset import off — no Poly Pizza key (prefs or POLYPIZZA_API_KEY in .env)")
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


def shot_cfg(context, task_text, need_key=True):
    """Main thread: build the shot cfg dict from settings. Returns (cfg, err) — err is a user message.
    need_key=False skips the backend checks for LLM-free work (rerenders)."""
    s = context.scene.world_builder
    prefs = context.preferences.addons[__name__].preferences
    res = RESOLUTIONS[s.resolution]
    root, render_dir, _ = get_dirs(prefs)
    cfg = {"model": s.model, "custom_model": s.custom_model, "reasoning": s.reasoning,
           "passes": s.vision_passes, "resolution": res, "style": s.style, "detail": s.detail,
           "mode": s.build_mode, "extra": s.extra,
           "claude_model": s.claude_model, "claude_bin": prefs.claude_path,
           "project_dir": root, "render_dir": render_dir,
           "duration": s.shot_duration, "fps": int(s.shot_fps), "final_quality": s.shot_final,
           "multicut": s.shot_multicut, "multicut_n": s.shot_cuts,
           "multicam": s.shot_multicam, "multicam_n": s.shot_cams, "key": None,
           "slug": re.sub(r"[^a-z0-9]+", "-", task_text.lower())[:40].strip("-") or "shot"}
    if not need_key:
        return cfg, None
    if s.model == "CLAUDE_CODE":
        if not os.path.exists(prefs.claude_path):
            return None, "claude CLI not found — set its path in Add-on Preferences"
        cfg["exec_helper"] = ensure_exec_helper(root)
    else:
        cfg["key"] = api_key(prefs)
        if not cfg["key"]:
            return None, "No API key — set it in Add-on Preferences or the .env file"
    return cfg, None


def start_shot(context, task_text):
    """Main thread: capture settings and launch a shot worker on the current scene."""
    cfg, err = shot_cfg(context, task_text)
    if err:
        return err
    state.update(running=True, cancel=False, log=[], status="starting shot...", record_done=False)
    threading.Thread(target=worker_shot, args=(task_text, cfg["key"], cfg), daemon=True).start()
    bpy.app.timers.register(pump, first_interval=0.2)
    return None


def start_film(context, task_text):
    """Main thread: launch the film worker (plan -> batch-shoot -> edit)."""
    cfg, err = shot_cfg(context, task_text)
    if err:
        return err
    state.update(running=True, cancel=False, log=[], status="starting film...",
                 record_done=False, shots=[], film_brief=None, last_film=None)
    threading.Thread(target=worker_film, args=(task_text, cfg["key"], cfg), daemon=True).start()
    bpy.app.timers.register(pump, first_interval=0.2)
    return None


def start_retake(context, ix, note):
    """Main thread: launch a retake of state['shots'][ix]."""
    if not (0 <= ix < len(state["shots"])):
        return f"No shot {ix + 1} — the last run recorded {len(state['shots'])} shot(s)"
    cfg, err = shot_cfg(context, state["shots"][ix]["prompt"])
    if err:
        return err
    state.update(running=True, cancel=False, status="starting retake...", record_done=False)
    threading.Thread(target=worker_retake, args=(ix, note, cfg["key"], cfg), daemon=True).start()
    bpy.app.timers.register(pump, first_interval=0.2)
    return None


def start_rerender(context, ix):
    """Main thread: re-record take ix with its saved camera move — no LLM involved."""
    if not (0 <= ix < len(state["shots"])):
        return f"No shot {ix + 1} — the last run recorded {len(state['shots'])} shot(s)"
    cfg, err = shot_cfg(context, state["shots"][ix]["name"], need_key=False)
    if err:
        return err
    state.update(running=True, cancel=False, status="starting rerender...", record_done=False)
    threading.Thread(target=worker_rerender, args=(ix, cfg), daemon=True).start()
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
        if context.scene.world_builder.build_mode == "ADD":
            return self.execute(context)  # additive builds don't destroy anything
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.world_builder
        if not s.prompt.strip():
            self.report({'ERROR'}, "Type a world description first")
            return {'CANCELLED'}
        if s.build_mode != "ADD" and s.backup and len(context.scene.objects) > 0:
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


class WB_OT_film(bpy.types.Operator):
    bl_idname = "world_builder.film"
    bl_label = "Film Sequence"
    bl_description = ("Film Director plans 2-6 shots for this request, each is keyframed and recorded "
                      "as its own take, then the takes are hard-cut together into one MP4. "
                      "Duration = total film length; multi-cut/multi-cam are ignored per take")

    @classmethod
    def poll(cls, context):
        return not state["running"]

    def execute(self, context):
        s = context.scene.world_builder
        if not s.shot_prompt.strip():
            self.report({'ERROR'}, "Describe the film first (subject + mood), e.g. 'dramatic volcano reveal'")
            return {'CANCELLED'}
        err = start_film(context, s.shot_prompt.strip())
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        return {'FINISHED'}


class WB_OT_retake(bpy.types.Operator):
    bl_idname = "world_builder.retake"
    bl_label = "Retake Shot"
    bl_description = ("Re-shoot one take from scratch with your note applied "
                      "(the shot rig is cleared first), then re-cut the film")

    @classmethod
    def poll(cls, context):
        return not state["running"] and bool(state["shots"])

    def execute(self, context):
        s = context.scene.world_builder
        if not s.retake_note.strip():
            self.report({'ERROR'}, "Type a director's note first, e.g. 'slower, wider at the end'")
            return {'CANCELLED'}
        err = start_retake(context, s.retake_index - 1, s.retake_note.strip())
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        s.retake_note = ""
        return {'FINISHED'}


class WB_OT_rerender(bpy.types.Operator):
    bl_idname = "world_builder.rerender"
    bl_label = "Rerender Take"
    bl_description = ("Re-record this take with the exact same camera move on the current scene "
                      "and replace its video — no AI replanning; use after fixing the world")

    index: bpy.props.IntProperty(default=0, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return not state["running"] and bool(state["shots"])

    def execute(self, context):
        err = start_rerender(context, self.index)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        return {'FINISHED'}


def do_clear_rig(scene):
    """Main thread: remove shot markers/cameras/keys, restore one static camera. Returns count removed."""
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
    return removed


class WB_OT_clear_rig(bpy.types.Operator):
    bl_idname = "world_builder.clear_shot_rig"
    bl_label = "Clear Shot Rig"
    bl_description = ("Remove shot markers and shot cameras (ShotCam / Cam_*), clear camera animation, "
                      "and restore a single static camera")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        removed = do_clear_rig(context.scene)
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


# ------------------------------------------------------------ prompt bar overlay

try:
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:  # pytest fake-bpy environment / very old builds
    blf = gpu = batch_for_shader = None

OV_MODES = (("BUILD", "Build"), ("REFINE", "Refine"), ("SHOT", "Shot"), ("FILM", "Film"))
OV_PROP = {"BUILD": "prompt", "REFINE": "refine_text", "SHOT": "shot_prompt", "FILM": "shot_prompt"}
OV_PH = {"BUILD": "Describe a world to build…", "REFINE": "Give feedback on the built world…",
         "SHOT": "Describe one camera move…", "FILM": "Describe the film — subject + mood…"}
OV_NEON = (0.83, 0.95, 0.18, 1.0)

ov = {"active": False, "close": False, "mode": "BUILD", "caret": 0, "hover": None,
      "area": None, "region": None, "rects": {}}


def _fan(center, ring, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'TRI_FAN', {"pos": [center] + ring + [ring[0]]}).draw(shader)


def _fill_rr(x, y, w, h, r, color, segs=7):
    """Filled rounded rect via a triangle fan from the centroid."""
    r = min(r, w / 2, h / 2)
    ring = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                       (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(segs + 1):
            a = math.radians(a0 + 90 * i / segs)
            ring.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _fan((x + w / 2, y + h / 2), ring, color)


def _star(cx, cy, r, color):
    ring = []
    for i in range(8):
        rad = r if i % 2 == 0 else r * 0.36
        a = math.radians(90 + i * 45)
        ring.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    _fan((cx, cy), ring, color)


def _wrap_px(f, txt, max_w):
    """Greedy word-wrap by measured pixel width -> [(start, end, substring)].

    ponytail: O(n^2) blf measuring — prompts are a few hundred chars, fine.
    """
    lines, start = [], 0
    while start <= len(txt):
        end, last_space = start, -1
        while end < len(txt):
            if blf.dimensions(f, txt[start:end + 1])[0] > max_w:
                break
            if txt[end] == " ":
                last_space = end
            end += 1
        if end >= len(txt):
            lines.append((start, len(txt), txt[start:]))
            break
        cut = last_space + 1 if last_space >= start else (end if end > start else start + 1)
        lines.append((start, cut, txt[start:cut]))
        start = cut
    return lines or [(0, 0, "")]


def draw_overlay():
    ctx = bpy.context
    if not ov["active"] or ctx.region != ov["region"]:
        return
    region, s = ctx.region, ctx.scene.world_builder
    running = state["running"]
    ui = ctx.preferences.system.ui_scale
    f, fs = 0, int(14 * ui)
    blf.size(f, fs)
    line_h = int(fs * 1.55)
    pad = int(14 * ui)
    pill_w, pill_h = int(72 * ui), int(40 * ui)
    bar_w = int(min(660 * ui, region.width - 40 * ui))
    text_w = bar_w - 2 * pad - pill_w - int(12 * ui)
    txt = getattr(s, OV_PROP[ov["mode"]])
    lines = _wrap_px(f, txt, text_w)
    shown = max(3, min(4, len(lines)))
    bar_h = 2 * pad + shown * line_h
    bar_x = (region.width - bar_w) // 2
    bar_y = int(46 * ui)
    gpu.state.blend_set('ALPHA')

    _fill_rr(bar_x, bar_y, bar_w, bar_h, int(17 * ui), (0.075, 0.075, 0.082, 0.96))
    ov["rects"]["bar"] = (bar_x, bar_y, bar_w, bar_h)

    tx0, ty0 = bar_x + pad, bar_y + bar_h - pad - fs
    if running:
        mins, secs = divmod(int(time.time() - state["started"]), 60)
        blf.color(f, 0.9, 0.9, 0.9, 1)
        blf.position(f, tx0, ty0, 0)
        blf.draw(f, f"Working · {mins}:{secs:02d}")
        blf.color(f, 0.55, 0.55, 0.55, 1)
        blf.position(f, tx0, ty0 - line_h, 0)
        blf.draw(f, state["status"][:70])
    elif not txt:
        blf.color(f, 0.48, 0.48, 0.5, 1)
        blf.position(f, tx0, ty0, 0)
        blf.draw(f, OV_PH[ov["mode"]])
    else:
        caret = min(ov["caret"], len(txt))
        li = next((i for i, (a, b, _) in enumerate(lines) if a <= caret <= b), len(lines) - 1)
        w0 = min(max(0, li - shown + 1), max(0, len(lines) - shown))
        blf.color(f, 0.93, 0.93, 0.93, 1)
        for row, (a, b, sub) in enumerate(lines[w0:w0 + shown]):
            blf.position(f, tx0, ty0 - row * line_h, 0)
            blf.draw(f, sub)
        if (time.time() % 1.2) < 0.75 and w0 <= li < w0 + shown:
            a, b, sub = lines[li]
            cx = tx0 + blf.dimensions(f, sub[:caret - a])[0]
            cy = ty0 - (li - w0) * line_h
            _fill_rr(cx + 1, cy - int(3 * ui), max(2, int(1.6 * ui)), line_h - int(4 * ui), 1, (0.95, 0.95, 0.95, 1))

    px = bar_x + bar_w - pad - pill_w
    py = bar_y + (bar_h - pill_h) // 2
    hover_gen = ov["hover"] == "gen"
    if running:
        _fill_rr(px, py, pill_w, pill_h, pill_h / 2, (0.78, 0.25, 0.25, 1) if not hover_gen else (0.88, 0.32, 0.32, 1))
        sq = int(11 * ui)
        _fill_rr(px + pill_w / 2 - sq / 2, py + pill_h / 2 - sq / 2, sq, sq, int(2 * ui), (0.98, 0.93, 0.93, 1))
    else:
        c = OV_NEON if not hover_gen else (0.9, 1.0, 0.32, 1.0)
        _fill_rr(px, py, pill_w, pill_h, pill_h / 2, c)
        _star(px + pill_w / 2, py + pill_h / 2, int(11 * ui), (0.06, 0.06, 0.05, 1))
    ov["rects"]["gen"] = (px, py, pill_w, pill_h)

    tab_y, th = bar_y + bar_h + int(10 * ui), int(30 * ui)
    tfs = int(12.5 * ui)
    blf.size(f, tfs)
    widths = [int(blf.dimensions(f, label)[0]) + int(30 * ui) for _, label in OV_MODES]
    tx = (region.width - sum(widths) - int(8 * ui) * (len(OV_MODES) - 1)) // 2
    for (mode_id, label), tw in zip(OV_MODES, widths):
        active = mode_id == ov["mode"]
        hov = ov["hover"] == "tab:" + mode_id
        bg = (0.19, 0.19, 0.2, 1) if active else (0.1, 0.1, 0.11, 0.93) if hov else (0.06, 0.06, 0.066, 0.9)
        _fill_rr(tx, tab_y, tw, th, th / 2, bg)
        blf.color(f, *((0.97, 0.97, 0.97, 1) if active else (0.68, 0.68, 0.68, 1)))
        blf.position(f, tx + int(15 * ui), tab_y + (th - tfs) / 2 + int(1 * ui), 0)
        blf.draw(f, label)
        ov["rects"]["tab:" + mode_id] = (tx, tab_y, tw, th)
        tx += tw + int(8 * ui)
    gpu.state.blend_set('NONE')


class WB_OT_overlay(bpy.types.Operator):
    bl_idname = "world_builder.overlay"
    bl_label = "Backlot Bar"
    bl_description = "Floating prompt bar in the viewport — Build / Refine / Shot / Film (Ctrl+Shift+P)"

    _handle = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _hit(self, mx, my):
        for name, (x, y, w, h) in ov["rects"].items():
            if x <= mx <= x + w and y <= my <= y + h:
                return name
        return None

    def invoke(self, context, event):
        if gpu is None or bpy.app.background:
            return bpy.ops.world_builder.palette('INVOKE_DEFAULT')
        if ov["active"]:  # second Ctrl+Shift+P toggles the open bar closed
            ov["close"] = True
            return {'CANCELLED'}
        region = next(r for r in context.area.regions if r.type == 'WINDOW')
        s = context.scene.world_builder
        ov.update(active=True, close=False, hover=None, rects={},
                  area=context.area, region=region,
                  caret=len(getattr(s, OV_PROP[ov["mode"]])))
        WB_OT_overlay._handle = bpy.types.SpaceView3D.draw_handler_add(draw_overlay, (), 'WINDOW', 'POST_PIXEL')
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if WB_OT_overlay._handle:
            bpy.types.SpaceView3D.draw_handler_remove(WB_OT_overlay._handle, 'WINDOW')
            WB_OT_overlay._handle = None
        if getattr(self, "_timer", None):
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        ov.update(active=False, close=False, rects={}, hover=None)
        try:
            ov["area"].tag_redraw()
        except (AttributeError, ReferenceError):
            pass
        return {'CANCELLED'}

    def _generate(self, context):
        op = {"BUILD": bpy.ops.world_builder.build,
              "REFINE": bpy.ops.world_builder.refine,
              "SHOT": bpy.ops.world_builder.shot,
              "FILM": bpy.ops.world_builder.film}[ov["mode"]]
        try:
            op('INVOKE_DEFAULT')
        except RuntimeError as e:
            self.report({'ERROR'}, str(e).strip().split("\n")[-1])

    def _edit(self, context, event):
        s = context.scene.world_builder
        prop = OV_PROP[ov["mode"]]
        txt = getattr(s, prop)
        i = min(ov["caret"], len(txt))
        k, uni = event.type, event.unicode
        ctrl = event.ctrl or event.oskey
        if k == 'BACK_SPACE' and i > 0:
            txt, i = txt[:i - 1] + txt[i:], i - 1
        elif k == 'DEL' and i < len(txt):
            txt = txt[:i] + txt[i + 1:]
        elif k == 'LEFT':
            i = max(0, i - 1)
        elif k == 'RIGHT':
            i = min(len(txt), i + 1)
        elif k == 'HOME':
            i = 0
        elif k == 'END':
            i = len(txt)
        elif ctrl and k == 'V':
            clip = context.window_manager.clipboard.replace("\r", "").replace("\n", " ")
            txt, i = txt[:i] + clip + txt[i:], i + len(clip)
        elif ctrl and k == 'C':
            context.window_manager.clipboard = txt
        elif uni and uni.isprintable() and not ctrl:
            txt, i = txt[:i] + uni + txt[i:], i + len(uni)
        else:
            return False
        if txt != getattr(s, prop):
            setattr(s, prop, txt)
        ov["caret"] = i
        return True

    def modal(self, context, event):
        if not ov["active"] or ov["close"]:
            return self._finish(context)
        if event.type == 'TIMER':
            try:
                ov["area"].tag_redraw()
            except (AttributeError, ReferenceError):
                return self._finish(context)
            return {'RUNNING_MODAL'}
        region = ov["region"]
        mx, my = event.mouse_x - region.x, event.mouse_y - region.y
        inside = 0 <= mx <= region.width and 0 <= my <= region.height
        if not inside:  # let the user work in other areas/editors untouched
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            hov = self._hit(mx, my)
            if hov != ov["hover"]:
                ov["hover"] = hov
                ov["area"].tag_redraw()
            return {'PASS_THROUGH'}
        if event.type in ('MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'):
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = self._hit(mx, my)
            if hit is None:
                self._finish(context)
                return {'PASS_THROUGH'}
            if hit.startswith("tab:"):
                ov["mode"] = hit[4:]
                s = context.scene.world_builder
                ov["caret"] = len(getattr(s, OV_PROP[ov["mode"]]))
            elif hit == "gen":
                if state["running"]:
                    bpy.ops.world_builder.cancel()
                else:
                    self._generate(context)
            ov["area"].tag_redraw()
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type not in ('LEFTMOUSE', 'RIGHTMOUSE'):
            if event.type == 'ESC':
                return self._finish(context)
            if event.type in ('RET', 'NUMPAD_ENTER'):
                if not state["running"]:
                    self._generate(context)
                ov["area"].tag_redraw()
                return {'RUNNING_MODAL'}
            if not state["running"] and self._edit(context, event):
                ov["area"].tag_redraw()
            return {'RUNNING_MODAL'}  # keys are the bar's while the mouse is over the viewport
        return {'PASS_THROUGH'}


# ------------------------------------------------------------ UI

def prompt_block(layout, s, prop, placeholder, wrap=38):
    """Single-line input + a 3-4 line 'page' box under it: live wrapped text,
    or a dim hint when empty.

    ponytail: Blender has no multiline string widget and a scale_y-stretched
    field renders broken (top-anchored text in a huge box), so the box below
    the input is the multi-line surface (TEXTEDIT_UPDATE keeps it live).
    """
    col = layout.column(align=True)
    col.prop(s, prop, text="", icon='GREASEPENCIL', placeholder=placeholder)
    box = col.box().column(align=True)
    box.scale_y = 0.85
    txt = getattr(s, prop)
    if txt:
        lines = textwrap.wrap(txt, wrap)
        for line in lines[:4]:
            box.label(text=line)
        if len(lines) > 4:
            box.label(text="…")
        pad = 3 - min(len(lines), 4)
    else:
        box.active = False
        box.label(text=placeholder)
        pad = 2
    for _ in range(max(0, pad)):
        box.label(text="")


class WB_OT_palette(bpy.types.Operator):
    bl_idname = "world_builder.palette"
    bl_label = "Backlot Prompt"
    bl_description = "Prompt dialog — pick an action, type, Generate (fallback for the Backlot Bar overlay)"

    mode: bpy.props.EnumProperty(
        name="Action", default="BUILD",
        items=[("BUILD", "Build", "Build a world from the prompt"),
               ("REFINE", "Refine", "Send feedback about the built world"),
               ("SHOT", "Shot", "Program & record one camera shot"),
               ("FILM", "Film", "Plan and shoot a multi-shot film")])

    @classmethod
    def poll(cls, context):
        return not state["running"]

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=480, confirm_text="Generate")

    def draw(self, context):
        s = context.scene.world_builder
        layout = self.layout
        row = layout.row()
        row.prop(self, "mode", expand=True)
        prop, ph = {"BUILD": ("prompt", "a cozy medieval village at dusk"),
                    "REFINE": ("refine_text", "raise the camera, add more trees"),
                    "SHOT": ("shot_prompt", "slow 360 orbit, gently descending"),
                    "FILM": ("shot_prompt", "dramatic volcano reveal at dusk")}[self.mode]
        prompt_block(layout, s, prop, ph, wrap=68)
        if self.mode == "REFINE" and not state["can_refine"]:
            layout.label(text="Nothing to refine yet — build a world first", icon='ERROR')

    def execute(self, context):
        op = {"BUILD": bpy.ops.world_builder.build,
              "REFINE": bpy.ops.world_builder.refine,
              "SHOT": bpy.ops.world_builder.shot,
              "FILM": bpy.ops.world_builder.film}[self.mode]
        try:
            op('INVOKE_DEFAULT')
        except RuntimeError as e:
            self.report({'ERROR'}, str(e).strip().split("\n")[-1])
            return {'CANCELLED'}
        return {'FINISHED'}


class WB_PT_panel(bpy.types.Panel):
    bl_idname = "WB_PT_panel"
    bl_label = "World Builder"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"

    def draw_header(self, context):
        self.layout.label(text="", icon='WORLD_DATA')

    def draw_header_preset(self, context):
        self.layout.operator("world_builder.overlay", text="", icon='WINDOW', emboss=False)

    def draw(self, context):
        s = context.scene.world_builder
        layout = self.layout
        col = layout.column()
        prompt_block(col, s, "prompt", "a cozy medieval village at dusk",
                     wrap=max(26, int(context.region.width / 7.8)))
        row = col.row(align=True)
        row.prop(s, "style", text="")
        row.prop(s, "detail", text="")

        header, body = layout.panel("wb_build_options", default_closed=True)
        header.label(text="Build Options", icon='OPTIONS')
        if body:
            bcol = body.column()
            bcol.prop(s, "build_mode", text="")
            bcol.prop(s, "use_assets")
            bcol.prop(s, "extra", text="", icon='TEXT',
                      placeholder="night time, no cacti, add a river")
            bcol.prop(s, "ref_image", text="", icon='IMAGE_DATA',
                      placeholder="reference image (optional)")

        layout.separator()
        if state["running"]:
            row = layout.row()
            row.scale_y = 1.3
            row.alert = True
            row.operator("world_builder.cancel", icon='X')
            mins, secs = divmod(int(time.time() - state["started"]), 60)
            box = layout.box().column(align=True)
            box.label(text=f"Working · {mins}:{secs:02d}", icon='SORTTIME')
            box.label(text=state["status"][:52])
        else:
            row = layout.row()
            row.scale_y = 1.3
            row.operator("world_builder.build", text="Build World", icon='PLAY')
            layout.label(text=state["status"][:52], icon='INFO')

        if state["log"]:
            header, body = layout.panel("wb_activity", default_closed=False)
            header.label(text="Activity", icon='CONSOLE')
            if body:
                box = body.box().column(align=True)
                box.scale_y = 0.8
                for line in state["log"][-12:]:
                    box.label(text=line[:55])

        if state["can_refine"] and not state["running"]:
            header, body = layout.panel("wb_refine", default_closed=False)
            header.label(text="Refine the World", icon='MODIFIER')
            if body:
                bcol = body.column(align=True)
                bcol.prop(s, "refine_text", text="",
                          placeholder="raise the camera, add more trees")
                bcol.operator("world_builder.refine", text="Apply Feedback", icon='CHECKMARK')

        u = state["usage"]
        if u["prompt"]:
            cost = f" · ${state['cost']:.4f}" if state["cost"] else ""
            row = layout.row()
            row.active = False
            row.alignment = 'RIGHT'
            row.label(text=f"{u['prompt']:,} in / {u['completion']:,} out{cost}")


class WB_PT_shot(bpy.types.Panel):
    bl_idname = "WB_PT_shot"
    bl_label = "Camera & Film"
    bl_parent_id = "WB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"

    def draw_header(self, context):
        self.layout.label(text="", icon='CAMERA_DATA')

    def draw(self, context):
        s = context.scene.world_builder
        layout = self.layout
        col = layout.column()
        prompt_block(col, s, "shot_prompt", "slow 360 orbit, gently descending",
                     wrap=max(26, int(context.region.width / 7.8)))
        row = col.row(align=True)
        row.prop(s, "shot_duration")
        row.prop(s, "shot_fps", text="")

        header, body = layout.panel("wb_cinematography", default_closed=True)
        header.label(text="Cinematography", icon='SEQ_SEQUENCER')
        if body:
            bcol = body.column()
            row = bcol.row(align=True)
            row.prop(s, "shot_multicut")
            sub = row.row(align=True)
            sub.active = s.shot_multicut
            sub.prop(s, "shot_cuts", text="")
            row = bcol.row(align=True)
            row.prop(s, "shot_multicam")
            sub = row.row(align=True)
            sub.active = s.shot_multicam
            sub.prop(s, "shot_cams", text="")
            bcol.prop(s, "shot_final")

        acts = layout.column(align=True)
        acts.scale_y = 1.25
        acts.operator("world_builder.shot", text="Record Shot", icon='RENDER_ANIMATION')
        acts.operator("world_builder.film", icon='SEQUENCE')
        layout.operator("world_builder.clear_shot_rig", icon='TRASH')

        if state["shots"] and not state["running"]:
            header, body = layout.panel("wb_takes", default_closed=False)
            header.label(text=f"Takes ({len(state['shots'])})", icon='SEQ_STRIP_DUPLICATE')
            if body:
                box = body.box().column(align=True)
                box.scale_y = 0.9
                for i, sh in enumerate(state["shots"]):
                    row = box.row(align=True)
                    row.label(text=f"{i + 1:02d}  {sh['name'][:24]}",
                              icon='CHECKMARK' if sh.get('path') else 'ERROR')
                    if sh.get("path"):
                        row.operator("world_builder.rerender", text="",
                                     icon='RENDER_ANIMATION').index = i
                bcol = body.column(align=True)
                row = bcol.row(align=True)
                row.prop(s, "retake_index")
                row.prop(s, "retake_note", text="",
                         placeholder="slower, keep the tower in frame")
                bcol.operator("world_builder.retake", icon='FILE_REFRESH')

        row = layout.row()
        row.active = False
        row.label(text="Records MP4 at the Settings resolution", icon='INFO')


class WB_PT_settings(bpy.types.Panel):
    bl_idname = "WB_PT_settings"
    bl_label = "Settings"
    bl_parent_id = "WB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "World Builder"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='PREFERENCES')

    def draw(self, context):
        s = context.scene.world_builder
        layout = self.layout

        header, body = layout.panel("wb_set_ai", default_closed=False)
        header.label(text="AI Model", icon='EXPERIMENTAL')
        if body:
            body.use_property_split = True
            body.use_property_decorate = False
            body.prop(s, "model", text="Backend")
            if s.model == "CUSTOM":
                body.prop(s, "custom_model", text="Model ID",
                          placeholder="anthropic/claude-sonnet-5")
            if s.model == "CLAUDE_CODE":
                body.prop(s, "claude_model")
            else:
                body.prop(s, "reasoning")
            body.prop(s, "vision_passes", text="Vision Passes")

        header, body = layout.panel("wb_set_output", default_closed=False)
        header.label(text="Output & Files", icon='OUTPUT')
        if body:
            body.use_property_split = True
            body.use_property_decorate = False
            body.prop(s, "resolution")
            body.prop(s, "backup", text="Backup Scene")
            prefs = context.preferences.addons[__name__].preferences
            body.prop(prefs, "project_dir", text="Save Folder")
            row = body.row(align=True)
            row.use_property_split = False
            row.operator("world_builder.open_renders", icon='FILE_FOLDER')
            row.operator("world_builder.save_world", icon='FILE_BLEND')


class WBSettings(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="World prompt", default="", options={'TEXTEDIT_UPDATE'},
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
    build_mode: bpy.props.EnumProperty(
        name="Mode", default="REPLACE",
        items=[("REPLACE", "New World", "Clear the scene and build fresh from the prompt"),
               ("ADD", "Add to Scene", "Build new content into the existing scene, keeping everything"),
               ("REMASTER", "Remaster Scene",
                "Study the existing scene (inventory + render) and upgrade it in place to the chosen "
                "style and detail — e.g. turn a low-poly draft into a detailed version")])
    extra: bpy.props.StringProperty(
        name="Extra instructions", default="",
        description="Optional extra requirements, e.g. 'night time, no cacti, add a river'")
    ref_image: bpy.props.StringProperty(
        name="Reference image", default="", subtype='FILE_PATH',
        description="Optional reference photo (.png/.jpg) — the model identifies its objects, "
                    "layout, and mood and builds the scene to match, guided by the prompt")
    use_assets: bpy.props.BoolProperty(
        name="Import CC0 assets", default=False,
        description="Let the model import real CC0 props: Kenney/Quaternius low-poly packs via "
                    "Poly Pizza (needs a free key) for Low Poly/Stylized, PolyHaven photoscans "
                    "for Realistic")
    refine_text: bpy.props.StringProperty(
        name="Refine", default="",
        description="Feedback for the built world, e.g. 'raise the camera and add more trees'")
    shot_prompt: bpy.props.StringProperty(
        name="Motion", default="", options={'TEXTEDIT_UPDATE'},
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
    retake_index: bpy.props.IntProperty(
        name="Shot #", default=1, min=1, max=8,
        description="Which shot of the last run to retake (1 = first)")
    retake_note: bpy.props.StringProperty(
        name="Note", default="",
        description="Director's note for the retake, e.g. 'slower, keep the tower in frame'")
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
        items=[("R720", "1280 × 720", "16:9 HD"), ("R1080", "1920 × 1080", "16:9 Full HD"),
               ("SQUARE", "1080 × 1080", "1:1 square"),
               ("VERT916", "1080 × 1920", "9:16 vertical — Reels/Shorts/TikTok"),
               ("UW219", "2560 × 1080", "21:9 ultrawide — cinematic")])
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
    polypizza_key: bpy.props.StringProperty(
        name="Poly Pizza API Key", subtype='PASSWORD',
        description="Free key from poly.pizza/api for low-poly CC0 assets (Kenney, Quaternius). "
                    "Leave empty to use the POLYPIZZA_API_KEY env var or the .env file")
    env_path: bpy.props.StringProperty(
        name=".env path", subtype='FILE_PATH', default="",
        description="Optional extra .env; <project folder>/.env and ~/.config/worldbuilder/.env "
                    "are always checked as fallbacks")
    claude_path: bpy.props.StringProperty(
        name="claude CLI path", subtype='FILE_PATH', default=_find_claude())

    def draw(self, context):
        self.layout.prop(self, "project_dir")
        self.layout.prop(self, "api_key")
        self.layout.prop(self, "polypizza_key")
        self.layout.prop(self, "env_path")
        self.layout.prop(self, "claude_path")


classes = (WBSettings, WB_OT_build, WB_OT_refine, WB_OT_shot, WB_OT_film, WB_OT_retake, WB_OT_rerender,
           WB_OT_clear_rig,
           WB_OT_cancel, WB_OT_open_renders, WB_OT_save_world, WB_OT_palette, WB_OT_overlay,
           WB_PT_panel, WB_PT_shot, WB_PT_settings, WB_prefs)

addon_keymaps = []


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.world_builder = bpy.props.PointerProperty(type=WBSettings)
    kc = getattr(bpy.context.window_manager, "keyconfigs", None)
    if kc and kc.addon:  # headless/background Blender has no addon keyconfig
        km = kc.addon.keymaps.new(name="3D View", space_type='VIEW_3D')
        kmi = km.keymap_items.new("world_builder.overlay", 'P', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))


def unregister():
    if WB_OT_overlay._handle:  # addon disabled while the bar was open
        bpy.types.SpaceView3D.draw_handler_remove(WB_OT_overlay._handle, 'WINDOW')
        WB_OT_overlay._handle = None
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    del bpy.types.Scene.world_builder
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
