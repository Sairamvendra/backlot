#!/usr/bin/env python3
"""LLM builds 3D worlds in the running Blender via the Lab MCP socket (localhost:9876).

Usage:
  python3 orchestrator.py "a cozy medieval village at dusk"
  python3 orchestrator.py --check        # verify Blender socket + API key

Key: export OPENROUTER_API_KEY, or a line `OPENROUTER_API_KEY=...` in .env next to this file.
"""
import json
import os
import re
import socket
import sys
import time
import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports")
import requests

MODEL = "z-ai/glm-5.3-flash"  # was stealth/ox-alpha; stealth period ended, this is the revealed model
MAX_TURNS = 40
DIR = os.path.dirname(os.path.abspath(__file__))

SYSTEM = """You are a 3D artist building a world in a live Blender session via the run_blender tool.

Build incrementally, one logical group per call, 6-12 calls for a full scene:
1. clear the default scene, then ground/terrain
2+. structures and props, one group per call (all buildings, then all trees, then props...)
then lighting, then camera last.

Rules for every call:
- bpy is available; code runs on Blender's main thread. Keep each call under ~80 lines.
- ALWAYS set `result` to a small JSON-serializable dict: what you created (names, counts, rough positions).
- Prefer bpy.data over bpy.ops where practical; ops that need UI context fail here.
- Put each group in its own collection. Ground is at z=0; use sensible real-world scale (a house is 4-6m).
- Vary duplicated objects (rotation, scale, position jitter) so nothing looks copy-pasted, and place
  objects so they don't intersect each other.
- Style: clean low-poly. Principled BSDF materials with distinct base colors; no image textures.
- Lighting: one sun matched to the requested mood, plus a world background color that fits.
- Camera: name it 'Camera', set scene.camera, frame the WHOLE scene from a pleasing 3/4 elevated angle.
- If you get a traceback back, fix that step and re-run it before moving on.

When the world is complete reply with plain text only: DONE: <one-line summary>. No tool call."""

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

# ponytail: camera fallback only fires if the model forgot one; engine is already EEVEE on Blender 5.1
RENDER_CODE = """
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
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.filepath = __PATH__
bpy.ops.render.render(write_still=True)
result = {"render": __PATH__, "objects": len(scene.objects)}
"""


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    env_file = os.path.join(DIR, ".env")
    if not key and os.path.exists(env_file):
        for line in open(env_file):
            if line.strip().startswith("OPENROUTER_API_KEY"):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        sys.exit("No API key. Export OPENROUTER_API_KEY or put OPENROUTER_API_KEY=... in .env")
    return key


def blender(code):
    s = socket.create_connection(
        (os.environ.get("BLENDER_HOST", "localhost"), int(os.environ.get("BLENDER_PORT", 9876))),
        timeout=600)
    s.sendall(json.dumps({"type": "execute", "code": code, "strict_json": False}).encode() + b"\0")
    buf = b""
    while not buf.endswith(b"\0"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.rstrip(b"\0"))


def chat(messages, key):
    for attempt in range(3):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": MODEL, "messages": messages, "tools": TOOLS,
                      "reasoning": {"effort": "low"}},
                timeout=600)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.RequestException(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                sys.exit(f"API error {r.status_code}: {r.text[:300]}")
            return r.json()["choices"][0]["message"]
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"   retrying after: {e}")
            time.sleep(5 * (attempt + 1))


def run_code(code, step):
    print(f"  ▸ {step}")
    try:
        out = json.dumps(blender(code))
    except (OSError, ValueError) as e:
        out = f"ERROR: blender socket: {e}"
    print(f"    → {out[:200]}")
    return out[:8000]


def check():
    resp = blender('import bpy; result={"blender": bpy.app.version_string, "objects": len(bpy.data.objects)}')
    print("blender socket:", json.dumps(resp.get("result", resp)))
    api_key()
    print("api key: found")


def main():
    if sys.argv[1:] == ["--check"]:
        return check()
    prompt = " ".join(sys.argv[1:])
    if not prompt:
        sys.exit('usage: orchestrator.py "<world description>" | --check')
    key = api_key()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    nudges = 0
    for turn in range(1, MAX_TURNS + 1):
        raw = chat(messages, key)
        msg = {"role": "assistant", "content": raw.get("content"),
               **({"tool_calls": raw["tool_calls"]} if raw.get("tool_calls") else {})}
        messages.append(msg)
        content = (msg.get("content") or "").strip()
        if content:
            print(f"[{turn}] {content[:300]}")
        if msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                try:
                    args = json.loads(call["function"]["arguments"])
                    out = run_code(args["code"], args.get("step", "(no description)"))
                except (ValueError, KeyError) as e:
                    out = f"ERROR: bad tool arguments: {e}"
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": out})
            continue
        if content.upper().startswith("DONE"):
            break
        # ponytail: fallback for models without tool calling — run a fenced code block if present
        blocks = re.findall(r"```(?:python)?\n(.*?)```", content, re.S)
        if blocks:
            out = run_code(blocks[0], "(from fenced code block)")
            messages.append({"role": "user", "content": f"Execution result:\n{out}\nContinue, or reply DONE: <summary>."})
            continue
        nudges += 1
        if nudges > 2:
            print("model stopped building without DONE; ending run")
            break
        messages.append({"role": "user", "content": "Continue building with run_blender, or reply DONE: <summary> if finished."})

    os.makedirs(os.path.join(DIR, "renders"), exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-")
    path = os.path.join(DIR, "renders", f"{slug}-{int(time.time())}.png")
    print("rendering...")
    resp = blender(RENDER_CODE.replace("__PATH__", json.dumps(path)))
    print("render:", json.dumps(resp.get("result", resp)))


if __name__ == "__main__":
    main()
