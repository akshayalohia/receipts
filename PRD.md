# Micro Factory: PRD + build plan (v0.2, 2026-10-24)

An AI-run 3D-print shop. Snap a photo and talk; the agent designs the part, quotes it, takes payment, prints it and shows the print live. A Hermes bot fleet runs the business. Sponsor tools: Whop (money), Terac (hired humans), Exa (search) and Lovable (ops dashboard); Exa and Lovable get added last.
Research and sources: `research/*.md`.

## 1. User flow (native iOS app)
1. **Capture:** take 1–4 photos. Measure in AR (tap two points, ARKit) or type the sizes. Talk (voice) or type.
2. **Design:** the agent asks 1–2 questions, then shows a 3D preview in about 1–2 min. Rotate it, or tap "View in AR" to see it at real size on your desk.
3. **Iterate:** e.g. "2 cm taller", "red", "add a keyring hole". The new preview comes back in under a minute.
4. **Quote:** price, colour, print time and ETA, all from the real slicer output.
5. **Pay:** native Whop checkout sheet with Apple Pay. Card fees are 2.7% + $0.30; no App Store cut on physical goods.
6. **Watch:** printer camera feed, progress % and ETA.
7. **Done:** a "ready for pickup" notification. The agent requests a bed-clear and starts the next job.

## 2. Architecture
```
iPhone app (SwiftUI) ──HTTPS (Cloudflare Tunnel)──► factory-api (FastAPI)
  ├─ ElevenLabs voice (WebRTC) ──send_to_agent tool──┘   ├─ /orders, /chat (SSE), files (GLB/USDZ/STL)
  └─ Whop iOS Checkout SDK                                ├─ /voice/token
                                                          └─ /webhooks/whop → production bot
Hermes (isolated Docker install, 6 profiles) ⇄ Kanban ⇄ factory MCP server (FastMCP)
  tools: route_request, generate_mesh (Meshy), make_cad (CadQuery), repair_mesh, slice (OrcaSlicer CLI),
         quote, create_checkout (Whop), print_start/status/pause, camera_snapshot, update_order, terac_task, exa_search*
factory MCP ⇄ Mosquitto ⇄ Bambu A1 (LAN-only + Developer Mode: MQTT 8883, FTPS 990, camera :6000)
            ⇄ Raspberry Pi (later: Pi camera via MediaMTX HLS, sensors)
```
Everything on the laptop runs as one `docker compose` stack: `hermes`, `factory-api`, `mosquitto`, `cloudflared`.
- **Isolated:** its own Hermes install and data volume, separate from Dit's.
- **Built and tested on akshaya-server first,** then moved to the Mac unchanged.
- **Secrets stay on the server.** The app ships only Whop's `iap:read` key, which is designed to sit inside an app.

## 3. Stack picks (runner-up in brackets)
| Layer | Pick | Note |
|---|---|---|
| App | **SwiftUI, iOS 17+, XcodeGen project** [Expo/React Native] | Whop's checkout SDK is Swift-only. ARKit measuring and AR Quick Look are native. Written on Linux, compile-checked on a GitHub macOS runner, sent to the Mac over Taildrop |
| 3D preview | SceneKit view of a server-made USDZ + AR Quick Look | Server converts GLB → USDZ |
| Live feed | v1: A1 camera snapshots relayed by the API (~1 fps). Later: Pi 5 + Camera Module 3 + MediaMTX HLS in AVPlayer | Pi deferred |
| Voice | **ElevenLabs Agents** (native Swift SDK, client/server tools) [OpenAI GPT-Live-1] | Mature mobile SDKs; GPT-Live is only 6 weeks old. ~$0.08/min plus LLM. Voice holds the conversation; heavy work goes through `send_to_agent` → Hermes. Text chat is the fallback |
| Agent backend | Hermes API server (`/v1/runs` + SSE), profiles, Kanban | `session_id` = order id |
| Glue | FastAPI + one FastMCP server; SQLite | App gets live updates over SSE. No Supabase needed |
| Router + vision | **Gemini 3.8 Flash** [Opus 5.5] | Sorts each request into organic / parametric / hybrid and lists missing info. <$0.01/turn |
| Organic 3D (pets, figures) | **Meshy 7.1** multi-image, mesh only [Tripo H3.1] | ~$0.40, ~65 s; free printability check |
| Measured parts | **Opus 5.5 → CadQuery**, render-and-check ×3 [GPT-6 Astra; Zoo Text-to-CAD] | Exact dimensions, deterministic edits. #1 on CAD Bench V3 |
| Hybrid | Meshy mesh ∪ CadQuery ring/base via manifold3d | e.g. pet keychain |
| Repair | trimesh + pymeshlab + manifold3d; scale, orient, add base, ≤250 mm | Assert the mesh is watertight before slicing |
| Slicer + quote | **OrcaSlicer CLI** (aarch64 AppImage exists, so it runs native on Apple Silicon) [Bambu Studio CLI] | `prediction` (s) and `weight` (g) from `slice_info.config` |
| Printer | `bambulabs_api`: FTPS upload + MQTT `project_file`, `use_ams:false` | Cloud API is unofficial: avoid |
| Failure check | Vision-LLM check on a camera snapshot every 2–3 min, auto-pause after 2 fails | A1 has no AI failure detection |
| Payments | **Whop**: sales bot creates a one-time variant per quote (metadata order_id) → app `checkout.purchase(variant)` → `payment.succeeded` webhook starts the print | Fulfil **only** from the webhook |
| Humans | **Terac** MCP, async (humans price each job, ~1 h) | Design QA, customer interviews, bed-clear/pickup if supported |
| Search (last) | Exa MCP + REST | Find existing models before generating; product dimensions; competitor pricing; leads |
| Dashboard (last) | Lovable web app | Live ops board for judges: orders, bot decisions, P&L, printer |

## 4. Bot fleet (Hermes profiles)
| Bot | Job | Model |
|---|---|---|
| **intake** (orchestrator) | Talks to customers, routes requests, designs and iterates | Opus 5.5 |
| **sales** | Prices, quotes and creates the Whop checkout; queue-based pricing | Sonnet |
| **production** | Slices, prints, watches the camera, pauses on failure, batches jobs by colour, requests spool swaps and bed clears | Sonnet |
| **support** | Status questions; refunds and reprints under a cap | Haiku |
| **growth** | Leads (Exa), customer interviews (Terac), offers | Sonnet |
| **finance** | P&L (Whop revenue minus filament and API costs), daily report | Haiku |

- The app's chat goes straight to intake through `/v1/runs`.
- The Whop webhook calls production directly, skipping the Kanban dispatcher's 60 s tick.
- Kanban carries the back-office handoffs, so the bots' decisions show on the board.

## 5. Single spool, many colours
- The app offers only the colours in stock. The production bot sets which spool is loaded.
- It batches the queue by colour. When the colour changes, it posts a "swap to red" task, to a teammate or through Terac, and waits for confirmation.
- A non-loaded colour adds $2 and some wait time.

## 6. Product menu (each prints in ≤25 min at 0.2 mm, PLA)
| Product | Path | Price | Example |
|---|---|---|---|
| **Pet / Mini-Me keychain** (40 mm) | hybrid | $12 | "Here's my dog", 3 photos |
| **Name tag / desk nameplate** | parametric | $8 | "AKSHAYA, bold, blue" |
| **Fix-it part** (knob, clip, cap, cable clip) | parametric | $10 | Photo of a broken blind clip + 2 measurements |
| **Perfect-fit holder** (AirPods case, phone, glasses) | parametric | $12 | Dimensions typed (Exa looks them up later) |
| **Figurine** (60 mm) | organic | $15 | "Me as a chess knight" |

**Pricing:** `max(menu floor, $3 + grams × $0.06 + print_h × $2.50 + gen_cost)`, plus a queue surcharge when more than 2 jobs are waiting. The sales bot may adjust within ±20%.
**Our cost per order:** about $0.50–1.50 (PLA ~$0.02/g, 3D generation $0.30–1).
**Demo:** a judge photographs their pet, it prints as a keychain, and they watch it live. Second order: a fix-it part from a photo plus measurements.

## 7. Data
- `orders`: id, status, product, path, params, colour, files (glb/usdz/stl/3mf), grams, print_s, price, whop_variant, payment_id, eta.
- `messages`: per-order chat.
- `events`: per-order audit trail of bot decisions (feeds the dashboard).
- **Status flow:** `draft → designing → review → quoted → paid → queued → printing → done → picked_up` (plus `failed`/`refunded`).

## 8. What Dit builds (after "go")
1. **Backend stack** (`backend/`): compose file, factory-api, factory MCP, 6 Hermes profiles with SOUL/skills, mock printer + mock Whop for offline tests. Tested end to end on akshaya-server: order → design → quote → mock payment → slice → mock print.
2. **iOS app** (`ios/`): all screens; ElevenLabs and Whop SDKs via SPM. Compiles clean on a GitHub macOS runner. Sent to your Mac by Taildrop as a zip.
3. **Setup kit** (`SETUP.md`): A1 into LAN + Dev Mode; `.env` keys; `docker compose up` on the Mac; Xcode signing (free Apple ID works on your own phone); ElevenLabs agent config; Whop webhook URL.

**Left for you:** keys, the printer's IP/serial/access code, one real test print, Pi + sensors (later), Exa and Lovable (last).

## 9. Risks
- **Venue wifi:** the travel router keeps printing local; tether a phone for the tunnel; text-chat fallback.
- **Slicer profiles:** pre-built and tested with a real A1 profile; only the STL changes per job.
- **Bad AI meshes:** always repair and check; keep pre-made backups for the demo.
- **Swift code can't be compiled on Linux:** CI compile check; first device run happens on your Mac.
- **Bed clear and spool swap are manual:** the agent asks a human (teammate or Terac) and waits for a camera check.
