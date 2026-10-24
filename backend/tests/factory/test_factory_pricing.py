import json
from pathlib import Path

import pytest

from factory.pricing import DEFAULT_POLICY, clamp_policy, load_policy, quote, save_policy
from factory.types import SliceResult


def sr(grams, seconds):
    return SliceResult(gcode_3mf=Path("x.gcode.3mf"), print_seconds=seconds, filament_grams=grams)


def test_default_policy_matches_spec():
    assert DEFAULT_POLICY == {"base_cents": 300, "per_gram_cents": 6, "per_hour_cents": 250,
                              "queue_surcharge_cents": 200, "queue_threshold": 2, "colour_swap_cents": 200,
                              "floors_cents": {"nametag": 800, "fixit": 1000, "holder": 1200, "keychain": 1200,
                                               "figurine": 1500, "custom": 800}}


def test_floor_applies_to_small_job():
    q = quote(sr(12.0, 1800), product="nametag", gen_cost_cents=0, queue_len=0, colour_loaded=True)
    # 300 base + 12 g * 6 + 0.5 h * 250 = 497 < 800 floor
    assert q.breakdown == {"base": 300, "material": 72, "machine_time": 125, "generation": 0,
                           "floor_topup": 303, "queue_surcharge": 0, "colour_swap": 0}
    assert q.price_cents == 800 and q.print_seconds == 1800 and q.filament_grams == 12.0


def test_big_job_with_queue_and_colour_swap():
    q = quote(sr(100.0, 4 * 3600), product="keychain", gen_cost_cents=40, queue_len=3, colour_loaded=False)
    # 300 + 600 + 1000 + 40 = 1940 > 1200 floor; +200 queue (3 > 2) +200 colour
    assert q.price_cents == 2340
    assert q.breakdown["floor_topup"] == 0 and q.breakdown["queue_surcharge"] == 200 and q.breakdown["colour_swap"] == 200
    assert sum(q.breakdown.values()) == q.price_cents


def test_queue_threshold_is_strictly_more_than():
    at = quote(sr(1, 60), product="custom", gen_cost_cents=0, queue_len=2, colour_loaded=True)
    over = quote(sr(1, 60), product="custom", gen_cost_cents=0, queue_len=3, colour_loaded=True)
    assert over.price_cents - at.price_cents == 200


def test_unknown_product_uses_custom_floor():
    q = quote(sr(1, 60), product="mystery", gen_cost_cents=0, queue_len=0, colour_loaded=True)
    assert q.price_cents == 800


def test_quote_clamps_an_out_of_bounds_policy():
    wild = dict(DEFAULT_POLICY, base_cents=10_000, floors_cents={"nametag": 1})
    q = quote(sr(1, 60), product="nametag", gen_cost_cents=0, queue_len=0, colour_loaded=True, policy=wild)
    assert q.breakdown["base"] == 360  # +20% max
    assert q.price_cents == 640  # floor clamped to 800 * 0.8


def test_save_policy_clamps_to_twenty_percent(tmp_path):
    path = tmp_path / "policy.json"
    applied = save_policy(path, {"base_cents": 1000, "per_gram_cents": 1, "per_hour_cents": 260,
                                 "floors_cents": {"nametag": 2000, "figurine": 1400}, "free_money": 1})
    assert applied["base_cents"] == 360
    assert applied["per_gram_cents"] == 5  # 6 * 0.8 = 4.8 -> smallest whole cent inside the bound
    assert applied["per_hour_cents"] == 260  # inside bounds: kept
    assert applied["floors_cents"]["nametag"] == 960 and applied["floors_cents"]["figurine"] == 1400
    assert applied["floors_cents"]["holder"] == 1200  # missing -> default
    assert applied["queue_threshold"] == 2 and "free_money" not in applied
    assert json.loads(path.read_text()) == applied
    assert load_policy(path) == applied


def test_load_policy_missing_file_and_hand_edits(tmp_path):
    assert load_policy(tmp_path / "none.json") == DEFAULT_POLICY
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"colour_swap_cents": 0, "queue_surcharge_cents": "lots"}))
    p = load_policy(path)
    assert p["colour_swap_cents"] == 160 and p["queue_surcharge_cents"] == 200


@pytest.mark.parametrize("key", [k for k in DEFAULT_POLICY if k != "floors_cents"])
def test_every_value_stays_within_bounds(key):
    d = DEFAULT_POLICY[key]
    assert d * 0.8 <= clamp_policy({key: d * 5})[key] <= d * 1.2
    assert d * 0.8 <= clamp_policy({key: -d})[key] <= d * 1.2
