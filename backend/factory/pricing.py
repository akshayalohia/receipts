"""Quote = max(menu floor, base + grams*rate + hours*rate + gen_cost) + queue surcharge + colour swap."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .types import Quote, SliceResult

DEFAULT_POLICY = {"base_cents": 300, "per_gram_cents": 6, "per_hour_cents": 250,
                  "queue_surcharge_cents": 200, "queue_threshold": 2, "colour_swap_cents": 200,
                  "floors_cents": {"nametag": 800, "fixit": 1000, "holder": 1200, "keychain": 1200, "figurine": 1500, "custom": 800}}
BOUND = 0.20  # the sales bot may move each value at most ±20% from DEFAULT_POLICY


def _clamp(value, default: int) -> int:
    lo, hi = math.ceil(default * (1 - BOUND)), math.floor(default * (1 + BOUND))
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v):
        return default
    return int(min(max(round(v), lo), hi))


def clamp_policy(policy: dict | None) -> dict:
    """Unknown keys dropped, missing keys defaulted, every number clamped to ±20% of the default."""
    policy = policy or {}
    out = {}
    for key, default in DEFAULT_POLICY.items():
        if key == "floors_cents":
            given = policy.get(key) if isinstance(policy.get(key), dict) else {}
            out[key] = {p: _clamp(given.get(p, d), d) for p, d in default.items()}
        else:
            out[key] = _clamp(policy.get(key, default), default)
    return out


def load_policy(path) -> dict:
    p = Path(path)
    if not p.exists():
        return copy.deepcopy(DEFAULT_POLICY)
    return clamp_policy(json.loads(p.read_text()))


def save_policy(path, policy) -> dict:
    applied = clamp_policy(policy)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(applied, indent=2))
    return applied


def quote(s: SliceResult, *, product: str, gen_cost_cents: int, queue_len: int,
          colour_loaded: bool, policy: dict | None = None) -> Quote:
    pol = clamp_policy(policy) if policy is not None else DEFAULT_POLICY
    floors = pol["floors_cents"]
    floor = floors.get(product, floors["custom"])
    b = {
        "base": pol["base_cents"],
        "material": round(s.filament_grams * pol["per_gram_cents"]),
        "machine_time": round(s.print_seconds / 3600 * pol["per_hour_cents"]),
        "generation": int(gen_cost_cents),
    }
    subtotal = sum(b.values())
    b["floor_topup"] = max(0, floor - subtotal)
    b["queue_surcharge"] = pol["queue_surcharge_cents"] if queue_len > pol["queue_threshold"] else 0
    b["colour_swap"] = 0 if colour_loaded else pol["colour_swap_cents"]
    return Quote(price_cents=sum(b.values()), print_seconds=s.print_seconds,
                 filament_grams=s.filament_grams, breakdown=b)
