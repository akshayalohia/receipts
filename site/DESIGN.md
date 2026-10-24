# Receipts site design

Concept: **thermal receipt meets trophy case.** The page is a sheet of warm paper. Type is set like
engraved plaque lettering (tall condensed display) and printed till roll (mono). The 3D object is
the hero; everything else is quiet ink on paper so the object reads as the trophy on the shelf.

Design read: consumer landing + builder for X users arriving on mobile, thermal-receipt / trophy-case
language, native CSS on Astro with vanilla TS, no design system.
Dials: DESIGN_VARIANCE 6, MOTION_INTENSITY 4, VISUAL_DENSITY 4 (home, make) / 7 (live).

## Palette (one theme, light, locked)

| token | hex | use |
|---|---|---|
| `--paper` | `#F2EEE4` | page background (warm thermal paper) |
| `--paper-hi` | `#FBF9F4` | receipt strip, inputs |
| `--ink` | `#151515` | text, borders, primary rules |
| `--ink-2` | `#55524B` | secondary text (about 6.7:1 on paper) |
| `--rule` | `#C8C1B2` | hairlines, dotted rules |
| `--red` | `#C21F17` | the one accent: receipt-printer red. Primary buttons, TOTAL line, live progress, focus ring |

No gradients (the torn receipt edge uses a CSS mask, not a visible gradient). No glass, no glow, no
indigo/violet. Shadows: none, except one hard 4px ink offset on the receipt strip (paper on a desk).
Theme is light only on purpose: it is paper. `color-scheme: light`.

## Type (self-hosted OFL via @fontsource, bundled into dist)

- Display: **Big Shoulders Display** 800/900. Tall, condensed, plaque-engraving feel. Headlines, prices, big numbers.
- Body: **Archivo** 400/600. Sub copy, FAQ answers, legal pages.
- Mono: **JetBrains Mono** 400/700. Receipt strip, labels, live feed, numbers in stats.
- Not Inter, not system-ui, not Space Grotesk. No serif.
- Scale: hero `clamp(3rem, 9vw, 7.5rem)` line-height 0.92, uppercase off (copy is sentence case).
  Section heads `clamp(2rem, 5vw, 3.5rem)`. Body 1.0625rem / 1.55, max 62ch.

## Shape

All-sharp: radius 0 everywhere. Borders are 2px ink for controls, 1px dotted `--rule` inside receipts.
Buttons: 48px tall min (44px target minimum everywhere), ink border, red fill for the single primary
action per screen, paper fill for secondary.

## Pages

- **Home `/`**: nav (wordmark left, "Watch it live" right). Split hero: left-aligned headline, sub, input
  bar (input + "Make mine") and the small "Free 3D preview" line; right side the 3D object, large.
  Mobile: copy and input first, object below at 70vw tall. Under the hero a full-bleed ink band = live strip
  (mono, revenue of $2,000, time left, link). "Pick your receipt": horizontal scroll-snap row of four
  objects (rendered with `snapshot()` from the preview, placeholder slot until it loads), name + price in
  display type, one line under. Founding line in mono. "How it works": three big display numerals in a
  row with a dotted rule between, stacks on mobile. FAQ: `<details>` list. Footer in mono.
- **Make `/make`**: two columns at ≥ 960px. Left: step 1 product switch (segmented, 4 options), step 2
  fields, step 3 shipping. Right (sticky): preview canvas with caption and "Save the preview", then the
  receipt strip with pay button and Whop element under it. Mobile order: step 1, preview, step 2,
  receipt, step 3, pay. The receipt strip prints line by line as fields fill.
- **Claim `/c/<slug>`**: split like the hero: headline + sub + two buttons (Claim it red, Gift it to them
  paper) left, the pre-made object right. Small disclaimer line in mono.
- **Order `/order`**: one receipt strip centred in a narrow column with the status line as its body.
  (Centering is allowed here: it is a single message.)
- **Live `/live`**: Monitor surface, density 7. Headline + sub top-left. Grid of panels with ink borders:
  Revenue (huge display number + 20-segment meter, one segment per $100, filled segments red), Orders,
  Time left (ticking hh:mm:ss). Right column: a tall receipt roll of agent events, newest at top, mono,
  timestamp + agent + text. Mobile: one column, feed last.
- **Terms / Privacy / Shipping**: plain prose column, 62ch, Archivo, h1 in display.

## Motion rules (MOTION 4)

- Receipt lines print in: each new line drops 0.4em and fades in over 180ms, `steps()`-free ease-out.
  Reason: it reads as the printer feeding paper as the order gets built.
- Hero headline and object fade up once on load (300ms). Reason: hierarchy, object arrives last.
- Buttons: `:active` translateY(1px). Live feed: new events print in like receipt lines.
- Only `transform` and `opacity`. No loops, no marquee, no parallax.
- `prefers-reduced-motion: reduce` turns every transition and animation off.

## Slop check (done before build)

- Gradients: none. Glassmorphism: none. Emoji: none. Indigo/violet: none.
- Icon-topped feature cards: none (products are rendered objects; how-it-works is numerals).
- Left accent rails: none. Centered everything: only `/order`, by intent.
- Fake stats: none. Live numbers come from `/api/stats`; zeros show as zeros.
- Stock imagery: none. Product images are preview renders or a labelled placeholder slot.
- Eyebrows: none. Em-dashes in visible copy: none. Copy is from `docs/site-copy.md`; gaps are `TODO(copy)`.
- Revision after check: dropped the barcode idea on the receipt strip (decorative fake), dropped a
  dark /live theme (would break the theme lock), replaced a filled progress track with a segmented meter.
