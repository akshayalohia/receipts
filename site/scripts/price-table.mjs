// Price table for the demo dog: measures public/examples/dog.glb exactly like the API (makePreview -> geom),
// then prints priceFor() for every size x plinth. Env overrides (PRICE_MARKUP=..., etc.) apply.
// Run from site/: node scripts/price-table.mjs
import { readFile } from "node:fs/promises";
import { makePreview, priceFor, SIZES } from "../api/_render.js";

const raw = new Uint8Array(await readFile(new URL("../public/examples/dog.glb", import.meta.url)));
const { geom } = await makePreview(raw);
const usd = (c) => `$${(c / 100).toFixed(2)}`;

console.log(`dog.glb geom: size ${geom.size.map((v) => v.toFixed(3)).join(" x ")}, volume ${geom.volume.toFixed(4)}`);
const head = ["size", "mm", "base", "grams", "print", "ship", "render", "fees", "cost", "margin", "PRICE"];
const rows = [];
for (const s of SIZES) {
  for (const base of ["round", "none"]) {
    const q = priceFor(geom, s.id, base);
    rows.push([`${s.id} ${s.label}`, String(q.heightMm), base, String(q.grams), usd(q.est_print_cents), usd(q.est_ship_cents),
      usd(q.est_render_cents), usd(q.est_fees_cents), usd(q.est_cost_cents), usd(q.margin_cents), usd(q.price_cents)]);
  }
}
const legacy = priceFor(geom, "S", "round");
rows.push([`S (legacy)`, String(legacy.heightMm), "round", String(legacy.grams), usd(legacy.est_print_cents), usd(legacy.est_ship_cents),
  usd(legacy.est_render_cents), usd(legacy.est_fees_cents), usd(legacy.est_cost_cents), usd(legacy.margin_cents), usd(legacy.price_cents)]);
const w = head.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i].length)));
const line = (r) => r.map((c, i) => (i < 3 ? c.padEnd(w[i]) : c.padStart(w[i]))).join("  ");
console.log(line(head));
console.log(w.map((n) => "-".repeat(n)).join("  "));
for (const r of rows) console.log(line(r));
