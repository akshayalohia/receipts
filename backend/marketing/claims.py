"""Claim pages: build the claim JSON (docs/CONTRACT.md), render an og:image card, PUT it to the site."""
from __future__ import annotations

import base64
import io
import re
import secrets
import textwrap

PRODUCTS = {"tweet": 2900, "milestone": 4900, "fullcolour": 8900, "team": 24900}
CLAIM_PRODUCTS = {"tweet", "milestone"}          # claim pages only carry these two (CONTRACT)
COLOURS = {"black", "white", "red", "blue", "green", "gold"}
CLAIM_KEYS = {"slug", "handle", "product", "tweet_url", "text", "likes", "number", "label", "name", "date",
              "colour", "price_cents", "og_image_b64"}
REQUIRED = {"slug", "handle", "product", "colour", "price_cents"}


def make_slug(handle: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", handle.lower().lstrip("@")).strip("-")[:32] or "claim"
    return f"{base}-{secrets.token_hex(2)}"


def build_claim(handle: str, product: str = "tweet", colour: str = "black", slug: str | None = None,
                tweet_url: str | None = None, text: str | None = None, likes: int | None = None,
                number: str | None = None, label: str | None = None, name: str | None = None,
                date: str | None = None) -> dict:
    if product not in CLAIM_PRODUCTS:
        raise ValueError(f"product must be one of {sorted(CLAIM_PRODUCTS)}")
    if colour not in COLOURS:
        raise ValueError(f"colour must be one of {sorted(COLOURS)}")
    handle = handle.lstrip("@").strip()
    if not handle:
        raise ValueError("handle is required")
    claim = {"slug": slug or make_slug(handle), "handle": handle, "product": product, "colour": colour,
             "price_cents": PRODUCTS[product], "tweet_url": tweet_url,
             "text": text[:280] if text else text, "likes": likes,
             "number": str(number)[:10] if number is not None else None, "label": label, "name": name,
             "date": date}
    if product == "tweet" and not (tweet_url or text):
        raise ValueError("tweet claims need tweet_url or text")
    if product == "milestone" and not number:
        raise ValueError("milestone claims need number")
    return {k: v for k, v in claim.items() if v is not None}


def validate_claim(claim: dict) -> None:
    extra = set(claim) - CLAIM_KEYS
    missing = REQUIRED - set(claim)
    if extra or missing:
        raise ValueError(f"claim keys: extra={sorted(extra)} missing={sorted(missing)}")
    if claim["price_cents"] != PRODUCTS[claim["product"]]:
        raise ValueError("price_cents does not match the product table")


_PALETTE = {"black": ((24, 24, 27), (250, 250, 250)), "white": ((250, 250, 250), (24, 24, 27)),
            "red": ((185, 28, 28), (255, 255, 255)), "blue": ((29, 78, 216), (255, 255, 255)),
            "green": ((21, 128, 61), (255, 255, 255)), "gold": ((202, 138, 4), (24, 24, 27))}


def render_card_png(claim: dict, size: tuple[int, int] = (1200, 630)) -> bytes:
    """Simple PIL og:image: the trophy text on a slab in the claim's colour.

    TODO(og-render): swap in a 3D preview render once BACKEND-ORDERS exposes one (CONTRACT only
    has generate(order) -> STL/3MF, which needs a paid Order).
    """
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    slab, ink = _PALETTE.get(claim.get("colour", "black"), _PALETTE["black"])
    img = Image.new("RGB", size, (228, 228, 231))
    d = ImageDraw.Draw(img)
    pad = 60
    d.rounded_rectangle((pad, pad, w - pad, h - pad - 40), radius=24, fill=slab)

    def font(px: int):
        try:
            return ImageFont.load_default(size=px)
        except TypeError:           # very old Pillow
            return ImageFont.load_default()

    x, y = pad + 40, pad + 36
    if claim["product"] == "milestone":
        d.text((x, y), str(claim.get("number", "")), fill=ink, font=font(140))
        d.text((x, y + 170), claim.get("label", "") or "", fill=ink, font=font(44))
    else:
        d.text((x, y), f"{claim.get('name') or claim['handle']}  @{claim['handle']}", fill=ink, font=font(38))
        body = textwrap.fill(claim.get("text", "") or "", width=48)
        d.multiline_text((x, y + 64), body, fill=ink, font=font(36), spacing=8)
    foot = []
    if claim.get("likes") is not None:
        foot.append(f"{claim['likes']:,} likes")
    if claim.get("date"):
        foot.append(claim["date"])
    d.text((x, h - pad - 110), "   ".join(foot), fill=ink, font=font(32))
    d.text((pad, h - pad - 20), f"We already made yours. ${claim['price_cents'] / 100:.0f}", fill=(24, 24, 27),
           font=font(30))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def attach_og(claim: dict) -> dict:
    return {**claim, "og_image_b64": base64.b64encode(render_card_png(claim)).decode()}


def claim_url(site_url: str, slug: str) -> str:
    return f"{site_url.rstrip('/')}/c/{slug}"
