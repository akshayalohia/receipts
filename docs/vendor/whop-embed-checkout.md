# Whop embedded checkout (copied from docs.whop.com, fetched 2026-10-24)

Sources: https://docs.whop.com/developer/guides/embed-checkout , https://docs.whop.com/elements/latest/checkout/overview , https://docs.whop.com/payments/checkout-embed

## Vanilla loader (no npm)
Head: `<script async defer src="https://js.whop.com/static/checkout/loader.js"></script>`
Element:
```html
<div id="whop-embedded-checkout"
  data-whop-checkout-plan-id="plan_XXXXXXXXX"
  data-whop-checkout-session="ch_XXXXXXXXX"   <!-- optional: checkout configuration id, needed to attach metadata with the loader -->
  data-whop-checkout-return-url="https://yoursite.com/checkout/complete"
  data-whop-checkout-theme="light"
  data-whop-checkout-hide-price="false"></div>
```
Programmatic submit: `wco.submit("whop-embedded-checkout")`.
Return URL gets `status` = success | error.

## Whop Elements (npm `@whop/elements@1.8.0`, React wrapper `@whop/elements-react`)
`import { loadWhop } from "@whop/elements"` then `whop.checkout.create({ ... })` (React: `<WhopElements elements={loadWhop()}><Checkout ...><CheckoutElement/></Checkout></WhopElements>`).
Options (all "set at create only"):
- `plan`: existing `plan_` id. The plan defines the price; amounts can't be asserted client-side. Or `items`, or `checkoutConfiguration` (`ch_` id created server-side).
- `quantity` (default 1)
- `metadata`: Record<string,string>, up to 40 string pairs. Whop copies it to the payment and every webhook about it. No server or API key needed on the page.
- `returnUrl`: https page; Whop appends `payment` (pay_ id) and `status` (succeeded | failed | canceled); your own query params survive.
- `promoCode`, `affiliateCode`, `attribution` {utmSource, utmMedium, utmCampaign, utmTerm, utmContent, trackingLinkId, funnelId, source}
- `appearance`, `locale`
Events: `onComplete(payload)` fires once per mount with `{result:"payment", paymentId, sessionId}`; use for analytics only, never fulfilment. `onLoadingChange(bool)`.
Methods: `update(partial)`, `destroy()`.

## Rules
- The return page is display only; anyone can type `status=succeeded`. Fulfilment comes only from the `payment.succeeded` webhook or from reading the payment back from the Whop API.
- Card declines show inline in the element; only off-site steps (3DS, bank, financing) land on the return URL.
