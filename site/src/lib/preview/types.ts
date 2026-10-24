/** Products, as keyed in docs/CONTRACT.md. */
export type PreviewProduct = 'tweet' | 'milestone' | 'fullcolour' | 'team';

/** Colours from the contract: black, white, red, blue, green, gold. Other CSS colours are accepted and treated as "other". */
export type PreviewColour = 'black' | 'white' | 'red' | 'blue' | 'green' | 'gold';

export interface PreviewParams {
  product: PreviewProduct;
  /** One of PreviewColour, or any CSS colour string. */
  colour: string;
  author_name?: string;
  handle?: string;
  text?: string;
  likes?: string | number;
  date?: string;
  number?: string | number;
  label?: string;
  name?: string;
  team?: string;
  subline?: string;
  image_url?: string;
  /** Tweet Trophy: author avatar (CORS-enabled URL). Rendered as a height-map relief; initial letter if absent. */
  avatar_url?: string;
  /** Tweet Trophy: reply / repost counts when known (only real numbers; omitted otherwise). */
  replies?: string | number;
  reposts?: string | number;
  /** Tweet Trophy: show the verified badge next to the name. */
  verified?: boolean;
  /** Founding Edition number, e.g. "7" or "007". Shown as "#007" on the back. */
  founding?: string;
}

export interface PreviewHandle {
  update(p: PreviewParams): void;
  /** 1200x630 PNG, object centred on #F2EEE6. */
  snapshot(): Promise<Blob>;
  destroy(): void;
}
