# 3D generation: photos + measurements + chat → printable model

Checked 2026-10-24. "(inf)" means inferred.

## Picks

| # | Decision | Pick | Runner-up |
|---|---|---|---|
| 1 | Organic (figurine, pet keychain) | **Meshy `meshy-7.1` Multi-Image to 3D, mesh only** | Tripo H3.1 (cheaper, faster). Hi3D v3.0 is the quality ceiling at about 5× the cost |
| 2 | Functional / measured parts | **Claude Opus 5.5 writing CadQuery, with a render-and-check loop** | GPT-6 Astra writing the same code; Zoo Text-to-CAD as a hosted fallback |
| 3 | Router | **Gemini 3.8 Flash classifier with JSON output** | Keyword rules |
| 4 | Measurements (web/PWA) | **User types key dimensions, plus an optional credit-card-in-photo scale check** | Native iOS LiDAR (later) |
| 5 | Printability | **trimesh + manifold3d (+ pymeshlab), then Bambu Studio CLI for the quote** | Meshy Repair Printability API |
| 6 | Vision LLM | **Gemini 3.8 Flash** | Claude Opus 5.5 / Gemini 4 Argon |

## 1. Image-to-3D (organic)
- **Ranking:** Rapidata human-preference board (357 images, 262k votes, updated 2026-10-24). Overall Elo: Hi3D v3.0 1366, Meshy 7.1 1298, Tripo H3.1 1261, Hunyuan3D 3.1 Pro 1144, Seed3D 2.0 1097, TRELLIS.2 1005, Rodin Gen-2.5 High 956, Hunyuan3D 2.1 750, SAM 3D Objects 658. The geometry-only order is similar.
- **Why Meshy:** #2 on quality and the most print-ready API.
  - Accepts 1–4 photos.
  - Analyze Printability is free (watertight, holes, wall thickness). Repair Printability costs 10 cr and can thicken walls.
  - Outputs: GLB, STL, 3MF, OBJ.
- **Cost:** mesh only is 20 cr, 2K texture is 30 cr. About $0.02/cr on the $20 / 1,000-credit plan (inf): **~$0.40 mesh-only, +$0.20 repair.**
- **Latency:** median 65 s mesh-only; about 2.5 min textured.
- **API:** async. POST returns a task ID, then poll or use a webhook.
- **Skip textures:** we print single-colour PLA, so a clay preview shows what will actually print.
- **Tripo H3.1:** $0.20 untextured, about 40 s, 3 tasks at a time. No print repair.
- **Others:**
  - Hi3D v3.0 via fal: $2.10, exports STL.
  - Rodin Gen-2: about $0.40.
  - Hunyuan3D 3.1 API: 25 cr × $0.02 = $0.50.
- **Self-host fallback:**
  - Hunyuan3D-2.1 (newest open weights; shape-only about 10 GB VRAM, inf).
  - TRELLIS.2-4B (≥24 GB, about 17 s at 1024³ on an H100; raw meshes can have holes).
  - Skip SAM 3D Objects (ranks last).

## 2. Parametric CAD (measured parts)
- **Benchmarks:**
  - CAD Bench V3 (Sept 2026): Opus 5.5 61.0, GPT-6 Astra 56.9, Gemini 3.8 Flash 36.2.
  - BenchCAD 2.0 (Oct 12): Astra 0.59 at $11/case, Opus 5.5 0.57 at $28/case.
  - CAD Arena: Opus 4.6 and Zoo each produced 19/20 valid STLs.
- **Loop:**
  1. Template with a `params` dict, units in mm.
  2. Run in a sandbox and export STL + STEP.
  3. Assert the bounding box matches the requested dimensions and the solid is valid.
  4. Render a PNG and feed it back to the model. Cap at 3 iterations.
- **Cost/latency:** about $0.05–0.30 and 10–60 s at medium effort (inf). The benchmark runs used multi-hour, max-effort agents; don't do that live.
- **Zoo Text-to-CAD:** $0.0083/s (about $0.50/min), billed only on success; 20 free min/month.
- **Preview:** convert STL to GLB with trimesh and show it with `<model-viewer>` in the Lovable app. For chat thumbnails, render PNGs server-side with pyrender.

## 3. Router and edits
- **Router:** Gemini Flash reads the photos plus the transcript and returns `{path: organic|parametric|hybrid, dims_known, missing_fields[]}`.
  - Parametric: dimensions mentioned, or fit/function words (mount, knob, box, hole, M3).
  - Organic: likenesses of people, pets or characters.
  - Hybrid, e.g. a pet keychain: organic mesh unioned with a parametric ring/base via manifold3d.
- **Edits, parametric:** the LLM edits `params` or adds a feature, then the code re-runs ("2 cm taller" becomes `height += 20`). Deterministic, with history.
- **Edits, organic:**
  - Geometric edits in manifold3d: scale, base, keyring hole, text.
  - Pose or appearance changes: edit the image, then regenerate. The result is non-deterministic, so show a before/after.

## 4. Measurement capture
- Vision LLMs are weak at absolute scale (MeasureBench). Never quote from an LLM size guess alone.
- **Web/PWA:**
  - Ask for one or two dimensions.
  - Optionally have the user put an ID-1 card (85.60 × 53.98 mm) in the same plane as the object. Detect the card with OpenCV, apply a homography, get mm per pixel. Expect about ±3–5% (inf).
- **Native only:** ARKit/LiDAR.
- **WebXR AR:** works on Android Chrome. Unreliable on iOS Safari (WebKit bug 309550: crashes on iOS 26+).

## 5. Printability pipeline
1. **Repair:** trimesh `merge_vertices`, `fill_holes`, `fix_normals`. Then pymeshlab hole-close / non-manifold repair. Final step: `manifold3d.Manifold`. Assert `is_watertight`.
2. **Scale:** to the user's dimension. Defaults: about 70 mm figurine, 40 mm keychain.
3. **Orient:** `trimesh.poses.compute_stable_poses`. Flatten the bottom or union a 2–3 mm base.
4. **Walls:** FDM doesn't need hollowing (infill). Minimum wall ≥1.2 mm.
5. **Fit:** A1 is 256 mm³. Cap at 250 mm; split or refuse anything larger.
6. **Quote:** `bambu-studio --slice 1 --load-settings "machine.json;process.json" --load-filaments pla.json --export-3mf out.3mf model.stl`. Read `Metadata/slice_info.config` for `prediction` (s) and `weight` (g). OrcaSlicer CLI is the fallback.

## 6. Vision LLM
- **Gemini 3.8 Flash:** $0.75 / $3.75 per M tokens (intro price to Dec 31), about 2–5 s, under $0.01 per turn with photos.
- **Escalate** hard cases to Opus 5.5 ($4/$20) or Gemini 4 Argon ($2/$10 intro).

## Unit economics
- **Organic:** under $1 total. About 1–2.5 min generation plus about 30–60 s slicing.
- **Parametric:** under $0.30, about 20–60 s.

## Hackathon risks
- **Bad wifi:** async APIs, so poll with retries. Pre-generate demo assets.
- **Raw AI meshes:** often non-manifold. Always repair and check before slicing.
- **Bambu CLI:** needs exact A1 profile JSONs. Export from the GUI and test a slice early.
- **CadQuery:** install the OCP wheels before the event.

## Sources
- https://www.benchmark.ai/image-to-3d
- https://docs.meshy.ai/en/api/pricing
- https://docs.meshy.ai/en/api/task-lifecycle
- https://docs.meshy.ai/en/api/repair-printability
- https://developers.tripo3d.ai/en/models/v3-1
- https://fal.ai/models/hitem3d/hi3d/v3.0/image-to-3d/llms.txt
- https://docs.hyper3d.ai/en/api-specification/rodin-gen2
- https://www.tencentcloud.com/document/product/1281/74121
- https://huggingface.co/microsoft/TRELLIS.2-4B
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- https://cadbench.ai/leaderboard
- https://benchcad.com/blog/benchcad-2
- https://cadarena.dev/
- https://zoo.dev/api-pricing
- https://ai.google.dev/gemini-api/docs/pricing
- https://platform.claude.com/docs/en/models/opus-5-5/overview
- https://bambulab.com/en/a1/tech-specs
- https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- https://github.com/bambulab/BambuStudio/issues/872
- https://bugs.webkit.org/show_bug.cgi?id=309550
- https://arxiv.org/html/2510.26865v1
