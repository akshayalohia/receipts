// Whop embedded checkout (docs/vendor/whop-embed-checkout.md, @whop/elements types).
import { loadWhop } from '@whop/elements';
import { getConfig, type ProductKey } from './api';

export const METADATA_KEYS = [
  'order_ref', 'product', 'colour', 'tweet_url', 'tweet_text', 'likes', 'number', 'label', 'name',
  'date', 'team', 'subline', 'upload_id', 'ship_name', 'ship_email', 'ship_line1', 'ship_line2',
  'ship_city', 'ship_state', 'ship_zip', 'ship_country', 'claim_slug', 'gift_from', 'gift_note', 'source',
] as const;
export type MetadataKey = (typeof METADATA_KEYS)[number];

/** 8-char random order ref, no ambiguous characters. */
export function makeOrderRef(): string {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}

export function sourceFromUrl(): string {
  const p = new URLSearchParams(location.search);
  return p.get('utm_source') || 'direct';
}

/** Strings only, known keys only, empty keys omitted, each value capped at 500 chars. */
export function buildMetadata(input: Partial<Record<MetadataKey, string | number | undefined | null>>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of METADATA_KEYS) {
    const v = input[k];
    if (v === undefined || v === null) continue;
    const s = String(v).trim();
    if (!s) continue;
    out[k] = s.slice(0, 500);
  }
  return out;
}

export interface MountedCheckout {
  destroy(): void;
}

export async function mountCheckout(opts: {
  target: HTMLElement;
  product: ProductKey;
  metadata: Record<string, string>;
  email?: string;
  shipping?: { name?: string; line1?: string; line2?: string; city?: string; state?: string; postal_code?: string };
  onError?: (msg: string) => void;
}): Promise<MountedCheckout> {
  const config = await getConfig();
  const plan = config.plans?.[opts.product];
  if (!plan) throw new Error(`No plan configured for ${opts.product}`);
  const ref = opts.metadata.order_ref;
  const WhopElements = await loadWhop();
  const whop = WhopElements({ locale: 'en' });
  const handle = whop.checkout.create({
    plan,
    metadata: opts.metadata,
    returnUrl: `${location.origin}/order?ref=${encodeURIComponent(ref)}`,
    attribution: { utmSource: opts.metadata.source },
    analytics: false, // no third-party usage analytics (privacy page says so)
  });
  const el = handle.create('checkout', {
    buyerEmail: opts.email || '',
    defaultValues: opts.shipping ? { shippingAddress: { ...opts.shipping, country: 'US' } } : undefined,
    onError: (e) => opts.onError?.(e.message),
  });
  el.mount(opts.target);
  return { destroy: () => handle.destroy() };
}
