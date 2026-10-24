# Micro Factory: PRD + build plan (v0.1, 2026-10-24)

An AI-run 3D-print shop. Snap a photo and talk; the agent designs it, quotes it, takes payment, prints it and streams the print live. Built on a Hermes bot fleet. Sponsor tools: Whop (money), Exa (search), Lovable (app), Terac (hired humans).
Research behind every pick: `research/*.md`, with sources.

## 1. User flow
1. **Capture:** open the app, snap 1–4 photos, type key dimensions if fit matters (card-in-photo for scale optional), talk or type.
2. **Design:** the agent asks 1–2 questions and returns a 3D preview in about 1–2 min. The user rotates it in-app.
3. **Iterate:** "2 cm taller", "add a keyring hole". A new preview arrives in under a minute.
4. **Quote:** price, print time and ETA, from the real slicer output.
5. **Pay:** Whop checkout embedded in the app.
6. **Watch:** the order goes to the A1; a live camera feed, progress % and ETA appear in the app.
7. **Done:** a "ready for pickup" push. The bed gets cleared, the next job starts.

## 2. Architecture
```
Phone (Lovable PWA) ──HTTPS── Supabase (auth, orders, messages, files, Realtime)
   │  voice (WebRTC)                 ▲ writes
   ▼                                 │
OpenAI GPT-Live-1 ──send_to_agent──► FastAPI (laptop, via Cloudflare Tunnel)
                                     ├─ /chat → Hermes /v1/runs (intake bot)
                                     ├─ /voice/session (mints voice token)
                                     └─ /webhooks/whop (payment.succeeded → production bot)
Hermes fleet (6 profiles) ⇄ Kanban ⇄ "factory" FastMCP server
   tools: generate_3d, make_cad, repair_mesh, slice, quote, print_start/status/pause,
          camera_snapshot, update_order, exa_search, whop_checkout, terac_task
FastMCP ⇄ Mosquitto (MQTT bus) ⇄ A1 (LAN + Dev Mode, MQTT 8883 / FTPS 990)
                                ⇄ Pi 5 (Camera Module 3 → MediaMTX WebRTC/HLS; BME280, door switch)
LAN: GL.iNet travel router (laptop, A1, Pi). Phones reach in through the Cloudflare Tunnel.
```
Key rule: **the browser holds no keys.** FastAPI owns the secrets and the Whop webhook.

## 3. Stack picks (runner-up in brackets)
| Layer | Pick | Why / note |
|---|---|---|
| App | Lovable mobile web app / PWA on Lovable Cloud (Supabase) [Capacitor wrap later] | Lovable can't build native apps. Camera uses `<input capture>`, preview uses `<model-viewer>`, video uses WHEP/hls.js |
| Voice | OpenAI **GPT-Live-1** with delegation to Hermes [gpt-realtime-2; Gemini 3.8 Live is cheapest] | $0.05/min. The voice model holds the conversation and hands the work to the agent. Text chat stays as the fallback |
| Agent backend | **Hermes** API server (`/v1/runs`, SSE) + profiles + Kanban | session_id = order_id |
| Glue | **FastAPI** + one **FastMCP** server shared by all bots | Per-bot tool whitelists |
| Vision / router | **Gemini 3.8 Flash** [Opus 5.5 for hard cases] | Labels each request organic / parametric / hybrid and asks for missing info. <$0.01/turn |
| Organic 3D (pets, figurines) | **Meshy 7.1** multi-image, mesh only [Tripo H3.1, $0.20, ~40 s] | ~$0.40, ~65 s, free printability check. Ranked #2 on human preference (Hi3D v3 is #1 at 5× the price) |
| Measured parts (brackets, stands, knobs) | **Claude Opus 5.5 writing CadQuery**, render-and-check loop ×3 [GPT-6 Astra; Zoo Text-to-CAD hosted] | Exact dimensions, deterministic edits. Tops CAD Bench V3 |
| Hybrid (pet keychain) | Meshy mesh ∪ CadQuery ring/base via **manifold3d** | |
| Mesh repair | trimesh + pymeshlab + manifold3d; scale, orient, add base, cap at 250 mm | Assert watertight before slicing |
| Slicer + quote | **Bambu Studio CLI** [OrcaSlicer 2.3.2 CLI] | Read `prediction` (s) and `weight` (g) from `slice_info.config` |
| Printer control | A1 in **LAN-only + Developer Mode**, `bambulabs_api` (FTPS upload + MQTT `project_file`) | Cloud API is unofficial and Bambu has acted against it: avoid |
| Live video | **Pi 5 + Camera Module 3 + MediaMTX** (WebRTC/WHEP, LL-HLS fallback) [go2rtc] | The A1's own camera runs at ~1 fps (snapshots only). Tailscale Funnel can't carry WebRTC, so use Cloudflare Tunnel + Cloudflare TURN |
| Sensors | BME280 (temp/humidity) + door reed switch → Mosquitto | Skip the load cell (the A1 has runout sensing) |
| Failure detection | Vision-LLM check of a snapshot every 2–3 min, auto-pause after 2 fails [Obico, too heavy] | A1 has no AI failure detection |
| Payments | **Whop**: checkout config per quote (metadata order_id) → embedded `<Checkout>` → `payment.succeeded` webhook | Fulfil **only** from the webhook. 2.7% + $0.30 |
| Search | **Exa** MCP + REST | Check Printables/Thingiverse/MakerWorld before generating; product dimensions; competitor prices; B2B leads. $10/mo free |
| Humans | **Terac** MCP, async only (~1 h human pricing) | Design QA review or customer interviews. "Agent hires a human when blocked" fits the brief |

## 4. Bot fleet (Hermes profiles)
| Bot | Job | Model | Tools |
|---|---|---|---|
| **intake** (orchestrator) | Talk to the customer, route organic vs CAD, iterate the design | Opus 5.5 | generate_3d, make_cad, repair, slice, Exa |
| **sales** | Price and quote, adjust price to the queue, create the Whop checkout | Sonnet | quote, whop_checkout |
| **production** | Slice, upload, print, watch the camera, pause on failure, call for bed-clear | Sonnet | printer, camera, sensors |
| **support** | Status questions, refunds and reprints within a set limit | Haiku/Sonnet | orders, Whop refund (capped) |
| **growth** | Daily Exa lead search, Terac interviews, draft offers | Sonnet | Exa, Terac |
| **finance** | P&L (Whop revenue − filament − API costs), daily report | Haiku | Whop MCP (read) |

- Customer chat goes straight to intake through `/v1/runs`.
- The Whop webhook calls the production bot **directly** through `/v1/runs`, not through Kanban, to avoid the 60 s dispatcher tick.
- Kanban carries back-office handoffs (growth → sales, production → support), so judges see the agent's decisions on the board.

## 5. Data (Supabase)
- `orders`: id, user, status, path (organic/parametric/hybrid), params JSON, model_glb_url, stl_url, grams, print_s, price, whop_checkout_id, payment_id, printer_job, stream_url, eta.
- `messages`: order_id, role, text, media_url (Realtime-subscribed by the app).
- `events`: order_id, actor (bot), type, payload. This is the audit trail and the "agent decisions" feed for the ops dashboard.
- **Status flow:** `draft → designing → review → quoted → paid → slicing → queued → printing → done → picked_up` (plus `failed`/`refunded`).

## 6. Pricing (starting formula; the sales bot tunes it)
`price = max($8, $3 base + grams × $0.06 + print_hours × $2.50 + gen_cost)`, plus a queue surcharge when >2 jobs are waiting. Our costs: PLA ~$0.02/g, generation $0.30–1, Whop 2.7% + $0.30.

## 7. Hackathon plan (today, 8:30–8:30)
**Before leaving:** install CadQuery, Bambu Studio and the CLI on the laptop. Export flattened A1 + PLA + Textured PEI profiles and slice one STL successfully. Pre-generate 3 demo models. Put the A1 in LAN + Dev Mode and write down IP, serial and access code. microSD in the printer. Flash the Pi with MediaMTX.

| Time | Milestone |
|---|---|
| 9:00–10:30 | **Golden path by hand:** STL → slice → FTPS → print starts. Pi stream visible on a phone. Whop sandbox checkout created by API. Terac request launched |
| 10:30–1:00 | FastMCP tools + FastAPI. Lovable app: capture, chat, preview, checkout, live view |
| 1:00–3:30 | Hermes profiles wired. Organic (Meshy) + CAD (CadQuery) paths. Webhook → print |
| 3:30–5:30 | Voice (GPT-Live), failure check, sensors, ops dashboard (events feed, P&L, Kanban) |
| 5:30–7:00 | Full end-to-end runs ×3, film a backup video, freeze code |
| 7:00+ | Demo: a judge orders on their own phone, pays, watches it print |

**4-way split:** (A) Lovable app + voice; (B) FastAPI + Hermes fleet + Whop/Exa/Terac; (C) 3D pipeline (Meshy, CadQuery, repair, slice); (D) printer, Pi, network, demo/pitch.

**Hardware list:** A1 + PLA spools, Pi 5 + Camera Module 3 + mount, BME280, reed switch, GL.iNet Beryl AX (~$99), microSD, ethernet cable, power strip.

## 8. Risks → mitigation
- **Venue wifi:** the travel router keeps printing local; tether the router to a phone for WAN; text fallback for voice; pre-recorded feed.
- **Slicer profile bugs:** solve first, then freeze. Only the STL changes after that.
- **Bad AI meshes:** always repair and check before slicing; keep pre-made backups.
- **Print time:** keep demo items under 20 min (keychains, name tags, small figurines).
- **Bed clearing is manual:** the agent posts a "clear bed" task (teammate today, Terac later); the next job waits for a vision check that the bed is empty.
- **New SDKs (GPT-Live, Whop Elements):** pin versions; Lovable SSR means client-only components for `<model-viewer>`/Checkout.

## 9. After the hackathon
1. Move the server from the laptop to the Ubuntu box; a named Cloudflare domain.
2. Multiple printers (queue + printer pool); SwapMod plate changer for continuous printing.
3. Capacitor-wrapped app for the App Store; native LiDAR measuring.
4. Shipping (label API) and local pickup lockers; Terac for packing and delivery if it supports physical gigs.
5. Multi-colour (AMS lite), more materials (PETG/TPU), B2B batch orders from growth-bot leads.

## 10. Open questions (owner)
Printer and AMS in hand? Pi model and sensors? Which laptop, and does Hermes run on it? PWA OK? Team and split? Whop/Exa/Lovable keys and API budget? Demo product list?
