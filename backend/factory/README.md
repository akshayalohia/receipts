# factory: BE1 pipeline library
Deterministic tools the bots call (contract: `SPEC.md` § BE1). Internal units: mm, Z up, part resting on z=0.

| Module | What |
|---|---|
| `types.py` | `Artifact`, `SliceResult`, `Quote`, `PrinterStatus` |
| `cad.py` | `list_templates`, `build_template` (nametag, keychain_ring, holder, knob, cable_clip), sandboxed `run_cadquery` → `CadError(message, traceback_tail)` |
| `mesh.py` | `generate_from_images` (Meshy `POST /openapi/v1/multi-image-to-3d`, `meshy-7.1`, `should_texture:false`, polls with `Retry-After`), `finish_for_print`, `combine` |
| `convert.py` | `to_all_formats`: STL (mm), GLB (m, Y up), USDZ (m, `metersPerUnit=1`, Y up, ARKit package), PNG 800×800 via matplotlib Agg |
| `slicer.py` | `slice_model`: OrcaSlicer CLI + flattened A1 profiles in `profiles/`; mock = volume estimate + `slice_result.json` (`estimate: true`) |
| `pricing.py` | `DEFAULT_POLICY`, `quote`, `load_policy`/`save_policy` (each value clamped to ±20%) |
| `printer.py` | `get_printer` → `BambuPrinter` (FTPS 990 + MQTT 8883 + camera :6000) or `MockPrinter` |
| `failure.py` | `check_snapshot` (Gemini vision; mock → ok) |
| `assets/sample_pet.stl` | procedural mock "Meshy" output |

**Mocks:** `FACTORY_MOCK=1`, or a missing `MESHY_API_KEY` / `GEMINI_API_KEY` / `PRINTER_*` / `ORCA_SLICER_BIN` (slicer: mock only when `FACTORY_MOCK=1`).
**Sandbox:** `python -I -c` child, `RLIMIT_CPU` = `timeout_s`, `RLIMIT_AS` 3 GiB, wall timeout, temp cwd/HOME, imports limited to cadquery/math, and an audit hook that blocks sockets and process spawning. Best effort, not a security boundary.

## Tests
```
cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r pyproject.toml --group dev
.venv/bin/python -m pytest tests/factory -q      # offline; conftest forces FACTORY_MOCK=1 and clears keys
```
Real-slice tests (nametag + sample-pet keychain): use `$ORCA_SLICER_BIN` or `tools/orca/squashfs-root/AppRun`
and `$ORCA_LD_LIBRARY_PATH` or `tools/libs/root/usr/lib/x86_64-linux-gnu`; skip if no slicer exists.

## Real-slice status (2026-10-24)
OrcaSlicer v2.4.2 x86_64 AppImage, extracted in `tools/orca/`. It needs three host libs it does not bundle:
`libOpenGL.so.0`, `libGLU.so.1`, `libmspack.so.0` (Ubuntu: `libopengl0 libglu1-mesa libmspack0t64`). Without root,
fetch them with `apt-get download`, `dpkg -x` them into `tools/libs/root`, and set `ORCA_LD_LIBRARY_PATH`
(`slice_model` prepends it to `LD_LIBRARY_PATH` for the slicer only). With those, the committed profiles slice
unchanged: default nametag 1031 s / 5.43 g, 40 mm sample-pet keychain with keyring 2341 s / 4.74 g.
The CLI runs without `--orient` (parts already rest flat on z=0). The binary needs GLIBC 2.38, so the Docker image is Debian trixie.
`slice_info.config` carries a level-3 `bed_temperature_too_high_than_filament` note: that is Bambu's own A1 values (65 °C textured plate vs 45 °C PLA vitrification), harmless on the open A1.
Profiles: `profiles/build_profiles.py` regenerates them from Orca's `resources/profiles/BBL`. It resolves `inherits` chains by `name`
(child overrides parent), adds `""` to `compatible_printers` (process, filament) and sets `curr_bed_type` = "Textured PEI Plate".

## Deviations from SPEC
- Printer uses paho-mqtt + ftplib + ssl directly, not `bambulabs_api`. That library builds its MQTT payloads in private methods (hard-coded `sequence_id`, `ams_mapping` and calibration flags), so they can't be unit-tested, and its pause/resume skip based on its own cached state. Payloads follow ha-bambulab `commands.py`. `ams_mapping:[0]` with `use_ams:false` is unverified on a real A1.
- `generate_from_images(prompt=...)` is accepted but not sent: the multi-image endpoint has no geometry prompt.
- `finish_for_print` "min wall": raises `MeshError` if more than 10% of sampled surface is under 1.2 mm thick (ray test). Keyring ring lies flat on the bed at the footprint's −X edge.
- Failure check calls the `gemini-flash-latest` alias, because no pinned "3.8 Flash" model id was verified.
- Pricing: the colour-swap fee is added after the floor, like the queue surcharge. The breakdown sums to the price.
- `MockPrinter.stop()` → state `FAILED` (Bambu reports a cancelled job that way). The mock `.gcode.3mf` is a placeholder and not printable.
