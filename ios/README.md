# Micro Factory iOS app

SwiftUI, iOS 17+, iPhone, portrait. `MicroFactoryCore` (models, API client, SSE client; Foundation only) + `MicroFactoryApp` (UI).
API contract: `../SPEC.md` "HTTP API". Optional SDKs: ElevenLabs (voice) and WhopCheckout (native pay).

## Config
Edit `Sources/MicroFactoryApp/Resources/Config.plist` (both builds bundle this file):
`API_BASE_URL` (the tunnel URL), `APP_KEY` (= server `APP_SHARED_SECRET`), `WHOP_COMPANY_ID`, `WHOP_IAP_KEY` (Whop `iap:read` key).
To change the server address at runtime, long-press the "Micro Factory" wordmark on the Shop screen.

## Build on Linux with xtool
1. Install the Swift 6.3 toolchain, `usbmuxd` and xtool (`xtool.AppImage`, renamed to `xtool` on your PATH), then run
   `xtool setup` once: it logs in to Apple (mode 1 "Password" works with a free Apple ID) and asks for an Xcode 26 `Xcode.xip`
   to build the iOS SDK. See https://xtool.sh/documentation/xtool/installation-linux
2. Set a unique `bundleID` in `xtool.yml` (keys used: `version`, `bundleID`, `infoPath`).
3. From this folder, with the iPhone plugged in over USB: `xtool dev`. It builds, signs and installs (pair the phone if prompted).
4. Without the SDKs: `MF_WITH_SDKS=0 xtool dev`. Drop just one: `MF_WITH_ELEVENLABS=0` or `MF_WITH_WHOP=0`.

## Build on a Mac with XcodeGen + Xcode
1. `brew install xcodegen`, then `xcodegen generate` in this folder.
2. `open MicroFactory.xcodeproj`, pick the `MicroFactory` scheme and your iPhone, then Run.
3. To build without an SDK, delete its entries under `packages:` and the app target's `dependencies:` in `project.yml`, then regenerate.
   The code uses `#if canImport(...)`. Without ElevenLabs the chat is text only; without WhopCheckout, Pay opens `whop_purchase_url` in Safari.

## Signing with a free Apple ID
- Xcode: Settings > Accounts > add your Apple ID. Target > Signing & Capabilities > Team = "(Personal Team)". Change the bundle id if it's taken.
- xtool: the Apple ID login happens in `xtool setup`; then `xtool dev`.
- On the phone: Settings > General > VPN & Device Management > trust your developer certificate. Turn on Developer Mode if asked.
- Free-account installs expire after 7 days. Reinstall to renew.

## Tests (Core only, no UIKit)
- Linux or Mac: `MF_CORE_ONLY=1 swift test`. That covers JSON decoding of every SPEC response and SSE payload, plus the SSE line parser.
- Xcode: the `MicroFactory` scheme > Test (`MicroFactoryCoreTests`).

## Notes
- Every request sends `X-App-Key` and `X-Device-Id` (a random id stored in UserDefaults).
- The order stream (`/orders/{id}/stream`) reconnects with backoff from 1 s up to 30 s, and the app re-fetches the order on each reconnect.
- Payment is confirmed only by the server's Whop webhook. The app just follows the order's `status`.
