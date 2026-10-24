# Receipts: one-page plan (Oct 24, 11am–11pm, $2,000 through Whop)

**Pitch:** "We 3D print your receipts." Bots find people the moment they win something online, design the trophy before asking, and sell it with one tap on Whop. Zero humans in the loop except clicks we're not allowed to automate.

## Products (all made by code from a screenshot or link, so generation never fails)
| Product | Price | Source | Made by |
|---|---|---|---|
| Tweet trophy (raised tweet + like count) | $29 | tweet link | Slant 3D, PETG |
| Milestone plaque (revenue, MRR, subs, stars, followers) | $49 | screenshot | Slant 3D, PETG |
| Full-colour "Receipt" (the screenshot itself in full photo colour, on a stand) | $89 | screenshot or photo | Craftcloud full-colour partner |
| Team pack (10 with your logo) | $249 | logo | Slant 3D |
Founding Edition #001–100, numbered. Ships in 2–7 days depending on tier; paid today = revenue today. Final prices get set after the first API quotes (target ≥ 60% margin after print + shipping + Whop fees).

## Production: no local printing, suppliers print and ship
On `payment.succeeded`, the production bot sends the generated file straight to a supplier with the customer's address. Nobody on the team touches a part.
- **Slant 3D API (default).** US print farm, 99.5% of orders ship in under 2 business days. REST API with webhooks at every step (queued, printing, QC, shipped), plus a public MCP server at `slant3d.com/mcp` for quoting. PLA/PETG in many colours. One colour per piece; ask Slant whether a two-colour base + lettering is possible. Covers tweet trophies, milestone plaques and team packs.
- **Craftcloud (by All3DP) API for full colour.** An aggregator across ~150+ print shops, some offering full-colour printing (HP Multi Jet Fusion colour, PolyJet). Upload → price → cart → order through its v5 API. Slower (about 1–2 weeks) and pricier, so it's only for the $89 premium tier. Backup: Marketiger3D full-colour PolyJet API (EU, sells to US).
- **Fallback:** Shapeways orders API (OAuth, card on file) if either of the first two fails onboarding.
- The production bot quotes before checkout so price and shipping always clear margin, tracks supplier webhooks, and emails the customer tracking. Failed or rejected prints get auto-reordered or refunded through Whop.
- **Still to verify today:** Slant API key and live pricing for our plaque sizes; Craftcloud full-colour availability for a US delivery address. One test order each, shipped to one of us.

## The core move: a "claim page" for every lead
For every lead, the bots pre-build `receipts.<domain>/c/<handle>`: their actual post as a rotating 3D trophy, the price, Whop checkout, and a "gift it to them" button for friends. Outreach never says "check out our store"; it says "we already made yours."

## Outreach engines (bots find, design and write; send rules below)
1. **X breakouts.** Every 10 min: posts with likes ≥ 20× the author's usual (or ≥ 1k likes on accounts under 5k followers) in the last 6 h. Source: X API search, Solari browser on X advanced search as backup. The bot renders their trophy, builds the claim page and drafts a short, specific reply.
2. **LinkedIn "thrilled to announce".** New jobs, promotions, funding rounds, launches. Exa finds the posts; the bot makes the trophy. Pitch both to the person and their company (team packs).
3. **The plaque YouTube won't give you.** Creators who just crossed 1k / 10k / 50k subs (their "THANK YOU 10K" videos, Social Blade). YouTube only sends a Play Button at 100k. Contact through the business email on their channel. Same for TikTok follower milestones.
4. **Builders.** Product Hunt top 5 of the day, Show HN front page, GitHub repos crossing 1k / 10k stars, Devpost hackathon winners this weekend. Exa + Solari pull the lists; email or X.
5. **Whop sellers.** Public revenue screenshots posted by Whop creators. Native buyers with saved cards.
6. **Fun streaks for reach.** Duolingo 365-day streaks, chess rating milestones, marathon times. Cheap tweet trophies, high shareability.

**Send rules (keeps accounts alive):** X bans automated replies triggered by searches, so the bot queues each reply (text + render + link) and one of you taps Post from a real account. That's about 60–90 a person per hour, with every word written by the bot. Emails go out from the brand domain at a low daily volume with an opt-out line. Reddit: one honest launch post in r/3Dprinting and r/SideProject from a human account, no comment spam.

## Stunts (the parts people screenshot)
- **"It's already on its way."** For the 3–5 biggest breakouts of the day, the bots don't ask: they order the trophy from Slant on express, then reply with the render and the live tracking link. "An AI saw your tweet blow up and shipped you a trophy." ~$20–30 each, and the reply itself is the ad. Terac hires a person to film the reveal when the trophy lands, for ad creative.
- **The challenge page.** "An AI company has 12 hours to make $2,000." Live revenue vs goal, every order's supplier status (queued → printing → shipped), every bot decision in a feed. The CEO bot posts hourly updates on X.
- **Tag-to-print.** Reply "@receipts print this" under any tweet → render + claim page in 2 min (mention-only, allowed).
- **In the room.** Every team gets a render of its logo trophy and a $249 pack offer. Pitch Whop/Terac to buy the winners' trophies.

## Ads (secondary, ~$100–150)
Whop Ads charges nothing on top of the ad spend, so it costs the same as Meta direct, with better account standing and Whop's buyer data; a card works. Use it for Instagram/Facebook retargeting of claim-page visitors and lookalikes. Put about half the budget into X Ads boosting the best-performing post to followers of build-in-public accounts (closer audience). Ads bot: shift budget every hour by cost per sale, kill anything over $25/sale, reinvest 20% of revenue.

## Bot fleet (Hermes)
CEO (targets, hourly post, budget) · Scout (breakout and milestone detection: X, Exa, Solari) · Designer (trophy + claim page) · Closer (writes replies/emails, answers chat) · Ads · Production (quotes, routes orders to Slant/Craftcloud, tracks webhooks, reorders or refunds) · Hiring (Terac reaction videos, street samples) · Finance (live P&L, reinvest rule).
**Sponsor fit:** Exa = lead engine (LinkedIn, PH, YouTube, builders). Solari = browser agents for sources with no API + checkout QA. Terac = bots hire filmers and street promoters. Whop = checkout, ads, affiliates (30%), Content Rewards for livestream clips.

## Revenue math (guesses, not forecasts)
Room + team packs $500–1,000 · X/LinkedIn claim pages (≈400 leads × 3% × $40) ≈ $500 · creators and builders (≈150 × 6% × $55) ≈ $500 · challenge page, tag-to-print, ads $300–600. **≈ $1.8–2.6k.**

## Timeline
- **10–11:** you do accounts (below); coder builds the site, generators, claim pages, Whop checkout.
- **11:00:** live. Room pitches begin; first challenge post.
- **11–1:** scout + designer + closer live on X breakouts and Product Hunt; reply queue to you three.
- **1–3:** LinkedIn, YouTube, builders; ads on; first "already on its way" gifts.
- **3–11:** CEO bot reallocates hourly to whichever source has the best cost per sale.

## You three, now
Whop store + verification + $1 test · brand X handle + developer app (write) · Facebook page for Whop Ads · domain · Solari, Exa, Terac keys to Dit · Slant 3D API key + card on file · Craftcloud account + card · ask organizers if team-pack sales from other teams count.
