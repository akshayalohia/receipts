# Printer pipeline: Bambu A1 control, slicing, camera, Pi sensors, network

## Recommendations (pick / runner-up)
| # | Decision | Pick | Runner-up |
|---|---|---|---|
| 1 | Printer control | LAN-only + Developer Mode, MQTT 8883 + FTPS 990 via `bambulabs_api` (fallback: raw paho-mqtt + ftplib) | `pybambu` from ha-bambulab. Avoid the cloud API |
| 2 | Headless slicing | OrcaSlicer 2.3.2 (stable, Mar 2026)[13] AppImage CLI under `xvfb-run` → `.gcode.3mf` | Bambu Studio CLI (same flags, official profiles land there first) |
| 3 | Live camera | Pi 5 + Camera Module 3 + **MediaMTX** (WebRTC/WHEP; LL-HLS fallback) | go2rtc |
| 4a | Sensors | BME280 + door reed switch → **Mosquitto on the laptop** | HTTP POST to the server |
| 4b | Failure detection | Vision-LLM check of a Pi snapshot every 2–3 min, auto-pause over MQTT | Obico self-hosted |
| 5 | Network | GL.iNet Beryl AX private LAN + **Cloudflare Tunnel** from the laptop | Phone hotspot as the router's WAN |
| 6 | Physical ops | Human clears the bed (team member now, Terac task later) | SwapMod automatic plate changer |

## 1. Printer control
- Bambu's Authorization Control has been live on A/P-series since June 2025.[4] In cloud mode and normal LAN mode, starting prints from non-Bambu software requires Bambu Connect, and movement/temperature/AMS control is restricted. Status pushes still work.[1]
- With **Developer Mode** on, third-party software works without changes and needs no authorization, but the printer can't use the cloud.[1] It opens MQTT, the live stream and FTP.[2] The A1 has had it since firmware 01.05.00.00.[3] Latest A1 firmware: 01.08.01.00 (2026-06-03).[5]
- **Printer setup:** Settings → LAN Only Mode → ON → Developer Mode → accept notice (toggle turns green).[2] Write down the IP, serial and 8-digit access code (if the code shows all zeros, toggle LAN-only off and on). Power-cycle once. **Insert a microSD card** (uploads land there). Bambu Handy stops working.[3]
- **Flow:** FTPS implicit TLS on port 990, user `bblp`, password = access code; upload `job.gcode.3mf`. Then publish to `device/<SERIAL>/request`: `{"print":{"command":"project_file","param":"Metadata/plate_1.gcode","url":"ftp:///job.gcode.3mf","bed_type":"textured_plate","use_ams":false,"bed_leveling":true,...}}`. Watch `device/<SERIAL>/report` for `gcode_state` going PREPARE → RUNNING → FINISH.[10] Full template, plus pause/resume/stop/pushall: ha-bambulab `commands.py`.[8]
- **Gotcha:** Python `ftplib` needs an implicit-TLS subclass. `storbinary` can hang at TLS `unwrap()`, so send the data, close the TCP socket, then read the 226 reply.[10]
- **Libraries:** `bambulabs_api` (MIT, Python ≥3.10) has `start_print_3mf(filename, plate_number, use_ams, ams_mapping…)`, `upload_file`, and camera frames.[6][7] ha-bambulab's `pybambu` is the most-used reference for MQTT payloads.[8][9] Latest release versions not checked.
- **Cloud API:** don't use it. It's unofficial. Bambu acted in 2026 against a client impersonating Bambu Studio and says cloud access falls under its user agreement.[25] It also needs venue internet.

## 2. Headless slicing and quotes
- Command: `xvfb-run -a AppRun model.stl --load-settings "machine.json;process.json" --load-filaments "pla.json" --orient 1 --slice 0 --export-3mf out.gcode.3mf`.[10] Bambu Studio CLI uses identical flags; Bambu updates its own profiles first.[11]
- The output zip holds `Metadata/plate_N.gcode`, its `.md5`, and `Metadata/slice_info.config` with slice stats and filament use.[12] For the **quote**, parse `prediction` (seconds) and filament `used_g` / `weight` from `slice_info.config`.[29] Price = grams × $/g + hours × machine rate + margin.
- **Gotchas (A1, tested on Orca):**[10]
  - Flatten the profile `inherits` chains into single JSON files.
  - Error `-17` ("process not compatible") is fixed by adding `""` to `compatible_printers` in both the process and filament JSON.
  - Set `curr_bed_type: "Textured PEI Plate"` in machine/process settings, or the G-code comes out with Cool Plate temperatures.
  - Use `--orient 1`: the A1 is a bed-slinger, so tall parts wobble.
- **External spool:** since firmware 01.08, plain G-code prints default to the external spool.[5] Send `use_ams:false` unless an AMS lite is mapped. Get one known-good slice → upload → print working before 11am; then only the STL changes.

## 3. Camera
- The A1 has a built-in "low rate" camera (up to 1080p).[15] Over LAN it's a TLS JPEG stream on TCP port 6000 at 1280×720,[14] but only ~1 fps.[16] Fine for snapshots, not for a "live" feed.
- **External camera:** MediaMTX supports Pi cameras natively (`source: rpiCamera`, path `/cam`).[17] The Pi 5 has **no hardware H.264 encoder** and uses software x264;[19] MediaMTX added a software encoder for this.[17] Use 720p30. A Zero 2 W also works (cheaper, hardware encoder, weaker CPU [inferred]).
- **Remote phone:** Tailscale Funnel is TCP-only, ports 443/8443/10000, bandwidth-capped and in beta.[21] It only carries TLS-terminated TCP,[22] so it can't carry WebRTC media. Instead:
  - Use Cloudflare Tunnel for the WHEP signalling and HLS (HTTP).
  - Add Cloudflare TURN to MediaMTX `webrtcICEServers2` so remote WebRTC media gets relayed (MediaMTX supports TURN/ICE-TCP).[18] Cost: $0.05/GB, first 1,000 GB free.[23]
  - Fallback: LL-HLS through the tunnel (~2–5 s latency [inferred]).
- go2rtc is comparable (WebRTC on port 8555, "zero-delay"),[20] but MediaMTX's built-in Pi camera support and docs win.

## 4. Sensors and failure detection
- **Worth it:** BME280 (I²C; temperature/humidity) and a reed switch on the door/enclosure.
- **Skip:** HX711 spool scale (the A1 already has runout, odometry and tangle sensors),[15] and vibration sensors.
- **Optional:** an SGP40/MQ-2 VOC/smoke sensor for the safety story [inferred value].
- **Transport:** run Mosquitto on the laptop. The Pi publishes JSON to `factory/pi1/sensors` every 10 s. The server's printer bridge republishes A1 status to the same broker, giving one bus for Hermes bots.
- **Failure detection:** the A1 has no AI failure detection built in.[24] Obico on Bambu needs an OctoPrint + BambuPrinter-plugin bridge plus a self-hosted server: too heavy for 10 hours.[24] Instead:
  - Every 2–3 min, send the MediaMTX snapshot (or the A1's own JPEG) to a vision LLM: "spaghetti / detached / empty bed?"
  - On 2 consecutive fails, send MQTT `pause` and notify.
  - Cost: ~$0.002–0.01 per check [inferred].

## 5. Hackathon network (exact topology)
```
venue Wi-Fi (or phone USB tether) ──WAN── GL.iNet Beryl AX (repeater, SSID "factory", DHCP reservations)
   ├─ laptop (Ethernet): Hermes, Mosquitto, slicer, printer bridge, cloudflared
   ├─ A1 (Wi-Fi, LAN-only + Dev Mode, static lease)
   └─ Pi 5 (Wi-Fi): MediaMTX :8889 WHEP / :8888 HLS, sensors → MQTT
phone (any network) ─HTTPS─ Cloudflare edge ─tunnel─ laptop API + Pi stream; media via CF TURN
```
- Beryl AX costs $98.99.[26] Printing never needs internet, so a venue outage only breaks the remote app, not the print.
- A named tunnel needs a domain on Cloudflare; `trycloudflare` quick tunnels need no account but get a random URL [inferred].
- A Lovable app on HTTPS needs HTTPS stream URLs, which the tunnel provides.

## 6. Physical ops
- Still manual: removing the part, re-seating or cleaning the plate, filament swaps.
- **MVP:** after FINISH, the agent posts a "clear bed" task (to a teammate, or Terac). The next job only starts once a vision check confirms the bed is empty.
- **Product:** Terac covers "physical-evidence tasks", paid on verified completion.[28] Local bed-clearing/packing gigs are unconfirmed [inferred]. The SwapMod plate changer automates plate swaps on the A1.[27]

## Cost and latency
- Hardware [inferred]: Pi 5 ~$60–80, Camera Module 3 ~$25, BME280 ~$10, Beryl AX $99.[26] Software is free; TURN has a 1,000 GB free tier.[23]
- Per print: PLA ~$0.02/g plus the LLM checks [inferred].
- Latency [inferred]: slice 10–60 s, FTPS upload a few seconds, print start (heating + leveling) 2–5 min, WebRTC LAN <0.5 s.

## Risks (10-hour build)
- A firmware OTA could change behaviour: keep the A1 offline in LAN-only mode.
- Slicer profile bugs: solve in the first hour.
- The printer's 2.4 GHz-only Wi-Fi [unverified]: set the router's 2.4 GHz band.
- TURN setup slipping: ship HLS first.

## Sources

[1] https://wiki.bambulab.com/en/software/third-party-integration
[2] https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode
[3] https://help.simplyprint.io/en/article/bambu-lab-lan-only-mode-and-developer-mode-how-to-enable-xa0hch
[4] https://all3dp.com/4/bambu-labs-controversial-authorization-control-hits-budget-3d-printers
[5] https://wiki.bambulab.com/en/a1/manual/a1-firmware-release-history
[6] https://pypi.org/project/bambulabs-api
[7] https://bambutools.github.io/bambulabs_api/api/mqtt_client.html
[8] https://github.com/greghesp/ha-bambulab/blob/main/custom_components/bambu_lab/pybambu/commands.py
[9] https://github.com/greghesp/ha-bambulab/releases
[10] https://yasu-home.com/bambu-a1-headless-orcaslicer-cli
[11] https://printago.io/blog/bambu-studio-cli-reference
[12] https://printago.io/slicer-cli/export-3mf
[13] https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.3.2
[14] https://github.com/Doridian/OpenBambuAPI/blob/main/video.md
[15] https://bambulab.com/en-us/a1/tech-specs
[16] https://blog.octoeverywhere.com/full-frame-rate-webcam-streaming-for-bambu-lab-3d-printers
[17] https://mediamtx.org/docs/publish/raspberry-pi-cameras
[18] https://mediamtx.org/docs/features/webrtc-specific-features
[19] https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-010033-WP-1-H.264%20encoding%20
[20] https://github.com/AlexxIT/go2rtc
[21] https://tailscale.com/docs/features/tailscale-funnel
[22] https://github.com/tailscale/tailscale/issues/14240
[23] https://developers.cloudflare.com/realtime/turn/faq
[24] https://www.obico.io/blog/ai-failure-detection-remote-control-bambu-lab-3d-printers
[25] https://blog.bambulab.com/setting-the-record-straight-on-cloud-access-and-community
[26] https://www.gl-inet.com/en-us/products/gl-mt3000
[27] https://simplyprint.io/features/autoprint/innocube3d-swapmod
[28] https://terac.com/mcp
[29] https://github.com/estampo/bambox/issues/101
