---
name: terac-escalation
description: "Use when a Terac trigger fires (CEO stuck decision, risky print, very complex design). Gate, draft, log."
---

# Terac escalation: bring in a human only when it pays

Terac (MCP tools `terac_*`) sends a task to identity-verified humans. **The default is not to call it.**
Most hours and most orders never touch Terac. That is the design, not a gap.

## The gate (all three must hold)
1. **A trigger fired** (see your SOUL.md: CEO = A, production = B or C).
2. **Expected loss beats the human cost:** `P(you are wrong) x money at risk > cost of the draft`.
   Terac priced our tasks at **$6 per person** (fee included): 2 experts = $12, 3 testers = $18.
3. **Budget:** draft total <= $20, at most **one escalation per bot per day**, and the Terac balance
   stays >= $40 after it. Check with `terac_list_opportunities` (look for one you made today, by
   `internal_title` prefix `[ceo]` or `[production]`) and `terac_get_context` (balance). Only call
   these two once conditions 1 and 2 already hold: never poll Terac "just to check".

If 1 holds but 2 or 3 don't, **skip and say so** in the event you already post, e.g.
`Terac skipped: P(wrong) 0.05 x $44 = $2.20 < $12`. Logged skips are the evidence that this is rare on purpose.

## How to escalate
1. `terac_create_opportunity` with the matching template below. Change only the links, the
   description details and `num_participants`. Always project `a1rrfs82zarkorqgwraxag44`
   ("Receipts: agent escalations"). The call can take up to 3 minutes; wait for `pricing`.
2. This creates a **DRAFT** (free, no recruitment). The launch tool is excluded from your toolset on purpose.
   A human launches from the draft link: Terac requires owner sign-off before spending, and that one
   click is our only human step here.
3. `queue_reply(kind="note", text=...)`: trigger, the expected-loss maths, cost from `pricing`, and
   `links.dashboard.draft_editor` exactly as returned. Say what the agent will do with the answer.
4. `post_event(kind="terac", text=...)`: one line, no customer data. E.g.
   `Escalated to Terac: complex figure, P(fail) 0.35 x $64 = $22 > $12 for 2 expert opinions (draft)`.
5. On a later run, if the opportunity is live: `terac_get_submissions` -> read -> act (production:
   place / re-render / refund; CEO: one change) -> `terac_approve_submission` for real answers.

## Privacy
Never put customer names, emails, addresses, order ids or original photos in a Terac task. Link the
render viewer (`https://trovefactory.shop/r?id=<render id>`) or a public page only.

## Templates (known-good: created successfully on Oct 24)

### A. CEO stuck decision: 3 US adults, what stops people buying
```json
{"title":"5-minute first impression of a custom gift website",
 "internal_title":"[ceo] stuck-decision check: what stops people buying",
 "description":"Look at a small website that turns your online wins (a viral post, a launch, a milestone) into a 3D printed trophy. Tell us honestly what you'd expect, what's confusing, and what would stop you buying. About 5 minutes, no purchase needed.",
 "project_id":"a1rrfs82zarkorqgwraxag44","num_participants":3,"business_type":"b2c",
 "unrestricted_audience":true,"customer_screening_review":"auto_invite",
 "screening_questions":[{"key":"gifts","text":"Which of these have you bought online in the last 6 months?","pick":"any","answers":[
   {"text":"A personalised or custom-made gift","qualify_logic":"must_one_of"},
   {"text":"A framed print, plaque or award","qualify_logic":"must_one_of"},
   {"text":"Groceries or household items","qualify_logic":"may"},
   {"text":"Clothes or shoes","qualify_logic":"may"},
   {"text":"None of these","qualify_logic":"reject"}]}],
 "tasks":[{"sequence":1,"task_type":"file_upload","review_type":"manual_review",
   "title":"Look at the site and upload your answers",
   "description":"1. Open <PAGE URL> on your phone or computer and look around for about 3 minutes. Do not buy anything.\n2. Answer in 3-5 lines: (a) in one sentence, what does this site sell? (b) what was confusing or felt untrustworthy? (c) the main thing that would stop you buying, (d) a price you'd find fair for the cheapest item.\n3. Save as a .txt or .pdf, or take a screenshot of your notes, and upload it.",
   "instructions":"Upload one file with your four short answers (what it sells, what's confusing, what would stop you buying, a fair price).",
   "accepted_mime_types":["text/plain","application/pdf","image/*"],"min_files":1,"max_files":3}]}
```

### B / C. Production expert check: 2 experienced 3D printers review a render before it is printed
Use 2 people (minimum study budget is $5; two opinions also let you spot disagreement: if they
disagree, queue a note for a human instead of guessing).
```json
{"title":"Quick expert opinion: is this 3D model printable as designed?",
 "internal_title":"[production] pre-production expert sanity check",
 "description":"We 3D print custom figurines. Before sending one to the printer, we want a 3D printing expert's opinion. Open the model (link in the task), rotate it, and tell us whether it will print cleanly in PETG at the planned size, and what you would change. About 10 minutes.",
 "project_id":"a1rrfs82zarkorqgwraxag44","num_participants":2,"business_type":"b2c",
 "unrestricted_audience":true,"device_types":["desktop"],"customer_screening_review":"auto_invite",
 "screening_questions":[
  {"key":"printing","text":"Which best describes your experience with 3D printing?","pick":"one","answers":[
    {"text":"I design my own models and print them regularly","qualify_logic":"must"},
    {"text":"I regularly print models other people designed","qualify_logic":"must"},
    {"text":"I have printed something once or twice","qualify_logic":"reject"},
    {"text":"I have never 3D printed anything","qualify_logic":"reject"}]},
  {"key":"slicer","text":"Which of these tools have you used in the last 3 months?","pick":"any","answers":[
    {"text":"PrusaSlicer, Cura, Bambu Studio or OrcaSlicer","qualify_logic":"must_one_of"},
    {"text":"Blender, Fusion 360 or another CAD/3D modelling tool","qualify_logic":"may"},
    {"text":"Photoshop, Canva or another 2D design tool","qualify_logic":"may"},
    {"text":"None of these","qualify_logic":"reject"}]}],
 "tasks":[{"sequence":1,"task_type":"file_upload","review_type":"manual_review",
   "title":"Review the model and upload your notes",
   "description":"1. Open the model: <RENDER VIEWER URL> (drag to rotate).\n2. Planned print: <MATERIAL/PROCESS>, about <SIZE> cm tall, printed by a print farm.\n3. Write 3-6 lines: (a) will it print cleanly as-is: yes / with fixes / no, (b) the riskiest part (thin features, overhangs, floating pieces, small text), (c) what you would change.\n4. Save it as a .txt, .pdf or a screenshot with notes and upload it.",
   "instructions":"Upload one file with your verdict (yes / with fixes / no), the riskiest part, and what you would change. A .txt, .pdf or annotated screenshot is fine.",
   "accepted_mime_types":["text/plain","application/pdf","image/*"],"min_files":1,"max_files":3}]}
```
