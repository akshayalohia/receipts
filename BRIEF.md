# Micro Factory: shared research brief

Read this first. Then do only your own topic and write `research/<topic>.md`.

## The product (Akshaya's spec, 2026-10-24)
An AI-agent-run 3D-print business ("micro factory").
- **Backend:** Hermes Agent (Nous Research) runs a fleet of bots that handle all business ops/workflow.
- **Consumer app (mobile):** user snaps photos of anything, takes measurements, talks (voice) and chats with the agent. Agent returns a 3D model/render; user iterates in chat. When happy, agent gives a quote; user pays live in-app.
- **Fulfilment:** on payment, the model is sliced and sent to a **Bambu Lab A1** which starts printing. A camera on the printer streams a live feed viewable in the app once printing starts. Sensors + camera hooked to a **Raspberry Pi** that connects to the central server.
- **Server:** a laptop for the demo/prototype.
- **Required sponsor tools:** **Whop** for all business stuff (payments, storefront, customers), **Exa** for any search, **Lovable** (app/front end). **Terac** (MCP that lets agents hire verified humans) is optional.
- **Context:** built for the Terac "Zero-Human Company Hackathon", Sat Oct 24 2026, 8:30am-8:30pm ET at Whop HQ, Brooklyn. Judges want an agent that runs a business on its own (decides, operates, executes). ~9-10 h of build time, venue wifi likely bad. The plan should cover the hackathon MVP and the path to a real product.
- Prior brainstorm notes: `research/prior-idea-notes.md` (concept only; nothing built).

## Rules for research workers
- Current facts only (today is 2026-10-24). Verify versions, prices, API availability, and model quality claims from official docs/pricing pages or credible recent benchmarks. Mark anything inferred as inferred.
- Output: `research/<topic>.md`, **max ~900 words**, terse bullets, no padding. Structure: Recommendation (one pick per decision + runner-up), why (1-2 lines), concrete integration notes (endpoints, libs, gotchas), cost per unit, latency, risks for a 10-hour hackathon build, sources (URLs).
- Done when: the file is written with a clear pick for every decision in your topic.
- Out of scope: writing app code, signing up for accounts, spending money, other workers' topics.
- Time bound: aim for ~25 minutes. Ship from the evidence you have.
- Do only what's listed. Mention anything else in one line; don't act on it. Verify once, then stop.
