// Typed client for the same-origin API in docs/CONTRACT.md (implemented by SITE-FN).

export type ProductKey = 'tweet' | 'milestone' | 'fullcolour' | 'team';

export const PRODUCTS: { key: ProductKey; name: string; price_cents: number }[] = [
  { key: 'tweet', name: 'Tweet Trophy', price_cents: 2900 },
  { key: 'milestone', name: 'Milestone Plaque', price_cents: 4900 },
  { key: 'fullcolour', name: 'Full-Colour Receipt', price_cents: 8900 },
  { key: 'team', name: 'Team Pack', price_cents: 24900 },
];

export const COLOURS = ['black', 'white', 'red', 'blue', 'green', 'gold'] as const;
export type Colour = (typeof COLOURS)[number];

export const DEFAULT_GOAL_CENTS = 200000;
export const DEFAULT_ENDS_AT = '2026-10-24T23:00:00-04:00';

export interface Config {
  plans: Partial<Record<ProductKey, string>>;
  products: { key: ProductKey; name: string; price_cents: number }[];
  ends_at: string;
  goal_cents: number;
}
export interface TweetInfo {
  ok: boolean;
  handle?: string;
  author_name?: string;
  text?: string;
  date?: string;
  url?: string;
}
export interface Stats {
  revenue_cents: number;
  orders: number;
  founding_left: number;
  ends_at: string;
  goal_cents: number;
}
export interface Claim {
  slug: string;
  handle: string;
  product: 'tweet' | 'milestone';
  tweet_url?: string;
  text?: string;
  likes?: string | number;
  number?: string;
  label?: string;
  name?: string;
  date?: string;
  colour: string;
  price_cents: number;
}
export interface AgentEvent {
  ts: string | number;
  agent: string;
  text: string;
  kind?: string;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return (await res.json()) as T;
}

let configPromise: Promise<Config> | null = null;
export function getConfig(): Promise<Config> {
  configPromise ??= getJSON<Config>('/api/config');
  return configPromise;
}
export const getStats = () => getJSON<Stats>('/api/stats');
export const getEvents = () => getJSON<AgentEvent[]>('/api/events');
export const getClaim = (slug: string) => getJSON<Claim>(`/api/claim/${encodeURIComponent(slug)}`);
export const getTweet = (url: string) => getJSON<TweetInfo>(`/api/tweet?url=${encodeURIComponent(url)}`);

export async function uploadImage(file: File): Promise<string> {
  const body = new FormData();
  body.append('file', file);
  const res = await fetch('/api/upload', { method: 'POST', body });
  if (!res.ok) throw new Error(`upload ${res.status}`);
  const data = (await res.json()) as { upload_id: string };
  return data.upload_id;
}

export const productByKey = (k: string) => PRODUCTS.find((p) => p.key === k);

export function dollars(cents: number): string {
  const d = cents / 100;
  return '$' + d.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: d % 1 ? 2 : 0 });
}

export function isTweetUrl(s: string): boolean {
  return /^(https?:\/\/)?(www\.|mobile\.)?(x|twitter)\.com\/[^/]+\/status(es)?\/\d+/i.test(s.trim());
}

/** "hh:mm" (or "hh:mm:ss") until ends_at; "00:00" once passed. */
export function timeLeft(endsAt: string, seconds = false): string {
  let ms = Math.max(0, new Date(endsAt).getTime() - Date.now());
  if (Number.isNaN(ms)) ms = 0;
  const s = Math.floor(ms / 1000);
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return seconds ? `${hh}:${mm}:${ss}` : `${hh}:${mm}`;
}
