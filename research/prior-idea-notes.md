# Akshaya's micro-factory hackathon idea: facts for E-Cup
Compiled 2026-10-23 by Dit from: Dit chat session 20261021_133317_43949a (desktop, "Hackathon hardware integration ideas Saturday"), the iMessage group "hackathon gc" (chat 1901, 2026-10-21), Hindsight banks (life-messages, akshaya-personal, personal-email), and a search for granola meetings/other sessions.

**Bottom line: the idea is about 2 days old and is a concept, not a built product.** Nothing is built or tested, no customers have been spoken to, and there is no pricing. Everything below is concept-stage. Items marked *Dit's proposal* came from Dit's brainstorm and Akshaya has only reacted to them ("i like the auto print shop, can you build on that"). They are not things he has decided or built.

## 1. Name and one-line pitch
- **Name:** none. Akshaya calls it "auto printing business" / "auto print shop" (iMessage, 2026-10-21; Dit chat, 2026-10-21). "Micro factory" is the word Dit's brainstorm used ("voice-first micro-factory run by an agent").
- **Pitch, in his words:** "auto printing business", plus "app for consumers to easily order cheap custom one-off stuff they want and super quickly" (iMessage, hackathon gc, 2026-10-21 18:15 UTC).
- **Pitch, working version (Dit's proposal, 2026-10-21):** a voice-first micro-factory run by an AI agent. You talk to it, and it designs, prices, prints and sells the custom item with no human running it.
- **Event:** Terac Zero-Human Company Hackathon, Sat 2026-10-24, 8:30am-8:30pm, Whop HQ, 300 Kent Ave, Brooklyn. The brief is to build an agent that operates a business with little to no human input. He is approved (Luma email 2026-10-19; ticket + Apple Wallet pass). Sponsors: Whop, Lovable, Exa. Terac's MCP lets agents hire verified humans (priced by hand, ~1 hr turnaround). Prizes, tracks and judging criteria were not posted as of 10-21. Organizer told Akshaya hardware integration is allowed.

## 2. How it works (all *Dit's proposal* unless noted; Akshaya's own statements are marked "A:")
- **A:** an automated 3D-printing business; he said "potentially" also Cricut (cutting/vinyl) and "anything else we might wanna add". **A:** a possible mobile consumer app for ordering cheap, custom, one-off items quickly. (iMessage chat 1901, 2026-10-21)
- **A:** he wants real-time voice as the way orders come in ("easy to do but big cool factor add") and asked to make the print shop "more impressive" (Dit chat, 2026-10-21).
- **Order -> design -> print -> ship flow (proposal):**
  1. Customer talks to the agent (real-time voice, e.g. OpenAI Realtime / ElevenLabs Agents / LiveKit; push-to-talk headset because the room is loud). Agent asks 1-2 follow-up questions.
  2. Design: speech -> 3D model via a text-to-3D API (Meshy, Tripo, etc.), preview on screen, price quoted from material cost, print time and queue length.
  3. Payment: Whop checkout / QR code (Whop is the hackathon sponsor with a payments + storefront API).
  4. Print: agent sends the job to the printer, a camera on the bed does vision QA (detects spaghetti/warping, stops the job, reprints, logs the cost) and the agent narrates progress. Two possible production lines: sticker/label printer (seconds) and 3D printer (~15-30 min for small parts); the agent decides which line each order goes on.
  5. Ship/hand-off: at the hackathon, the item is handed over at the table. For delivery or ambiguous design review the agent would hire a human through the Terac MCP.
- **Agent roles / business functions (proposal):** voice order-taker; designer; pricer (dynamic pricing, adjusted during the day); production controller (printer + camera QA); sales (uses Exa to find Brooklyn businesses/startups needing merch, stickers or prototypes, drafts quotes/offers on the Whop storefront); ops (filament tracking, reorder decisions, live P&L dashboard); "HR" (hires Terac humans for design review, fulfillment/delivery, customer interviews).
- **Stack (proposal):** Terac MCP, Whop (payments/storefront), Exa (lead search), Lovable (storefront + dashboard front end), a hosted realtime voice stack, a text-to-3D API, a slicer, a printer API (Bambu or OctoPrint), a camera. Printer run in LAN mode, not cloud, because venue wifi will be bad.
- **Printer setup:** UNKNOWN / unresolved. No printer is secured. On 2026-10-21 Akshaya asked Jo and Vrisag whether either has a 3D printer or knows someone he could borrow one from before Saturday. Jo said a friend in Baltimore has one (Jo to ask about borrowing it and whether it is internet-connected). Anush asked whether it is a Bambu; Jo said he didn't think so. Model, loan and connectivity are unconfirmed.
- Demo guidance from the brainstorm: keep demo prints small (keychains, name tags, small figurines, under ~20 min), bring pre-calibrated spare filament and a few pre-printed backups.

## 3. Customer, product, pricing
- **Customer:** not defined. Two candidate customers appear in the conversations: (a) consumers who want cheap custom one-offs fast (Akshaya's words, "app for consumers"), and (b) local businesses/startups needing custom merch, stickers or prototypes (Dit proposal; the agent finds them via Exa). A hackathon judge/attendee is the demo customer ("I want a keychain of my dog", "make 50 stickers for my startup" were Dit's example orders).
- **What they order:** custom keychains, stickers, name tags, small figurines (proposal); "cheap custom one-off stuff" (Akshaya).
- **Pricing / unit economics:** UNKNOWN. Nothing discussed beyond "price from material cost + print time + queue length" as the pricing approach and "cheap" as the positioning. No numbers.

## 4. Built / tested vs planned
- **Built or tested:** NOTHING that I can find. As of 2026-10-21 the concept was still being chosen between options (Dit's list: agent-run micro-store, hardware-locked RigShare, autonomous print shop, robotics data company, inspection service); Akshaya picked the print shop on the same day. No code, repo, prototype or printer test found in the sessions or memory banks. Unknown whether he has done anything on 10-22/23 that was not in a place Dit can see.
- **Planned for Saturday (proposal):** build everything at the event in ~9 hours; send Terac requests in the first hour; stretch goal is a phone line (Vapi/Twilio) so judges can call in an order. Proposed 4-way split: voice + customer UI; agent brain (orchestration + Terac/Whop/Exa); hardware pipeline (text-to-3D -> slicer -> printer + camera QA); business ops + demo script/pitch.

## 5. Teammates (names and roles only)
- Nothing confirmed. People discussed for the Saturday team, all unconfirmed as of the latest messages I have:
  - **Jo Unnam:** said he's in (2026-10-19); in the hackathon group chat; asking about borrowing a printer. Role unknown. He also planned to ask a UVA contact (ex-YC founder, worked at Phia) to join, but that person will be in New York that weekend.
  - **Vrisag:** in the group chat; Dit's earlier session notes say he was accepted to the event. Role unknown.
  - **Anush Devkar:** invited; interested, said he'd confirm with family on 2026-10-22; also asked "is it a Bambi[u]?". Status unknown.
  - Akshaya said he'd drive Jo/Vrisag/Anush from home (he comes home ~noon Fri 10-23, goes to NYC Saturday morning).
  - Each person needs their own approved Luma registration; I could only see that Akshaya's is approved.

## 6. Why he's the person; customer conversations
- **Why him:** UNKNOWN. He has not said anything on this that I can find. Possible supporting facts from elsewhere in his record, for him to confirm and not stated by him as reasons for this idea: he runs AI agents on a home GPU and a VPS (memory note, 2026-10-19), he does hardware hackathons (Philly 250 maritime/hardware hackathon March 27-29, 2026; a team of his was the only high-school team among 25 collegiate teams per a message from Ansh Malhotra, 2026-08-28), and he said in March 2026 he can't come up with good hardware ideas (so don't claim hardware is his strength without asking him). All inferences, not quotes.
- **Real customer conversations:** NONE found. No messages, meetings or notes about asking anyone who would order custom 3D prints. The only customer-ish discussion is the internal group chat above. The Granola (meeting) bank has nothing on this idea. (Separate: on 2026-10-19 he asked Sailini for 4-5 small-business owners he could contact as potential customers for Fiore AI, a different project, not this one.) Do not present any of this as customer validation.
- **Quotes from Akshaya (his own words, from the group chat, 2026-10-21):** "we were thinking abt auto printing business for the idea"; "can add mobile app as well and make it like app for consumers to easily order cheap custom one-off stuff they want and super quickly". And in the Dit chat: "lets think bigger... One thing is potentially integrating real time voice (easy to do but big cool factor add)"; "i like the auto print shop, can you build on that, make it more impressive".

## 7. Sources
- Dit desktop chat session `20261021_133317_43949a` ("Hackathon hardware integration ideas Saturday"), 2026-10-21 (Akshaya msgs 53095, 53107; Dit replies 53106, 53108). This is the only place the full flow, roles and stack are written down.
- iMessage group "hackathon gc" (chat 1901: Jo Unnam, Vrisag, Anush Devkar), 2026-10-21 17:50-18:24 UTC, message ids 560267-560316. Private; paraphrase rather than quote.
- iMessage chat 93 (Anush Devkar DM), 2026-10-21, and chat 1792 (Jo Unnam DM), 2026-10-19: team invitations.
- Personal email: Terac Luma approval 2026-10-19 (Gmail id 1a15280d43df39f8); host "IMPORTANT DETAILS" email 2026-10-21 (1a161250440f039c; says to join the event Slack, capacity increased).
- Hindsight `life-messages` (docs life:imessage:1901:2026-10-21, life:imessage:93:2026-10-21), `akshaya-personal` (session 20261021_133317_43949a facts).
- Searched with no further hits: granola-meetings, school-email, whatsapp-private, groupme-facts, other Dit sessions through 2026-10-23, project/notes files on this server.
