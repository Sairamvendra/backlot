# Art Direction / Set Design / Environment Design — Research Corpus

Source material for Backlot's **Creative Director** brain (scene-brief pass). Gathered 2026-08-31 via four parallel deep-research passes. Rules are distilled and actionable by design — numbers in brackets are executable parameterizations of qualitative source guidance where the source gave none.

Companion doc for the **Film Director** brain (shot-brief pass): `CinemaForge_Camera_Framing_Research_v2.docx` (user-provided, shot sizes / angles / movements / genre presets).

---

## PART 1 — Composition & Focal Hierarchy (concept-art / environment design)

Sources: Feng Zhu (FZD School), *Framed Ink* (Marcos Mateu-Mestre), Neil Blevins (Soulburn), The Level Design Book, Mateusz Piaskiewicz "Composition in Level Design" (Game Developer), "Shaping Emotions: Shape Language in Level Design" (Game Developer), Felix Leyendecker (80.lv), *The Skillful Huntsman*, notan/Gurney sources, visualcomposing (tangents).

### A. Scene skeleton — size hierarchy (Big/Medium/Small)
- A1. Build every scene from exactly 3 size classes: ONE Big dominant mass, 2-4 Medium supporting masses, many Small accents. No two elements of near-equal size competing.
- A2. Make size steps obvious: Big ≥2-3x the height/bulk of Medium; Medium ≥2-3x Small. Smooth gradients read as noise; stepped jumps read as intentional.
- A3. 70/30 dominance: one visual family (hue, value range, shape motif) occupies ~70% of the scene; the contrasting accent gets ~30%. Never 50/50.
- A4. Apply B/M/S fractally: inside each cluster (village block, rock group) repeat one-large/few-medium/many-small.
- A5. One composition theme per view — a single dominant idea; never two competing "main events" in one frame.
- A6. Odd counts for similar objects: 3 or 5 trees/pillars/rocks, not 2 or 4.

### B. Focal point hierarchy
- B1. Exactly ONE primary focal structure per scene. Start the design from it. (Feng Zhu: "one focal point per set")
- B2. Visual weight ≈ contrast × size × isolation × meaning. Stack at least 3 of these on the focal; give background elements none.
- B3. Focal gets the scene's strongest VALUE contrast: lightest against dark surround, or darkest against light.
- B4. Reserve the brightest, most saturated color in the palette for the focal only.
- B5. Highest detail/object density at the focal; density decays with distance from it.
- B6. From the render camera, place the focal at a rule-of-thirds intersection — never dead center, never touching frame edge; clear margin between the dominant silhouette and the border.
- B7. Relative height sells dominance: keep the focal's neighbors at ~1/3-1/2 of its height within its zone.
- B8. The focal silhouette must not merge with other objects — isolate it against sky/haze/simple backdrop; nothing sprouting behind its apex.
- B9. 1-2 secondary focal points max, each clearly weaker (~half the primary's size/contrast), at other thirds positions.
- B10. Aim leading lines at the focal: roads, fences, shorelines, prop rows, light shafts converge on it.

### C. Shape language
- C1. Pick ONE shape motif per scene mood: round = safe/friendly/organic; square = stable/ordered/manmade; triangle/diagonal = danger/tension. Bias every major mass toward it.
- C2. Three shape tiers: primary = overall silhouette, secondary = structural forms (roofs, arches), tertiary = surface detail. All three echo the motif.
- C3. Line direction sets mood: horizontals = calm, verticals = awe/power, diagonals = agitation.
- C4. Objects leaning TOWARD camera/path = threatening; leaning AWAY = welcoming. 2-8° of tilt is enough.
- C5. Wide-base triangles read grounded; inverted/top-heavy forms read unstable; spike arrays read hostile.
- C6. Perfect grids read cold/mechanical; positional/rotational jitter reads organic. Order = safety, chaos = anxiety — mix to mood.
- C7. Landmark/interactive objects: rectangular, high-contrast, clean silhouettes. Background objects: rounder, lower contrast, silhouettes broken by overlap.
- C8. Design silhouette-first: block each key object so it's identifiable from silhouette alone before detailing.

### D. Depth layering (FG/MG/BG)
- D1. Three depth zones — foreground, midground, background; the focal usually lives in the MIDGROUND.
- D2. Default outdoor value scheme: DARK foreground, LIGHTER midground, LIGHTEST background (atmospheric haze).
- D3. Theatrical scheme (forests, ruins, interiors): dark FG, spot-lit MG, dark BG — stage-spotlight; suits god-rays.
- D4. Silhouette scheme: dark FG + dark MG against a light BG (backlight/sunset) — for drama and iconic reads.
- D5. Use 4-5 receding background planes (hill behind hill), each step lighter and less saturated — never one background mass.
- D6. Overlap is the strongest depth cue: every layer partially occludes the next.
- D7. Atmospheric perspective: near = warm, saturated, high contrast; far = cool, desaturated, low contrast. In Blender: distance fog/volume + muted BG materials.
- D8. Detail falloff by zone: FG full detail, MG medium, BG silhouette-level simple meshes.
- D9. Scale cues: place known-size objects (human 1.8m, door ~2m, cart, lamppost) at 2+ depth zones so big structures read big.
- D10. Dark FG elements at frame edges act as a natural frame ("viewer stands in the dark looking into the lit scene"); a near FG object 1.5-5m from camera anchors depth.

### E. Value + light structure
- E1. The whole scene must reduce to 2-4 flat value groups (notan). If a postage-stamp render doesn't read, fix value masses, not details.
- E2. Never light evenly: light the important, sink the unimportant into shadow.
- E3. One dominant light direction for the whole scene; accent/practical lights only at focal and secondaries.
- E4. Group values: keep lights connected to lights, darks to darks — no scattered equal spots of light.
- E5. Palette split ~70% dominant hue family / ~30% accent — commonly cool scene + warm accent at focal (or inverse).
- E6. Moving/emissive garnish (flags, smoke, dust shafts, embers) is a focal amplifier — ONLY near focal or the path to it.

### F. Object placement — repetition, rhythm, tangents
- F1. Repetition with variation: duplicates must differ in ≥3 of {scale ±10-30%, Z-rotation, tilt, hue/roughness}.
- F2. Cluster + gap rhythm: some objects nearly touching, then a large gap. Even spacing is the #1 amateur tell.
- F3. Scale progression along the eye path (small → medium → big toward focal) directs reading order.
- F4. Curved paths read gentle/natural; zigzag/angular reads risky/tense. Choose curvature by mood.
- F5. TANGENT CHECK from the render camera: no two silhouettes merely touching — overlap decisively or separate clearly.
- F6. Never let one object's edge touch another's apex/roofline; no pole/tree "growing" out of a hero object's top.
- F7. Don't align edges across depths (rooftop flush with horizon, rock edge continuing a building edge) — offset or move camera.
- F8. Frame cropping: fully inside with margin, or boldly cut past midpoint — never sliced exactly in half at the frame edge.
- F9. Every cluster must connect logically (path, terrain flow, shared ground) — no floating islands of stuff.

### G. Readability + detail budget
- G1. 70/30 detail rule: ~30% of the space carries ~70% of the detail; the rest stays calm.
- G2. Spend detail where the camera dwells: focal, thresholds, path ends, vista points.
- G3. Bring 3 hero assets to 100% instead of 30 assets to 60% — even distribution = "nothing memorable".
- G4. Detail must never break silhouettes: interest INSIDE the major shape read, never distorting its outline.
- G5. Rest areas are mandatory: large simple planes (wall, ground, water, sky) as negative space; up to 60-75% controlled emptiness makes a small subject iconic.
- G6. Distinct color zone per district/area works as navigation signage (blue harbor, red market).
- G7. Squint test: at thumbnail size the focal, 3 depth layers, and B/M/S must still read; else fix values/masses first.
- G8. Unity + one violation: keep everything coherent to the motif, then break the pattern exactly once — at the focal.

### H. Camera + framing (scene-side)
- H1. Horizon = camera eye level. Low horizon (bottom third) = structures loom, epic; high horizon (top third) = terrain emphasis. Never 50/50 by default.
- H2. Compose the SPACE first, the shot second: spatial hierarchy works from every angle; thirds/leading lines work from the chosen camera. Do both.
- H3. Shoot key structures from a 3/4 angle showing two faces; dead-frontal only for deliberate symmetry statements.
- H4. Scale drama: camera low (0.5-1.6m) + wide lens (24-35mm) makes the Big element tower; high/aerial shrinks the world to a diorama.
- H5. Wide lens = near/far exaggeration, immersion; long lens (70mm+) = compressed stacked layers.
- H6. Place the camera at a natural funnel (gate, path bend, gap between FG masses) so the view is inherently framed.
- H7. Asymmetric balance: off-center heavy focal balanced by a small far element + open negative space (balance = mass × distance from center).
- H8. Key light 30-60° off camera axis, raking across the focal so lit and shadow sides both show.
- H9. Pre-render checklist: focal at thirds, margin at edges, no tangents, dark FG anchor, readable horizon.

---

## PART 2 — Practical 3D Layout & Set Dressing (game dev / level art)

Sources: The Level Design Book (env-art, composition, metrics, Disneyland study), Game Developer ("Composition in Level Design", "Random Scattering", "Art Tips for Building Forests", Don Carson "Environmental Storytelling"), Worch/Smith GDC 2010 "What Happened Here?", 80.lv, Experience Points, World of Level Design, StraySpark.

### A. Composition & focal hierarchy
- A1. One dominant focal point per view: brightest lighting, highest detail density, strongest color contrast. Never two heroes of equal weight.
- A2. 3 depth layers: foreground (dark, low detail, frames the view, overlaps frame edges), center of interest (bright, detailed), background (desaturated, calm).
- A3. Dominant off-center (~38% from one frame edge, golden ratio), dead-center only for monumental/architectural statements.
- A4. Balance visual weight: one large/dark/detailed mass on one side needs 2-3 smaller counterweights on the other.
- A5. Contrast in 4 dimensions: height (one tall among short — cap secondary buildings at ~60-70% of hero height), density (open plaza ringed by tight structures), orientation (one object rotated 20-45° off the grid), shape (one round among rectangles).
- A6. Mix matte and reflective; all-matte = flat, all-shiny = noisy.
- A7. 3-4 color values per zone (one dark, two mids, one highlight); most saturated accent at the focal only.
- A8. Highest prop density at focal and along the route; lowest in background and dead zones.
- A9. One moving element near the dominant if possible (flag, smoke, water) — motion strengthens focal pull.

### B. Landmarks, weenies & sight-lines
- B1. Every navigable scene needs a "weenie": one landmark 2-4x taller than surroundings, visible from entry and most of the area (Disney).
- B2. Hub-and-spoke: districts around the landmark; each sub-area gets a smaller secondary landmark visible from its entrance.
- B3. Clear sight-corridor from entry to the weenie: nothing taller than ~1/3 of landmark height inside that corridor.
- B4. Paths may branch, but every branch curves back toward the critical path/landmark.
- B5. Gateway framing: flank area transitions with paired vertical elements (arch, two trees, gateposts) 1-2 path-widths apart, framing the next landmark in the gap.
- B6. Hero/landmark assets appear ONCE per map. Keep the landmark's base clear of clutter so its silhouette reads.
- B7. Curve roads/rivers in S-shapes toward the focal; curved leading lines read natural and reveal progressively.

### C. Object placement & clustering
- C1. Cluster, don't scatter: groups of 2-5 related objects, clear empty space between clusters (objects 0.1-0.5m apart within, clusters 5-15m apart).
- C2. Asymmetrical fractal duplication: place one, duplicate → shrink ×0.6-0.9 → rotate → offset; repeat. Works for rocks, barrels, crates, plants.
- C3. Odd numbers: 3s and 5s read natural; pairs and even rows read man-made — use each deliberately.
- C4. Never duplicate with identical transform: vary Z-rotation ±5-180°, uniform scale ±10-20%; never two identical assets side by side at the same rotation.
- C5. Pure random placement fails (accidental lines and voids). Grid perturbation: grid spacing D, offset each item ±0.4D in X/Y (guarantees 0.2D min spacing).
- C6. Exclusion radii: reject placements closer than footprint radius to a neighbor; after N failed retries the area is full.
- C7. Lean and stack: lean 1-2 props per cluster against walls/larger objects (5-15° off vertical, touching both); stack with 5-10cm edge offsets and 2-8° rotation deltas.
- C8. Orient by use: chairs face tables, benches face views, tools point at their work, signs face the road. Only debris gets random rotation.
- C9. Man-made objects align loosely to architecture: parallel ±2-8° jitter; perfect parallel = sterile, >15° = chaos (unless ransacked).
- C10. Density rhythm: dense cluster → sparse gap → dense cluster. Uniform density is boring AND illegible.

### D. Grounding & contact
- D1. Nothing floats: sink every object 1-3cm into terrain (heavy objects 3-10cm); align to sampled terrain height; tilt props to terrain normal up to ~10°, buildings 0°.
- D2. Buildings don't tilt — they get foundations: flatten a terrain pad or extend the foundation into the slope; never rotate a building to a slope.
- D3. Soften every structure-terrain seam: grass tufts, small rocks, dirt piles along 30-60% of the base perimeter, concentrated at corners.
- D4. Detail at the base: most detail where objects meet ground (roots, moss, dirt skirts) — the camera lives at ground level.
- D5. Accumulation logic: leaves/dirt/trash collect in corners, against walls, under trees — scatter debris 2-3x denser within 0.5m of vertical surfaces.
- D6. Weathering pairs with contact: long-sitting objects get moss/dirt at the contact line; fresh objects don't. One story per prop.

### E. Scale & proportion
- E1. Anchor to the human: 1.8m tall, eye 1.6m. At least one human-scale anchor (door, bench, fence, cart, lamppost) per camera view.
- E2. Core metrics (m): door 1.0-1.25 × 2.0-2.5; ceiling 3.0; path ≥2.0 wide; step 0.15-0.17 × 0.25-0.3; railing 1.0-1.1; seat 0.45; table 0.75; sill 0.9-1.0; street lamp 3-5; one-story 3-4; two-story 6-7.
- E3. Game doors/hallways run ~125% of real size for camera comfort — err bigger.
- E4. Scale contrast for drama: hero 2-4x neighbors; for awe, put a small human-scale object directly at the giant's base.
- E5. Forced perspective (Disney Main Street): scale successive stories 3/4 → 5/8 → 1/2 going up.
- E6. Trees: deciduous 8-15m, pines 15-25m — taller than a 1-2 story house. Beginners chronically undersize trees.
- E7. Organic repeats need ±10-25% scale variance; manufactured repeats (fence posts, lamps, windows) stay IDENTICAL — nature varies, manufacturing doesn't.
- E8. Justify every prop's size against the 1.8m human; if it can't be justified, fix it.

### F. Terrain & ground dressing
- F1. Never leave ground flat: ±0.1-0.3m undulation at 5-20m wavelength; true flat only for man-made floors, plazas, water.
- F2. Paths are worn, not painted: 1-2m band of bare dirt, vegetation → 0 on the path, ramping to full over 0.5-1.5m; irregular edges, never parallel lines.
- F3. Desire lines: cut an informal shortcut across open ground between high-traffic points, even when a paved path exists.
- F4. Rocks cluster in size families (1 boulder + 2-4 medium + 5-10 pebbles), sunk 10-30% into terrain; concentrate at riverbanks, slope bases, cliff feet.
- F5. Slope logic: no trees above 30-35° slopes; grass thins above ~25°; scree at cliff bottoms.
- F6. Water logic: vegetation 2-3x denser within 5-15m of water; reeds at the waterline; extra rocks on banks.
- F7. Altitude/exposure: vegetation thins with altitude and on exposed ridges; densest in valleys and depressions.
- F8. No straight biome borders: noise-driven irregular boundaries with 1-3m interleaved overlap (grass↔dirt, forest↔meadow).

### G. Vegetation distribution
- G1. Bold clumping with bare gaps: drive density with large-scale noise (50-100m wavelength) so clearings and thickets emerge.
- G2. Layer in 3 sizes: canopy trees → understory shrubs → ground cover; place shrubs AROUND large trees (1-2 canopy radii), not in the open between them.
- G3. 10-25% of forest trees dead/fallen/leaning/bare; 1-2 anomalies per area (tree leaning on neighbor 10-20°, log across a boulder).
- G4. Trunk density beats canopy count: cheap bare trunks fill the deep forest behind the first full row.
- G5. Forest floor is ferns/shrubs/litter/rocks — not lawn grass. Grass belongs in clearings.
- G6. Per-instance: random Z-rotation 0-360°, scale 0.8-1.2, tilt 0-5°; never two identical silhouettes adjacent.
- G7. Forest edges are gradual: 5-15m band of shrubs/young trees between full forest and meadow; denser on the sunlit side.

### H. Storytelling through layout
- H1. Answer "where am I / what is this place" within 15 seconds via recognizable anchors; a scene's primary function must read at a glance (Don Carson).
- H2. Cause-and-effect prop chains: axe + stump + woodpile + chips; ladder + half-repaired roof. Minimum viable story = 3 related props (Worch/Smith).
- H3. Every prop answers: who put it here, when, why HERE? No answer = delete or move.
- H4. Imply the absent inhabitant: interrupted activity reads strongest — chair pushed back, tools mid-task, meal half-eaten, door ajar.
- H5. History through wear and repair: patched fence in a different material, repainted patches, boarded windows — 1-2 visible repairs per structure.
- H6. One story per space: a single key narrative prop highlighted by light and composition; everything else is supporting cast.
- H7. Asymmetry = life: 5-10% of any repeated man-made series broken, crooked, or missing.

### I. Common mistakes — negative checklist
- I1. Floating/intersecting: verify every base contacts ground; no visible mesh interpenetration (except deliberate sink-in).
- I2. The clone stamp: identical rotation+scale duplicates in view together — the #1 amateur tell.
- I3. Even spacing everywhere = parking lot. Regular spacing only for orchards, colonnades, streetlights.
- I4. Over-cluttering: keep 30-50% of the scene as visual rest area; detail clusters at focal points and routes.
- I5. Tangents: no two unrelated silhouettes barely touching from the main camera.
- I6. Everything pristine = CGI-fake; uniform grunge = equally fake. Wear where use happens: handles, thresholds, path centers, corners.
- I7. Scale drift: everything checks against the 1.8m human.
- I8. Stage the entry view deliberately: dominant visible, framed, human anchor present — never arbitrary.

---

## PART 3 — Production Design & Set Decoration (film)

Sources: Dennis Gassner (Team Deakins), Sarah Greenwood (Pushing Pixels), Adam Stockhausen (The Film Stage), Hannah Beachler (NPR — Wakanda bible), Annie Atkins (99% Invisible "Hero Props"), PulseGeek, GarageFarm, Creative Pathways, Blauw Films, Tidbits & Twine (rule of odds), wolfcrow / No Film School (60-30-10), StudioBinder, FilmDaft, Fiveable, Suite Studios, FilmLocal.

### A. From story to design brief (before placing any object)
- 1. Boil the story down to ONE word ("decay", "wonder", "control"); test every object, color, and layout choice against it (Gassner).
- 2. Decide the full palette before building: dominant, secondary, accent per scene — and stick to them.
- 3. Write a mini world-bible first: period, place, climate, wealth level, who lives here. Every object answers to it (Beachler).
- 4. Ground fantasy in real reference: fantastical form + recognizable material/structure = believable; fantastical everything = alienating.
- 5. Give key structures a one-line backstory ("mining town that got rich then died") and let it dictate materials and wear.
- 6. Every scene is a period piece, even today: date-stamp the world; check each asset against the date (Greenwood).
- 7. Design for character: a set is a portrait of its inhabitant. Answer occupation, wealth, tidiness, one hobby — then place ≥3 objects proving each answer.

### B. Color rules
- 8. 60-30-10: ~60% dominant color family, ~30% secondary, ~10% accent — accent ON the focal object (Grand Budapest: pink dominant, muted blue secondary, red/yellow accents on heroes).
- 9. 2-3 color families max; variety via saturation/value shifts inside families, not new hues.
- 10. Warm = comfort or danger; cool = calm or isolation. Match temperature to the one-word mood; accent gets the opposite temperature.
- 11. Maximum contrast creates the focal wherever it sits — never allow max contrast on a background prop.
- 12. Signature color: assign one color to the protagonist's key object/zone, repeat in small doses for cohesion.
- 13. Wealth/mood via saturation: desaturate + darken for poverty/decay/the past; saturate + clean for wealth/optimism/artificiality.

### C. Camera-first composition
- 14. Design from the camera outward: pick 1-3 views first, place objects to compose those frames; don't spend budget behind the camera (Stockhausen).
- 15. Focal at a thirds intersection; dead center only for formal/oppressive/ritual moods (Wes Anderson symmetry = deliberate artifice signal).
- 16. 1-2 leading lines per shot pointing at the focal: road, fence, tree row, cable, light shaft entering from a lower corner.
- 17. At most 2-3 compositional guides per vista (thirds + one leading line + one color contrast); more reads as herding.
- 18. 3 depth planes: dark foreground frame element (partially cropped), midground subject, desaturated lighter background. A shot missing foreground reads flat.
- 19. Silhouette check: key shapes identifiable in a black-and-white thumbnail; if two majors merge into a blob, move one.
- 20. Frame the focal with architecture: doorways, arches, windows, tree canopies lock attention.

### D. Focal hierarchy & hero props
- 21. One hero object per scene: most detail, best light, accent color, clear line of sight. Everything else is supporting cast.
- 22. Hero earns 3-4x the detail budget of background props; background props only need to read at a glance (Annie Atkins).
- 23. Stack cues on the hero: isolation + brightest/rim light + the 10% accent + elevation (pedestal/table, not floor).
- 24. One dominant narrative cue per room-sized volume + exactly 2 minor hints in the periphery.
- 25. Foreshadow with placement: clues where the natural camera catches them — "obvious in hindsight, not invisible initially."
- 26. Repeat a motif with variation 2-3 times across the scene (carved on a door, echoed in a window) to tie the world together.

### E. Set dressing — making it lived-in
- 27. Stage interrupted action: open book face-down, tools on a half-repaired fence, cup beside an unfinished letter, chair pushed back.
- 28. Clutter is narrative: each cluster answers "who used this, for what, why still here?" A mug ON a ledger tells a story; a mug NEXT to it is dressing.
- 29. Layer time: rooms accumulate — mix object ages; newest items small and cheap, oldest large (Greenwood: post-war rooms keep pre-war furniture).
- 30. Wealth is WHEN things were bought: poor = dated-but-cared-for or new-but-cheap; rich = current or antique-by-choice.
- 31. 2-3 purely personal, non-functional items per inhabited space (photo in a mirror, dusty trophy, child's drawing) — strongest "someone lives here" signal.
- 32. Nothing brand-new in an inhabited space unless newness IS the story; one showroom-fresh object in a lived-in room reads as an error.
- 33. A prop made by a character reflects that character's skill and materials — a child's sign is crooked; a soldier's repair uses wire.
- 34. Show yesterday: leftover traces of the previous scene of life (last night's dishes, wilted flowers).

### F. Aging, wear & weathering
- 35. Wear goes where hands and feet go: doorknob zones, path centers, stair treads, chair arms; corners and high surfaces stay dusty. Uniform aging = fake.
- 36. Dirt in recesses, rain streaks from protrusions: darken under sills and roof edges; streak downward from metal fixtures.
- 37. Age to perception, not history: make "old" look how the audience believes old looks (yellowed paper, warm patina).
- 38. Symmetric even dust = abandonment; asymmetric wear = active use. Choose per story.
- 39. Grade by exposure: exteriors weather hardest on the weather side and in the splash zone (~0.5m up walls); interiors at touch height (0.8-1.2m).
- 40. Overgrowth timeline: weeks = tall grass; years = vines and gutter saplings; decades = trees through floors.

### G. Grouping, spacing & asymmetry (styling math)
- 41. Odd clusters — 3, 5, or 7 per vignette; even counts split into pairs and read staged.
- 42. In every group vary all three: height (no two adjacent equal — tops form a triangle, not a line), shape (round vs angular), texture (rough vs smooth).
- 43. A tight stack/tray of small items counts as ONE visual unit — use stacking to reach odd counts and organize micro-clutter.
- 44. Breathing room: clear space around a cluster ≥ half the cluster's own width; touching groups merge into clutter.
- 45. Reserve even numbers and mirror symmetry for formality/authority/ritual (thrones, courts, temples); asymmetry for ordinary life.
- 46. Kill the grid: rotation jitter ±5-20°, spacing jitter, scale ±10-15% between "identical" items.
- 47. Compose in 3D triangles: three related objects at three heights AND three depths, never in a row parallel to camera.

### H. World consistency & believability
- 48. Set internal rules and never break them silently; one inconsistent object breaks the whole set (Blauw Films).
- 49. The stranger the world, the tighter the logic: keep gravity, weather, and human scale familiar unless the story is about breaking them.
- 50. Materials obey geography and economy: build from what's locally abundant; imported material = wealth signal, keep it rare.
- 51. Architectural vocabulary: arches/columns = power/antiquity; low ceilings = intimacy/oppression; high = grandeur/exposure; small windows = cold or defense.
- 52. One era, one construction logic: match door heights, window styles, roof pitches, ornament density per district; a mismatch must be a story beat.
- 53. Technology needs a supply chain: any advanced/magical device implies infrastructure — show one trace (cables, fuel drums, spare parts).
- 54. Sweep for anachronisms: objects newer than the world's date are errors unless plot.

### I. Lighting & atmosphere (design-side)
- 55. Mood by contrast ratio: high-key (bright, low contrast, soft) = safe/cheerful; low-key (dark, high contrast, hard) = tension/noir.
- 56. Focal brightest and warmest; brightness falls off toward frame edges; never put the brightest patch on a blank wall.
- 57. Motivate every light: each glow needs a source object, colored to its physics (fire warm, moon cool, fluorescent greenish).
- 58. Atmosphere for depth: even 5-10% haze separates background from midground in a way geometry can't.
- 59. One dramatic light shaft (window, canopy gap, door crack) is the cheapest focal-point machine — aim it at the hero.

### J. Scale, density & negative space
- 60. Scale detail to camera distance: enclosed spaces need dense small props; vistas need large readable shapes — tiny props in a wide shot are wasted budget.
- 61. Negative:positive space is an emotional dial: full frame = energy/pressure; ≥60% empty = minimalist/lonely/calm.
- 62. Don't fill every zone: deliberate empty walls and floors make dressed clusters stand out.
- 63. Human scale is the ruler: doors ~2-2.2m, seats 0.45m, tables 0.75m, counters 0.9m — distort only when distortion is the point.
- 64. Keep the route between camera and focal clean: dense dressing at edges and corners, never down the middle.

---

## PART 4 — Color & Lighting (film color scripts, CG lighting, Gurney)

Sources: Chris Brejon *CG Cinematography* (ch 2/4/6), Radiator GDC 2018 "How to Light a Level", The Level Design Book (lighting), James Gurney *Color and Light*, Neil Oseman (moonlight), wolfcrow, Brink Helsinki (color scripts), Digital Synopsis (film color psychology), StudioBinder (lighting ratios), Kelvin/sun-elevation references. RGB values are usable directly as Blender light colors.

### A. Palette structure
- 1. 3 colors per scene: dominant ~60%, secondary ~30%, accent ~10%. Dominant sets mood; accent marks the focal.
- 2. Accent complementary (or near) to dominant; ONLY on/near the focal object.
- 3. Gamut mask: 2-3 hue families + neutrals; derive every color from inside that gamut.
- 4. Neutrals are never pure grey: bias 5-15% toward the dominant hue.
- 5. Orange-teal is the lowest-risk environment scheme; analogous = calm; triadic = energetic.
- 6. Dominant on LARGE surfaces (world/sky, ground, biggest objects); secondary on mids; accent on the hero.
- 7. Palette tracks emotion per beat: muted at lows, peak saturation+warmth at climax — muted scenes make the peak land (Pixar color scripts).
- 8. Warm dominant = comfort/excitement; cool = isolation/melancholy. Emotion first, then temperature, then hues.

### B. Saturation discipline
- 9. Saturation = attention: most-saturated element wins the eye. Focal may be saturated; surround must not.
- 10. 60-80% of surfaces at HSV saturation < 0.25; reserve S > 0.6 for the ~10% accent.
- 11. Desaturate with distance: backgrounds shift toward sky color, losing saturation and contrast.
- 12. No pure primaries / zero channels (no (1,0,0)); keep every RGB channel ≥ 0.02 — zero channels kill bounce.
- 13. Light on the focal near-neutral; saturated color goes into environment/ambient lights instead.
- 14. Colored light overwrites object color — under saturated light, reduce material saturation to compensate.

### C. Value structure (notan)
- 15. Design in 2-3 flat value masses first (sky mass, ground mass, subject mass); merge close shadows into one connected shape.
- 16. Value contrast beats color contrast at the focal: lightest-light against darkest-dark there, nowhere else.
- 17. Squint test: blurred to masses, subject must separate from background; fix values, not hues.
- 18. Counterchange: light subject on dark ground or dark on light — never subject and backdrop at the same value.
- 19. Don't light everything: alternate bands of light and shadow along the depth axis.
- 20. Separate background from subject by ~2 stops (4x luminance) up or down.
- 21. Albedo 0.05-0.8 linear: near-black kills GI; near-white blows out.
- 22. The brightest spot in frame must be the focal or a motivated source.

### D. Color of light vs color of object (Gurney)
- 23. Pixel = light color × object color. Author base colors as if under neutral light; let the rig warm/cool the scene.
- 24. Warm key ⇒ cool shadows (and vice versa). Shadow hue = fill hue (usually sky). Sunny day: shadows blue-grey, value 25-40% of lit side, never black.
- 25. The sky is a giant blue fill light — in Blender the WORLD BACKGROUND is that fill; every shadow inherits its color. Never pure black or default grey.
- 26. In shadow: up-facing planes cool (see sky), down-facing planes warm (ground bounce). Add a weak warm bounce from below (~1/8 key).
- 27. Warm advances, cool recedes: warm the foreground/focal, cool the distance.
- 28. Max temperature contrast at low sun: warm key (2000-3500K) + blue sky fill = orange-teal for free.
- 29. Sky gradient: warmest/most saturated at horizon near sun, coolest overhead.
- 30. Water reflections render slightly darker than the object reflected.

### E. Time-of-day recipes (Blender-ready)
- 31. Golden hour: sun elevation 0-6°; 3500K→2000K, RGB (1.0, 0.72, 0.45)→(1.0, 0.55, 0.25); Blender sun angle 1.5-3° (long soft shadows); low contrast; sky warm at horizon, desaturated blue above.
- 32. Midday: elevation 50-70°; 5500-6000K (1.0, 0.95, 0.9); hard short shadows (sun angle 0.53°); high contrast; cool blue shadow fill; reads harsh/exposed — heat, brutality, banality.
- 33. Overcast: no sun disc — sky IS the light; 6500-7500K; world bright cool grey ~(0.75, 0.78, 0.82); near-shadowless (sun angle 15°+ or sky-only); compressed values; local colors read strongest; quiet/bleak.
- 34. Blue hour: sun -4 to -6°; ambient deep desaturated blue 9000-12000K, RGB (0.4, 0.5, 0.8) low intensity; any warm 2700K practical (1.0, 0.6, 0.3) becomes an automatic focal accent.
- 35. Night/moonlight: readable convention = dim desaturated blue: moon key (0.6, 0.7, 0.9) at ~1/200-1/1000 of day-sun, elevation 30-60°; world near-black blue (0.01-0.03). Keep the blue DESATURATED.
- 36. Moonlight contrast: key vs ambient 4:1-8:1, hard-ish shadows (sun angle 0.5-1°); silver-grey reads more grounded than saturated blue.
- 37. Warm interior: practicals 2700-3200K = (1.0, 0.6, 0.35)-(1.0, 0.71, 0.45); pair with a cool 6500K+ window/moon fill; motivate every light.
- 38. Sunrise cooler/pinker (hope, freshness); sunset warmer orange-red (nostalgia, ending).
- 39. Night is not black: compress values, 3-5 stops darker, blue shift, desaturate — everything stays readable.
- 40. Storm/ominous: invert the value structure — sky mass darker than the sunlit subject.

### F. Key direction & cinematic depth
- 41. Never key from the camera: offset the key ≥30-60° horizontally and 30-45° in elevation off the camera axis.
- 42. Best environment depth: 3/4 backlight — key azimuth ~110-160° away from camera azimuth; camera-facing surfaces carry gradation, objects get a lit edge.
- 43. Rim/silhouette: backlight against a brighter background; rim intensity 1-2x key.
- 44. Key:fill ratio sets genre: 2:1 light/comedic, 4:1 drama, 8:1+ noir/thriller. Set key, then fill = 1/2, 1/4, 1/8.
- 45. One light must dominate: never two equal rims or symmetric setups.
- 46. Shadow softness = source size: sun angle 0.5° crisp midday, 2-5° golden/hazy, 15°+ overcast-soft.
- 47. Light depth planes separately at 3 values (e.g. dark FG, lit MG, bright BG).
- 48. No crossed shadows: ONE shadow-casting key per scene.
- 49. Motivate every non-sun light with a visible or implied source; unmotivated glows read gamey.
- 50. Light hierarchy = attention hierarchy: important brighter/warmer, secondary dimmer/cooler, never uniform.

### G. Mood-to-color mappings (defaults)
- 51. Danger/violence/passion: red-orange dominant, 8:1 contrast, hard shadows. Comfort/nostalgia: golden ~3000K, soft 2:1.
- 52. Melancholy/isolation: desaturated blue dominant (S 0.2-0.4), overcast or blue-hour recipe, compressed values.
- 53. Unease/sickness/poison: green-shifted light or green-tinted sky.
- 54. Magic/mystery: purple/teal ambient + warm accent; luxury: deep purple + gold.
- 55. Yellow flips on saturation: pale warm yellow = joy; acid yellow-green = madness/poison.
- 56. Bleak/apocalyptic: near-monochrome (S < 0.2) + one warm/red accent (Blade Runner 2049).
- 57. Reliable universals: temperature (warm=life, cool=distance/death) and saturation (high=intensity, low=drained); hue symbolism is contextual.
- 58. Signal with the accent, not a flood: red on 10% of frame beats red on 100%.

### H. Blender execution guardrails
- 59. Choose light colors by Kelvin first (Blackbody or the RGB approximations above), then art-direct hue by at most ~10%.
- 60. The world background is a real light: sky-colored by day, near-black blue at night, bright grey overcast — always set deliberately.
- 61. Set ratios, not absolutes: key first; fill = 1/4 key (drama); rim = 1-2x; world = 1/8-1/10 key sunny, ~1x overcast. Ratios survive exposure changes.
- 62. Verify the notan after building: if the greyscale doesn't read (3 masses, max value contrast at focal), no hue change will save it.

---

## CONVERGENCE — the cross-validated core

Rules independently arrived at by 3+ of the 4 research passes (strongest signals, the spine of the Creative Director KB):

1. **One focal dominant, everything subordinate** — 2-4x neighbor height/weight, brightest light, strongest value contrast, the accent color, highest detail, isolated silhouette, at a thirds intersection. (all 4 passes)
2. **Ratio-controlled palette** — 60-30-10 (or 70/30), 2-3 hue families + neutrals, saturation reserved for the focal accent, temperature contrast between focal and surround. (all 4)
3. **Odd clusters + variation + gaps** — groups of 3/5/7, vary height/rotation/scale (organic ±10-25%, manufactured identical), cluster spacing >> intra-cluster spacing, 30-50% of the scene as rest area. (all 4)
4. **Three depth layers with distinct value bands** — dark FG frame / lit MG focal / hazy light BG, overlap decisively, desaturate with distance. (3 passes)
5. **Value before color (notan)** — 2-4 value masses, max value contrast at the focal only, squint/thumbnail test. (3)
6. **Ground and wear everything** — sink bases, soften seams, wear where hands/feet go, accumulation in corners; pristine = fake, uniform grunge = fake. (3)
7. **Every prop is evidence** — who/when/why-here, cause-effect chains of ≥3 props, interrupted action, orient by use. (3)
8. **Human metric anchor** — 1.8m human, ~2m doors, 0.45m seats; one anchor per view; trees taller than houses. (3)
9. **One dominant motivated key light + world-as-fill** — single shadow-caster, 3/4 backlight off camera axis, warm/cool key-fill split, key:fill ratio as the mood dial. (3)
10. **Camera-first design** — compose the 1-3 intended frames, not the floor plan; leading lines to the focal; tangent check; stage the entry view. (3)
