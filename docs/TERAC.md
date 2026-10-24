# How Receipts uses Terac: humans as the exception handler

Receipts is run by agents. They bring in a verified human through the Terac MCP only when two things are
true: **the agent is unsure**, and **being wrong costs more than asking**. Most hours and most orders
never touch Terac. That is on purpose.

## The rule
Escalate only if `P(agent is wrong) x money at risk > cost of asking`.
Terac priced our tasks at $6 per person (fee included). Extra limits: at most $20 per escalation, one per
bot per day, and the Terac balance must stay at $40 or more.
When a trigger fires but the maths says no, the agent logs the skip (`Terac skipped: 0.05 x $44 = $2.20 < $12`).
Those logged skips are the evidence that it is rare by design.

## Three triggers
| | Bot | Fires when | Who it asks | Why a human |
|---|---|---|---|---|
| A. Stuck decision | CEO (hourly) | Leads are coming in but no sales, or two lead sources are tied, so the next move is a coin flip | 3 US adults who buy personalised gifts, 5 min | With almost no traffic there is nothing to learn from. Real people saying what stops them breaks the tie |
| B. Risky print | Production | Supplier rejected the file, or the printability report flags a problem, on an order big enough to matter | 2 people who 3D print regularly (screened on slicer use) | AI can't reliably judge whether a mesh will print. A failed print costs a refund plus supplier cost |
| C. Very complex design | Production | After the render is finished, the agent rates it 8/10 or harder (thin limbs, several figures, tiny text, overhangs) | Same 2 experts: a sanity check before manufacturing | The "would a pro print this?" judgement, bought only for the few designs where it matters |

Worked example (C): an $89 full-colour order with $30 supplier cost, P(fail) 0.35 -> $42 at risk > $12 -> ask 2 experts.
A $49 plaque from a known-good template, P(fail) 0.05 -> $3 -> skip.

## Guardrails
- The agents create Terac **drafts** themselves (free, already priced). The launch tool is removed from their
  toolset, so spending credit is one human click in the Terac dashboard. Terac's credit balance is a second
  hard cap ($100 loaded).
- No customer names, emails, addresses or original photos ever go into a Terac task: only the 3D viewer link.
- Two experts disagree -> the agent asks a human on the team instead of guessing.

## Wiring
- Terac MCP (`https://terac.com/api/mcp`, org API key) on the `ceo` and `production` Hermes profiles only
  (`fleet.yaml: terac: true`, rendered by `fleet/profiles.py`, key via `TERAC_API_KEY`).
- Shared skill `fleet/shared/terac-escalation/SKILL.md`: the gate, the steps and the two known-good templates.
- Terac project "Receipts: agent escalations" holds every escalation.

## Log
- Oct 24: wired in. First run: CEO created both template drafts in the project
  (C expert check of a render, 2 experts, $12; A site first-impression test, 3 testers, $18). Both left as drafts.
