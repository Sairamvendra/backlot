# Backlot

**Your AI film studio inside Blender** — describe a world, watch it build itself, then say "action."

Backlot is a Blender addon (4.2+ / 5.x) that builds, refines, and films 3D worlds from text prompts
using an LLM. (It registers in Blender's add-on list as **World Builder**.)

**Features**: prompt-to-world building with style/detail presets · **director brains**: a Creative
Director pass turns your prompt into an art-direction brief (mood, focal point, 60/30/10 palette,
lighting recipe, story prop clusters) and a Film Director pass turns motion requests into a shot plan
(sizes, angles, movements, lenses, per-cut frame ranges) before anything is built — both distilled from
film production design, concept art, level design, and cinematography practice · vision critique passes
(the model sees its own render and grades it against the brief) · iterative refine box · add-to-scene or
replace mode with auto-backup · editable scene structure (grouped objects, see below) · camera shots:
prompt-driven animation with duration/fps, multi-cut and multi-cam (marker-bound camera switching), fast
OpenGL viewport capture or full-quality render to MP4, one-click Clear Shot Rig · **Film Sequence
(v3.6)**: the Film Director plans 2–6 single-take shots, each is shot and recorded independently, then
hard-cut into one film in a kept `WB_Edit` VSE scene · **retakes (v3.6)**: re-shoot any one shot with a
director's note and the film re-cuts automatically · **CC0 asset import (v3.6, opt-in)**: real props
pulled in by style — Kenney/Quaternius low-poly packs via Poly Pizza, PolyHaven photoscans for Realistic ·
model backends: OpenRouter (default `z-ai/glm-5.3-flash`, any custom model ID, reasoning effort
selector) or local headless Claude Code (runs on your subscription).

## Install

1. Blender → Edit → Preferences → Add-ons → Install from Disk → `world_builder.py`, enable it.
2. Requires the Blender MCP socket addon listening on `localhost:9876` (the Claude Code backend talks
   to Blender through it; the OpenRouter backend runs fully in-process).
3. Panel appears in the 3D Viewport sidebar (N key) → **World Builder** tab.

## Configure (Add-on Preferences)

- **Project folder** — where `renders/`, `worlds/`, `steps/`, and `.env` live (default `~/Documents/WorldBuilder`).
- **OpenRouter API key** — paste it here, **or** export `OPENROUTER_API_KEY`, **or** put
  `OPENROUTER_API_KEY=...` in `<project folder>/.env`. Never commit `.env` (see `.gitignore`).
- **Poly Pizza API key** (optional) — free key from [poly.pizza/api](https://poly.pizza/api), only
  needed for CC0 asset import in Low Poly/Stylized styles; same three ways (`POLYPIZZA_API_KEY`).
- **claude CLI path** — auto-detected; only needed for the Claude Code backend.

## Scene structure: objects behave like layer folders

Every world is built for editing afterwards, Photoshop-layers style:

- Each compound object gets a **root empty** (`Barn_1`, `Tree_2`, `Cart_1`...) with its part meshes
  parented under it and named `<Root>_<part>` (`Barn_1_Door`, `Tree_2_Apple0`, `Cart_1_Wheel0_Spoke1`...).
  In the Outliner, click the ▸ triangle on a root to open its "folder".
- **Move the whole object**: select the root (Outliner row, or the axis-cross empty at its base in the
  viewport) and press G/R/S — all parts follow.
- **Edit one part**: click the part directly; parts are never joined into a single mesh.
- **Edit by prompt**: the naming makes surgical Refine requests work — e.g.
  *"make Barn_1's door dark blue and all of Tree_2's apples golden yellow"* changes exactly those meshes.
- Simple props (a hay bale, the ground) stay as plain single meshes with clear names.
- Replace-mode builds auto-remove empty leftover collections from previous worlds, so the Outliner
  stays clean.

## Camera shots

Describe a motion ("slow 360 orbit, descending", "three-camera coverage cutting between angles"), pick
duration and fps, and hit **Program & Record Shot**. Multi-cut and Multi-cam toggles take an optional
count (0 = the model chooses). Recording defaults to a fast OpenGL viewport capture in your current
shading; enable **Final quality render** for the full engine (slower; ESC in the render window stops it).
**Clear Shot Rig** removes shot cameras, markers, and camera animation afterwards, restoring one static
camera — undo-able.

## Film Sequence & retakes (v3.6)

Describe a film ("cinematic tour inside the spaceship, tense and quiet"), set the **total** length, and
hit **Film Sequence**. The Film Director plans 2–6 single-take shots (machine-readable shot list), each
take is keyframed and recorded on a clean rig, then the takes are hard-cut together in a new `WB_Edit`
scene and rendered to `<slug>-film-<ts>.mp4`. The `WB_Edit` scene stays in your .blend so you can re-trim
the cut by hand in the VSE. If the plan can't be parsed, the run falls back to the classic single-shot
behavior — you always get a video. A failed take is skipped, never fatal.

After a run, the panel shows the shot board (`01 corridor-push ✓ …`). Pick a shot number, type a
director's note ("slower, hold longer on the viewport"), and hit **Retake Shot** — that one take is
re-shot from scratch with your note as top priority and the film re-cuts automatically. Notes don't
accumulate across repeated retakes of the same shot, so write the full note each time. Sound is the
planned v3.7 follow-up.

## CC0 asset import (v3.6, opt-in)

Tick **Import CC0 assets** in the main panel and the builder gains an `import_asset` tool for complex
props (furniture, vehicles, barrels...) instead of modelling everything from primitives — terrain and
buildings stay procedural. Sources are routed by style, all CC0 (no attribution required, credited
anyway): **Low Poly / Stylized / Custom** → [Poly Pizza](https://poly.pizza) (Kenney, Quaternius, and
the Google Poly archive; needs the free key above — without it the toggle quietly turns itself off) ·
**Realistic** → [PolyHaven](https://polyhaven.com) photoscan models with 1k textures (no key). Downloads
are cached under `<project folder>/assets/` and imported as a collection under a root empty, so imported
props move like every other Backlot object. Credits: Kenney, Quaternius, Poly Haven.

## Notes

- The addon writes `wb_exec.py` (a small socket helper for the Claude Code backend) into the project folder.
- No API keys are stored in this file or in `.blend` files; keys live only in your preferences file,
  environment, or `.env`.

## License & credits

Created by **Sairam** ([GitHub](https://github.com/sairamvendra) ·
[LinkedIn](https://www.linkedin.com/in/sairamvendra/)). **Dual-licensed:**

- **Community**: **GPL-3.0-or-later** (see `LICENSE`) — free for everyone; build on it, keep the
  copyright notices intact, credit the original (`CITATION.cff` powers GitHub's "Cite this
  repository" button), and keep derivatives open source.
- **Commercial**: closed-source or proprietary use is available under a separate commercial license —
  see `LICENSE-COMMERCIAL.md` for how to inquire.

Contributors: see `CONTRIBUTING.md` — contributions are accepted under a grant that keeps the dual
licensing intact.
