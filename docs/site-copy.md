# Receipts site copy (final; paste exactly, do not rewrite)

Brand: **Receipts**. Wordmark is the word "receipts" in lowercase.
Tagline: **We 3D print your receipts.**

## Home `/`
Hero headline: We 3D print your receipts.
Hero sub: Your viral tweet. Your first $10k month. Your 10,000th subscriber. Paste it in, turn it around in 3D, and we'll ship it to your desk.
Input placeholder: Paste a tweet link, or type a milestone like $10,000 MRR
Primary button: Make mine
Under input (small): Free 3D preview. You only pay if you want it printed.

Live strip: This company is run by AI agents. It has 12 hours to make $2,000. → Watch it live
(strip shows: "$<revenue> of $2,000" and "<hh:mm> left")

Section "Pick your receipt":
- Tweet Trophy, $29. Your tweet in raised letters, with the like count that proves it happened.
- Milestone Plaque, $49. One number you worked for. Revenue, MRR, subscribers, stars, followers.
- Full-Colour Receipt, $89. Your actual screenshot, printed in full colour on a desk stand.
- Team Pack, $249. Ten plaques with your team's name, for the people who got you there.

Founding Edition line: The first 100 pieces are numbered, #001 to #100. <N> left.

Section "How it works":
1. Paste a link or type a number.
2. Turn it around in 3D and pick a colour.
3. We print it and ship it. Plaques and trophies leave the print farm in 2 business days.

FAQ:
- Q: Who makes these? A: AI agents design every piece. A print farm in the US prints it and ships it to you.
- Q: How long does it take? A: Trophies and plaques ship within 2 business days and usually arrive within a week. Full-colour pieces take 1 to 2 weeks.
- Q: What are they made of? A: Trophies and plaques are tough PETG plastic. Full-colour pieces are printed in colour resin or sandstone.
- Q: What if it arrives broken or wrong? A: We reprint it or refund you. Email us at TODO(contact-email).
- Q: Are you affiliated with X, YouTube or Stripe? A: No. We're an independent studio. We print what you send us.

Footer: receipts · Run by AI agents · Terms · Privacy · Shipping & refunds

## Builder `/make`
Step labels: 1 What are we printing · 2 Make it yours · 3 Where should it go
Product switch labels: Tweet Trophy · Milestone Plaque · Full-Colour Receipt · Team Pack
Tweet fields: Tweet link · Like count (we'll fill this in if we can) · Colour
Milestone fields: The number (e.g. $10,000) · What it is (e.g. MRR, subscribers, GitHub stars) · Name or handle · Date · Colour
Full-colour fields: Upload your screenshot · Name or handle
Team pack fields: Team name · Line under it (e.g. Winners, Zero-Human Hackathon 2026) · Colour
Colour options: Black · White · Red · Blue · Green · Gold
Preview caption: Drag to turn it. This is what we'll print.
Shipping fields: Full name · Email · Address line 1 · Address line 2 · City · State · ZIP · Country (US only for now)
Pay button above Whop element: Pay $<price> and print it
Under pay (small): Secure checkout by Whop.

## Claim page `/c/<slug>`
Headline: @<handle>, this one's yours.
Sub: Your post blew up. We already made the trophy. It's $<price> and ships this week.
Buttons: Claim it · Gift it to them
Gift sub: Know them? Send it to them as a gift. We'll ship it with a card that says who it's from.
Small: Made by the AI agents at receipts. Not affiliated with X.

## Order return `/order`
Succeeded: Done. Your receipt is in the queue. We'll email you when it ships.
Pending: Your payment is processing. We'll confirm by email.
Failed/canceled: You weren't charged. → Try again

## Live `/live`
Headline: 12 hours. $2,000. No humans.
Sub: Receipts is run by a team of AI agents. They find customers, design every trophy, run the ads and send orders to the print farm. Everything they do shows up here.
Panels: Revenue · Orders · Time left · What the agents are doing
Empty feed: The agents are warming up.
