# Micro Factory: build spec (interfaces all workstreams share)

Product context: `PRD.md`. This file holds the exact contracts. If code and this file disagree, this file wins. If something here is wrong, change it in your workstream's report, not silently.

## Repo layout and ownership
| Path | Owner |
|---|---|
| `backend/factory/` (Python package `factory`), `backend/tests/factory/`, `backend/factory/profiles/` | **BE1 pipeline** |
| `backend/service/`, `backend/mcp_server/`, `backend/fleet/`, `backend/deploy/`, `backend/tests/service/`, `backend/pyproject.toml` | **BE2 services** |
| `ios/` | **IOS app** |
| `SETUP.md`, root files | integration |

BE1 does not create `backend/pyproject.toml`. It lists its Python deps in `backend/factory/REQUIREMENTS.txt`; BE2 merges them into `backend/pyproject.toml` at integration.

Python 3.12+. Use `uv`. Tests use pytest. Every external service has a mock, selected with `FACTORY_MOCK=1` or by a missing key. The full test suite runs offline with no keys.

## Environment variables (`backend/deploy/.env.example`)
```
FACTORY_MOCK=1                 # 1 = mock printer, Meshy, Whop, ElevenLabs, vision
FACTORY_DATA=./data            # orders/, db.sqlite, uploads
PUBLIC_BASE_URL=https://<tunnel-host>
APP_SHARED_SECRET=             # app sends X-App-Key; MVP auth
DEVICE header: X-Device-Id     # identifies a customer (no accounts in MVP)
MESHY_API_KEY=
GEMINI_API_KEY=                # failure check (vision)
WHOP_API_KEY=  WHOP_COMPANY_ID=  WHOP_PRODUCT_ID=  WHOP_WEBHOOK_SECRET=
ELEVENLABS_API_KEY=  ELEVENLABS_AGENT_ID=
HERMES_API_BASE=http://hermes:8642   HERMES_API_KEY=
MCP_TOKEN=                     # bearer token Hermes uses to reach the factory MCP
PRINTER_IP=  PRINTER_SERIAL=  PRINTER_ACCESS_CODE=
ORCA_SLICER_BIN=/opt/orca/AppRun
```

## BE1: `factory` library (pure Python, no web server)
```python
# factory/types.py
@dataclass class Artifact:
    stl: Path; glb: Path; usdz: Path; png: Path      # all four always produced
    bbox_mm: tuple[float, float, float]              # x, y, z after finishing
    watertight: bool
    volume_cm3: float
@dataclass class SliceResult:
    gcode_3mf: Path; print_seconds: int; filament_grams: float
@dataclass class Quote:
    price_cents: int; print_seconds: int; filament_grams: float; breakdown: dict[str, int]
@dataclass class PrinterStatus:
    state: str   # IDLE | PREPARE | RUNNING | PAUSE | FINISH | FAILED | OFFLINE
    progress_pct: int; remaining_min: int; layer: int; total_layers: int; job_name: str | None; raw: dict

# factory/cad.py
def list_templates() -> list[dict]       # [{name, title, description, params: JSON-schema-ish with defaults+units(mm)}]
def build_template(name: str, params: dict, out_dir: Path) -> Artifact
def run_cadquery(code: str, out_dir: Path, timeout_s: int = 90) -> Artifact
    # Code from the intake bot. Must bind `result` (cq.Workplane or cq.Shape), units mm.
    # Runs in a subprocess: no network, CPU/time/memory limits, temp dir, only cadquery/math imports allowed.
    # Errors raise CadError(message, traceback_tail) so the bot can fix and retry.
# templates (each a parametric CadQuery function, all dims mm):
#   nametag(text, width, height, thickness, font_size, border, hole)
#   keychain_ring(outer_d, inner_d, thickness)         # used to add a ring to meshes
#   holder(item_w, item_d, item_h, wall, clearance, angle_deg)   # stand/holder sized to an object
#   knob(d, h, shaft_d, shaft_flat, grip_ribs)          # fix-it example
#   cable_clip(cable_d, count, base_w)                  # fix-it example

# factory/mesh.py
def generate_from_images(image_paths: list[Path], out_dir: Path, prompt: str | None = None) -> Path
    # Meshy multi-image-to-3D (latest model, mesh only, no texture). Returns raw GLB/STL path.
    # Mock: returns a bundled sample mesh after a short delay.
def finish_for_print(src: Path, out_dir: Path, *, target_height_mm: float | None = None,
                     max_dim_mm: float = 250, add_base: bool = False, keyring: bool = False) -> Artifact
    # repair (trimesh -> pymeshlab -> manifold3d), scale, stable-pose orient, flat bottom/base,
    # optional keyring loop (unions keychain_ring), asserts watertight, enforces ≤250 mm and min wall.
def combine(a: Path, b: Path, out_dir: Path, op: str = "union") -> Artifact
# factory/convert.py
def to_all_formats(mesh_path: Path, out_dir: Path) -> Artifact   # STL + GLB + USDZ + PNG
    # USDZ: real-world scale (metersPerUnit set so AR Quick Look shows true size), via usd-core.
    # PNG: headless 3/4-view shaded render, 800x800, no GPU/display needed.

# factory/slicer.py
def slice_model(stl: Path, out_dir: Path) -> SliceResult
    # OrcaSlicer CLI with flattened Bambu A1 0.4 nozzle + 0.20mm Standard + Generic PLA profiles
    # stored in factory/profiles/. Textured PEI plate, external spool (no AMS).
    # Reads print_seconds and filament_grams from Metadata/slice_info.config.
    # If ORCA_SLICER_BIN missing and FACTORY_MOCK=1: estimate from volume (labelled estimate=True in a sidecar json).

# factory/pricing.py
DEFAULT_POLICY = {"base_cents": 300, "per_gram_cents": 6, "per_hour_cents": 250,
                  "queue_surcharge_cents": 200, "queue_threshold": 2, "colour_swap_cents": 200,
                  "floors_cents": {"nametag": 800, "fixit": 1000, "holder": 1200, "keychain": 1200, "figurine": 1500, "custom": 800}}
def quote(s: SliceResult, *, product: str, gen_cost_cents: int, queue_len: int,
          colour_loaded: bool, policy: dict | None = None) -> Quote
# policy is a JSON file the sales bot may edit within bounds: each value within ±20% of DEFAULT_POLICY.
def load_policy(path) -> dict;  def save_policy(path, policy) -> dict  # clamps to bounds, returns applied

# factory/printer.py
class Printer(Protocol):
    def start(self, gcode_3mf: Path, job_name: str) -> None
    def status(self) -> PrinterStatus
    def pause(self) -> None; def resume(self) -> None; def stop(self) -> None
    def snapshot_jpeg(self) -> bytes        # A1 built-in camera (TLS JPEG, port 6000)
def get_printer() -> Printer               # BambuPrinter (bambulabs_api: FTPS upload + MQTT project_file, use_ams False)
                                           # or MockPrinter (simulated progress, ~60 s per job in mock mode)
# factory/failure.py
def check_snapshot(jpeg: bytes) -> dict   # {"verdict": "ok"|"spaghetti"|"detached"|"empty_bed"|"unknown", "confidence": float}
                                           # Gemini Flash vision; mock returns ok.
```

## BE2: service, MCP server, fleet, deploy

### SQLite (`service/db.py`)
- `orders(id TEXT PK 'ord_xxx', device_id, status, product, path TEXT organic|parametric|hybrid, params JSON, colour, design_version INT, files JSON {stl,glb,usdz,png,gcode_3mf}, bbox_mm JSON, print_seconds, filament_grams, price_cents, gen_cost_cents, whop_variant_id, whop_purchase_url, payment_id, queue_position, eta TEXT, created_at, updated_at)`
- `messages(id, order_id, role user|agent|system, text, media JSON [urls], created_at)`
- `events(id, order_id NULL, actor TEXT (bot or system), type TEXT, payload JSON, created_at)`: every bot decision and state change; feeds the SSE stream and a later dashboard.
- `human_tasks(id, kind bed_clear|spool_swap|qa|pickup|other, order_id, details, status open|done, assignee teammate|terac, created_at, done_at)`
- `shop_state(key PK, value JSON)`: `loaded_colour`, `colours_in_stock` (list), `printer_busy`, `bed_clear` (bool).

Order status flow: `draft → designing → review → quoted → paid → queued → printing → done → picked_up`, plus `failed`, `refunded`, `cancelled`.

### HTTP API (`service/app.py`, FastAPI). All app routes need `X-App-Key` and `X-Device-Id`.
| Method | Path | Body / result |
|---|---|---|
| GET | `/health` | `{ok, mock, printer_state}` (no auth) |
| GET | `/catalog` | `{products: [{id, title, blurb, from_price_cents, path, needs: [photos|measurements|text]}], colours_in_stock, loaded_colour}` |
| POST | `/orders` | `{product}` → order |
| GET | `/orders` | this device's orders |
| GET | `/orders/{id}` | order + messages + latest artifact URLs + quote |
| POST | `/orders/{id}/photos` | multipart `files[]` (≤4, jpeg/heic/png) → `{urls}` |
| POST | `/orders/{id}/messages` | `{text, measurements?: [{label, mm}], colour?}` → 202 `{message_id}`; starts an intake run |
| GET | `/orders/{id}/stream` | SSE. Event types: `message` {role,text}, `agent_delta` {text}, `status` {status}, `design` {version, glb, usdz, png, bbox_mm}, `quote` {price_cents, print_seconds, filament_grams, colour, whop_variant_id}, `printer` {state, progress_pct, remaining_min}, `human_task` {kind}. Heartbeat comment every 15 s |
| POST | `/orders/{id}/accept` | customer accepts the design → status `quoted` path: slice + quote + Whop variant (via sales tools) |
| GET | `/files/{order_id}/{name}` | artifacts (signed by order id + device id) |
| GET | `/orders/{id}/camera.jpg` | latest printer snapshot; only while this order is printing |
| POST | `/voice/token` | `{order_id}` → `{conversation_token, agent_id}` (ElevenLabs; mock returns fake token) |
| POST | `/webhooks/whop` | Standard Webhooks signature check (`webhook-id`, `webhook-timestamp`, `webhook-signature`, secret `WHOP_WEBHOOK_SECRET`). `payment.succeeded` → find order by variant/plan id → `paid` → start production run. Idempotent on payment id |
| POST | `/dev/pay/{id}` | mock-only: same effect as a signed payment.succeeded |
| GET/POST | `/admin/*` | needs `X-Admin-Key`: `state`, `spool {colour}`, `bed-cleared`, `human-tasks`, `human-tasks/{id}/done`, `stock {colours}` |

How a customer message flows: POST message → service calls Hermes `POST {HERMES_API_BASE}/p/intake/v1/runs` with `session_id=order_id`. Input includes the order JSON, photo file paths visible to the MCP server, measurements and the message. Stream `GET /v1/runs/{run_id}/events` → `agent_delta` SSE → on completion store the agent message. Bots never write to the customer directly except through their final reply and the `post_customer_update` tool.

Printer monitor (background task in service): poll `printer.status()` every 5 s while busy; emit `printer` events; every 150 s `check_snapshot`; 2 bad verdicts in a row → pause + event + production run. On FINISH → order `done`, create `human_tasks bed_clear`, notify, start production run (it picks the next job only after `bed_clear` is true).

### MCP server (`mcp_server/server.py`, FastMCP streamable HTTP on :9000/mcp, bearer `MCP_TOKEN`)
Tools (each logs an `events` row with the calling bot from the `X-Hermes-Profile` header or a `bot` arg):
- Design: `get_order(order_id)`, `list_templates()`, `build_template(order_id, name, params)`, `run_cadquery(order_id, code)`, `generate_mesh(order_id, prompt?)` (uses the order's photos), `finish_mesh(order_id, src, target_height_mm?, add_base?, keyring?)`, `combine(order_id, a, b)`, `publish_design(order_id, artifact_id, summary)` → saves files, bumps design_version, status `review`, emits `design`. Every design tool returns `{artifact_id, bbox_mm, watertight, png_url}`.
- Sales: `prepare_quote(order_id)` → slice, price with current policy, create the Whop one-time variant (price, title "Micro Factory order <id>"), save `whop_variant_id`, status `quoted`, emit `quote`. `get_pricing_policy()`, `set_pricing_policy(policy, reason)` (clamped ±20%), `shop_metrics()` (queue length, orders/day, conversion, avg price).
- Production: `queue()`, `start_next_job()` (refuses unless bed_clear true, printer IDLE/FINISH, loaded colour matches; picks next paid order of the loaded colour first, else oldest), `printer_status()`, `pause_print(reason)`, `resume_print()`, `cancel_print(reason)`, `snapshot()` → png url, `set_loaded_colour(colour)`, `request_human(kind, details, order_id?)`.
- Support/finance: `list_orders(status?)`, `refund(order_id, reason)` (Whop refund; capped at `REFUND_CAP_CENTS=2000`, larger → `request_human qa`), `financials(days)` → revenue, Whop fees, filament cost ($0.02/g), generation cost, margin.
- Shared: `post_customer_update(order_id, text)` (writes an agent message + SSE), `log_decision(order_id?, decision, reason)`.

### Hermes fleet (`fleet/`)
One folder per profile: `intake`, `sales`, `production`, `support`, `growth`, `finance`. Each has `SOUL.md` (role, rules, voice), `config.yaml` (model; `mcp_servers.factory` with url + bearer + `tools.include` whitelist; toolsets limited to what the role needs; kanban on), and optional `skills/`. Plus `fleet/bootstrap.sh`, which creates the profiles inside the isolated Hermes install (`HERMES_HOME`) from these folders, idempotently.
- intake: Opus-class model. Customer-facing. Decides the path (template if a menu item fits; CadQuery for measured/functional parts; Meshy + finish for organic; combine for hybrid), asks at most 2 questions, publishes a design, explains it in ≤3 sentences, iterates. Never quotes a price it did not get from `prepare_quote`.
- sales: Sonnet-class. Runs on the `/accept` event and on an hourly cron: reviews `shop_metrics`, may adjust the pricing policy within bounds and logs why.
- production: Sonnet-class. Woken by payment, FINISH, failure and bed-cleared events. Batches by colour; asks for a spool swap only when no queued job matches the loaded colour.
- support: Haiku-class. Status questions after payment; refunds under the cap.
- growth: Sonnet-class, daily cron. Exa and Terac tools are configured but disabled until keys exist; writes a lead/idea note to Kanban.
- finance: Haiku-class, daily cron. `financials(1)` → a short P&L note on Kanban.

### Deploy (`deploy/`)
`docker-compose.yml` services: `hermes` (official Hermes image built from the Hermes repo, data volume `./data/hermes:/opt/data`, API server on 8642 with key, profiles bootstrapped on first start), `factory` (one image running the FastAPI service on 8080 and the MCP server on 9000; includes OrcaSlicer CLI for amd64 and arm64 via TARGETARCH, xvfb, cadquery), `mosquitto` (reserved for the Pi; local only), `cloudflared` (quick tunnel by default, named tunnel if `CF_TUNNEL_TOKEN` set). Works on Docker Desktop and OrbStack on Apple Silicon.

## IOS app (`ios/`)
- SwiftUI, iOS 17+, iPhone only, portrait. Builds two ways from the same sources:
  1. **xtool** (SwiftPM package + `xtool.yml`) so it builds on Linux. No asset catalogs, no storyboards, no Apple-only macros (no SwiftData); `@Observable` is fine.
  2. **XcodeGen** `project.yml` so it opens in Xcode on the Mac.
- Targets: `MicroFactoryCore` (models, API client, SSE client, no third-party deps) + `MicroFactoryApp` (UI). Voice (ElevenLabs Swift SDK) and payments (WhopCheckout) live in separate files behind `#if canImport(ElevenLabs)` / `#if canImport(WhopCheckout)`. Without them the app still builds: voice falls back to text, and pay opens `whop_purchase_url` in an `SFSafariViewController`.
- Config: base URL, app key and Whop company ID/`iap:read` key in a `Config.plist` the user edits, plus a hidden settings screen (long-press the logo) to change the base URL at runtime.
- Screens:
  1. **Shop:** product cards from `/catalog`, plus "Something else".
  2. **Capture:** up to 4 photos from the camera or library.
  3. **Measure:** ARKit two-tap distance (`ARView` raycast), shown in mm and added as a measurement chip. Manual entry is always available.
  4. **Order chat:** message list, live agent typing from SSE, photo/measure attachments, colour picker from `colours_in_stock`, and a hold-to-talk voice button.
  5. **Design preview:** SceneKit view of the USDZ (orbit, auto-rotate), dimensions label, "View on your desk" (AR Quick Look), "Change something", "Looks good" (→ `/accept`).
  6. **Quote:** price, colour, print time, ETA; Pay.
  7. **Live print:** `camera.jpg` refreshed every 2 s, progress ring, remaining time, status timeline.
  8. **My orders.**
- Voice: an ElevenLabs conversation started with a token from `/voice/token`. Client tool `send_to_agent(text)` posts to `/orders/{id}/messages` and returns "On it." When an agent message arrives over SSE, the app sends it into the voice session as a contextual update so the voice reads it out.
