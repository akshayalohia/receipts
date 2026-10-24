"""Shop logic shared by the HTTP API, the MCP tools and the printer monitor.

Sync methods may block (pipeline, printer, Whop); async callers wrap them in
asyncio.to_thread. Every state change goes through `emit`, which writes an `events`
row and publishes on the in-process bus that feeds the SSE stream.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import logging
import math
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from .bus import EventBus
from .config import (FILAMENT_CENTS_PER_GRAM, MESHY_COST_CENTS, REFUND_CAP_CENTS,
                     WHOP_FEE_BPS, WHOP_FEE_FIXED_CENTS, Settings)
from .db import DB
from .hermes import HermesClient
from .pipeline import Pipeline, get_pipeline
from .whop import WhopClient, make_whop

log = logging.getLogger("factory.core")

SSE_TYPES = ("message", "agent_delta", "status", "design", "quote", "printer", "human_task")
PRE_PAYMENT = ("draft", "designing", "review", "quoted")
HUMAN_KINDS = ("bed_clear", "spool_swap", "qa", "pickup", "other")
PRINTABLE_FROM = ("IDLE", "FINISH")

CATALOG = [
    {"id": "keychain", "title": "Pet / Mini-Me keychain", "path": "hybrid", "needs": ["photos"],
     "blurb": "A 40 mm keychain of your pet or you, from 1-4 photos."},
    {"id": "nametag", "title": "Name tag / desk nameplate", "path": "parametric", "needs": ["text"],
     "blurb": "Your name or a word, raised letters, any stocked colour."},
    {"id": "fixit", "title": "Fix-it part", "path": "parametric", "needs": ["photos", "measurements"],
     "blurb": "Knobs, clips, caps and cable clips, from a photo and a couple of measurements."},
    {"id": "holder", "title": "Perfect-fit holder", "path": "parametric", "needs": ["measurements"],
     "blurb": "A stand sized to your AirPods case, phone or glasses."},
    {"id": "figurine", "title": "Figurine", "path": "organic", "needs": ["photos"],
     "blurb": "A 60 mm figure from your photos or an idea."},
]
PRODUCTS = {p["id"] for p in CATALOG} | {"custom"}


class ShopError(Exception):
    """A refusal the caller (bot or app) should see as a plain message."""


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def clamp_policy(new: dict, default: dict, current: dict) -> dict:
    """Merge `new` into `current`, keeping every value within ±20% of `default`."""

    def clamp(value, base):
        lo, hi = math.ceil(base * 0.8), math.floor(base * 1.2)
        try:
            v = round(float(value))
        except (TypeError, ValueError):
            return None
        return max(lo, min(hi, v))

    out = json.loads(json.dumps(current))
    for key, value in (new or {}).items():
        if key not in default:
            continue
        if isinstance(default[key], dict):
            sub = dict(out.get(key) or default[key])
            for sk, sv in (value or {}).items() if isinstance(value, dict) else []:
                if sk in default[key]:
                    c = clamp(sv, default[key][sk])
                    if c is not None:
                        sub[sk] = c
            out[key] = sub
        else:
            c = clamp(value, default[key])
            if c is not None:
                out[key] = c
    return out


class Core:
    def __init__(self, settings: Settings, *, db: DB | None = None, bus: EventBus | None = None,
                 pipeline: Pipeline | None = None, whop: WhopClient | None = None,
                 hermes: HermesClient | None = None) -> None:
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = db or DB(settings.db_path)
        self.bus = bus or EventBus()
        self._pipeline = pipeline
        self.whop = whop or make_whop(settings)
        self.hermes = hermes or HermesClient(settings.hermes_api_base, settings.hermes_api_key)
        self._file_key = (settings.app_shared_secret or secrets.token_hex(16)).encode()
        self._tasks: set[asyncio.Task] = set()

    @property
    def pipeline(self) -> Pipeline:
        return self._pipeline or get_pipeline()

    # ---- events / messages --------------------------------------------------
    def emit(self, order_id: str | None, actor: str, type_: str, payload: dict,
             *, persist: bool = True) -> None:
        if persist:
            self.db.add_event(order_id, actor, type_, payload)
        self.bus.publish(order_id, type_, payload)

    def set_status(self, order_id: str, status: str, actor: str, **fields: Any) -> dict:
        order = self.db.update_order(order_id, status=status, **fields)
        self.emit(order_id, actor, "status", {"status": status})
        return order

    def add_message(self, order_id: str, role: str, text: str, media: list | None = None) -> int:
        mid = self.db.add_message(order_id, role, text, media)
        self.emit(order_id, role, "message", {"role": role, "text": text}, persist=False)
        return mid

    # ---- orders / files -----------------------------------------------------
    def require_order(self, order_id: str) -> dict:
        order = self.db.get_order(order_id)
        if order is None:
            raise ShopError(f"unknown order {order_id}")
        return order

    def file_sig(self, order: dict) -> str:
        msg = f"{order['id']}.{order['device_id']}".encode()
        return hmac.new(self._file_key, msg, hashlib.sha256).hexdigest()[:32]

    def file_url(self, order: dict, name: str) -> str:
        return f"{self.settings.public_base_url}/files/{order['id']}/{name}?sig={self.file_sig(order)}"

    def file_path(self, order_id: str, name: str) -> Path | None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        for base in (self.settings.order_dir(order_id), self.settings.upload_dir(order_id)):
            p = base / name
            if p.is_file():
                return p
        return None

    def photos(self, order_id: str) -> list[Path]:
        d = self.settings.upload_dir(order_id)
        return sorted(p for p in d.iterdir() if p.is_file()) if d.is_dir() else []

    def quote_view(self, order: dict) -> dict | None:
        if order.get("price_cents") is None:
            return None
        return {"price_cents": order["price_cents"], "print_seconds": order["print_seconds"],
                "filament_grams": order["filament_grams"], "colour": order["colour"],
                "whop_variant_id": order["whop_variant_id"],
                "whop_purchase_url": order["whop_purchase_url"], "eta": order["eta"]}

    def order_view(self, order: dict) -> dict:
        files = {k: self.file_url(order, v) for k, v in (order["files"] or {}).items()
                 if k in ("stl", "glb", "usdz", "png")}
        keys = ("id", "status", "product", "path", "colour", "design_version", "bbox_mm",
                "print_seconds", "filament_grams", "price_cents", "whop_variant_id",
                "whop_purchase_url", "queue_position", "eta", "created_at", "updated_at")
        view = {k: order[k] for k in keys}
        view["params"] = {k: v for k, v in (order["params"] or {}).items() if not k.startswith("_")}
        view["files"] = files
        view["quote"] = self.quote_view(order)
        return view

    # ---- artifacts ----------------------------------------------------------
    def _artifact_dir(self, order_id: str, artifact_id: str) -> Path:
        return self.settings.order_dir(order_id) / "artifacts" / artifact_id

    def _new_artifact_dir(self, order_id: str) -> tuple[str, Path]:
        aid = "art_" + secrets.token_hex(4)
        d = self._artifact_dir(order_id, aid)
        d.mkdir(parents=True, exist_ok=True)
        return aid, d

    def _register(self, order: dict, aid: str, art: Any, kind: str) -> dict:
        rec = {"artifact_id": aid, "kind": kind,
               "stl": str(art.stl), "glb": str(art.glb), "usdz": str(art.usdz), "png": str(art.png),
               "bbox_mm": [float(x) for x in art.bbox_mm], "watertight": bool(art.watertight),
               "volume_cm3": float(art.volume_cm3)}
        (self._artifact_dir(order["id"], aid) / "artifact.json").write_text(json.dumps(rec))
        png_name = f"{aid}.png"
        shutil.copyfile(art.png, self.settings.order_dir(order["id"]) / png_name)
        return {"artifact_id": aid, "bbox_mm": rec["bbox_mm"], "watertight": rec["watertight"],
                "png_url": self.file_url(order, png_name)}

    def load_artifact(self, order_id: str, artifact_id: str) -> dict:
        p = self._artifact_dir(order_id, artifact_id) / "artifact.json"
        if "/" in artifact_id or not p.is_file():
            raise ShopError(f"unknown artifact {artifact_id} for {order_id}")
        return json.loads(p.read_text())

    def _design_start(self, order_id: str, path: str | None, actor: str) -> dict:
        order = self.require_order(order_id)
        if order["status"] not in PRE_PAYMENT:
            raise ShopError(f"order {order_id} is {order['status']}; designs are locked after payment")
        fields: dict[str, Any] = {}
        if path and (order["path"] is None or path == "hybrid"):
            fields["path"] = path
        if order["status"] != "designing":
            order = self.set_status(order_id, "designing", actor, **fields)
        elif fields:
            order = self.db.update_order(order_id, **fields)
        return order

    def list_templates(self) -> list[dict]:
        return self.pipeline.list_templates()

    def build_template(self, order_id: str, name: str, params: dict, actor: str) -> dict:
        order = self._design_start(order_id, "parametric", actor)
        aid, d = self._new_artifact_dir(order_id)
        art = self.pipeline.build_template(name, params or {}, d)
        p = dict(order["params"] or {})
        p.update({"template": name, "template_params": params or {}})
        order = self.db.update_order(order_id, params=p)
        return self._register(order, aid, art, f"template:{name}")

    def run_cadquery(self, order_id: str, code: str, actor: str) -> dict:
        order = self._design_start(order_id, "parametric", actor)
        aid, d = self._new_artifact_dir(order_id)
        (d / "model.py").write_text(code)
        art = self.pipeline.run_cadquery(code, d)
        return self._register(order, aid, art, "cadquery")

    def generate_mesh(self, order_id: str, prompt: str | None, actor: str) -> dict:
        order = self._design_start(order_id, "organic", actor)
        photos = self.photos(order_id)
        if not photos:
            raise ShopError("no photos uploaded for this order")
        aid, d = self._new_artifact_dir(order_id)
        raw = self.pipeline.generate_from_images(photos, d / "raw", prompt=prompt)
        art = self.pipeline.to_all_formats(raw, d)
        order = self.db.update_order(order_id, gen_cost_cents=(order["gen_cost_cents"] or 0) + MESHY_COST_CENTS)
        return self._register(order, aid, art, "mesh_raw")

    def finish_mesh(self, order_id: str, src: str, actor: str, target_height_mm: float | None = None,
                    add_base: bool = False, keyring: bool = False) -> dict:
        order = self._design_start(order_id, "hybrid" if keyring else None, actor)
        source = self.load_artifact(order_id, src)
        aid, d = self._new_artifact_dir(order_id)
        art = self.pipeline.finish_for_print(Path(source["stl"]), d, target_height_mm=target_height_mm,
                                             add_base=add_base, keyring=keyring)
        return self._register(order, aid, art, "mesh_finished")

    def combine(self, order_id: str, a: str, b: str, actor: str) -> dict:
        order = self._design_start(order_id, "hybrid", actor)
        sa, sb = self.load_artifact(order_id, a), self.load_artifact(order_id, b)
        aid, d = self._new_artifact_dir(order_id)
        art = self.pipeline.combine(Path(sa["stl"]), Path(sb["stl"]), d)
        return self._register(order, aid, art, "combined")

    def publish_design(self, order_id: str, artifact_id: str, summary: str, actor: str) -> dict:
        order = self.require_order(order_id)
        if order["status"] not in PRE_PAYMENT:
            raise ShopError(f"order {order_id} is {order['status']}; designs are locked after payment")
        rec = self.load_artifact(order_id, artifact_id)
        if not rec["watertight"]:
            raise ShopError("artifact is not watertight; run finish_mesh first")
        version = (order["design_version"] or 0) + 1
        odir = self.settings.order_dir(order_id)
        files = {}
        for ext in ("stl", "glb", "usdz", "png"):
            name = f"v{version}.{ext}"
            shutil.copyfile(rec[ext], odir / name)
            files[ext] = name
        p = dict(order["params"] or {})
        p["_published_artifact"] = artifact_id
        order = self.db.update_order(order_id, files=files, bbox_mm=rec["bbox_mm"],
                                     design_version=version, params=p)
        order = self.set_status(order_id, "review", actor)
        payload = {"version": version, "glb": self.file_url(order, files["glb"]),
                   "usdz": self.file_url(order, files["usdz"]), "png": self.file_url(order, files["png"]),
                   "bbox_mm": rec["bbox_mm"]}
        self.db.add_event(order_id, actor, "design_published",
                          {"artifact_id": artifact_id, "summary": summary, "version": version})
        self.emit(order_id, actor, "design", payload)
        return {"version": version, **payload}

    # ---- sales --------------------------------------------------------------
    def get_policy(self) -> dict:
        path = self.settings.policy_path
        return self.pipeline.load_policy(path) if path.exists() else self.pipeline.default_policy()

    def set_policy(self, policy: dict, reason: str, actor: str) -> dict:
        clamped = clamp_policy(policy, self.pipeline.default_policy(), self.get_policy())
        applied = self.pipeline.save_policy(self.settings.policy_path, clamped)
        self.emit(None, actor, "pricing_policy", {"requested": policy, "applied": applied, "reason": reason})
        return applied

    def _active_jobs(self) -> list[dict]:
        return self.db.list_orders(status=["paid", "queued", "printing"])

    def prepare_quote(self, order_id: str, actor: str) -> dict:
        order = self.require_order(order_id)
        params = dict(order["params"] or {})
        if order["status"] == "quoted" and params.get("_quoted_version") == order["design_version"]:
            return {**self.quote_view(order), "breakdown": params.get("_quote_breakdown", {}), "reused": True}
        if order["status"] not in ("review", "quoted") or not (order["files"] or {}).get("stl"):
            raise ShopError(f"order {order_id} has no published design to quote (status {order['status']})")
        odir = self.settings.order_dir(order_id)
        version = order["design_version"]
        sliced = self.pipeline.slice_model(odir / order["files"]["stl"], odir / f"slice_v{version}")
        gcode_name = f"v{version}.gcode.3mf"
        shutil.copyfile(sliced.gcode_3mf, odir / gcode_name)
        active = self._active_jobs()
        loaded = self.db.get_state("loaded_colour")
        colour = order["colour"] or loaded
        q = self.pipeline.quote(sliced, product=order["product"], gen_cost_cents=order["gen_cost_cents"] or 0,
                                queue_len=len(active), colour_loaded=(colour == loaded),
                                policy=self.get_policy())
        variant = self.whop.create_variant(order_id=order_id, price_cents=int(q.price_cents),
                                           title=f"Order {order_id}")  # Whop plan titles: max 30 chars
        wait_s = sum(o["print_seconds"] or 0 for o in active) + int(q.print_seconds)
        files = dict(order["files"])
        files["gcode_3mf"] = gcode_name
        params.update({"_quoted_version": version, "_quote_breakdown": dict(q.breakdown)})
        order = self.db.update_order(
            order_id, print_seconds=int(q.print_seconds), filament_grams=float(q.filament_grams),
            price_cents=int(q.price_cents), whop_variant_id=variant["id"],
            whop_purchase_url=variant.get("purchase_url"), colour=colour, files=files, params=params,
            eta=_iso(time.time() + wait_s))
        order = self.set_status(order_id, "quoted", actor)
        self.emit(order_id, actor, "quote", {
            "price_cents": order["price_cents"], "print_seconds": order["print_seconds"],
            "filament_grams": order["filament_grams"], "colour": colour,
            "whop_variant_id": order["whop_variant_id"]})
        return {**self.quote_view(order), "breakdown": dict(q.breakdown)}

    def shop_metrics(self) -> dict:
        orders = self.db.list_orders()
        day_ago = time.time() - 86400
        quoted = [o for o in orders if o["price_cents"] is not None]
        paid = [o for o in orders if o["payment_id"]]
        return {
            "queue_length": len([o for o in orders if o["status"] in ("paid", "queued")]),
            "printing": len([o for o in orders if o["status"] == "printing"]),
            "orders_last_24h": len([o for o in orders if o["created_at"] >= day_ago]),
            "paid_last_24h": len([o for o in paid if o["created_at"] >= day_ago]),
            "conversion": round(len(paid) / len(quoted), 3) if quoted else None,
            "avg_price_cents": round(sum(o["price_cents"] for o in paid) / len(paid)) if paid else None,
            "loaded_colour": self.db.get_state("loaded_colour"),
        }

    # ---- payment ------------------------------------------------------------
    def mark_paid(self, order: dict, payment_id: str, actor: str) -> bool:
        """Record a payment. Returns False when this payment was already processed."""
        if self.db.find_order_by_payment(payment_id):
            return False
        if order["payment_id"]:
            self.db.add_event(order["id"], actor, "payment_extra", {"payment_id": payment_id})
            return False
        if order["status"] not in PRE_PAYMENT:
            self.db.add_event(order["id"], actor, "payment_unexpected",
                              {"payment_id": payment_id, "status": order["status"]})
            return False
        self.set_status(order["id"], "paid", actor, payment_id=payment_id)
        position = len(self.db.list_orders(status=["paid", "queued"]))
        self.set_status(order["id"], "queued", actor, queue_position=position)
        return True

    # ---- production ---------------------------------------------------------
    def _renumber_queue(self) -> None:
        for i, o in enumerate(self.db.list_orders(status=["paid", "queued"]), start=1):
            if o["queue_position"] != i:
                self.db.update_order(o["id"], queue_position=i)

    def queue(self) -> dict:
        jobs = [{"order_id": o["id"], "status": o["status"], "colour": o["colour"],
                 "print_seconds": o["print_seconds"], "queue_position": o["queue_position"]}
                for o in self.db.list_orders(status=["paid", "queued"])]
        printing = [o["id"] for o in self.db.list_orders(status="printing")]
        st = self.db.get_state()
        return {"jobs": jobs, "printing": printing, "loaded_colour": st["loaded_colour"],
                "bed_clear": st["bed_clear"], "printer_busy": st["printer_busy"]}

    def printer_status(self) -> dict:
        s = self.pipeline.get_printer().status()
        return {"state": s.state, "progress_pct": s.progress_pct, "remaining_min": s.remaining_min,
                "layer": s.layer, "total_layers": s.total_layers, "job_name": s.job_name}

    def start_next_job(self, actor: str) -> dict:
        st = self.db.get_state()
        if not st["bed_clear"]:
            return {"started": False, "reason": "bed is not clear; wait for the bed_clear task"}
        pstate = self.printer_status()["state"]
        if pstate not in PRINTABLE_FROM:
            return {"started": False, "reason": f"printer is {pstate}, needs IDLE or FINISH"}
        candidates = self.db.list_orders(status=["paid", "queued"])
        if not candidates:
            return {"started": False, "reason": "queue is empty"}
        loaded = st["loaded_colour"]
        pick = next((o for o in candidates if o["colour"] == loaded), candidates[0])
        if pick["colour"] != loaded:
            return {"started": False, "reason": f"no queued job in loaded colour {loaded}; "
                    f"next job {pick['id']} needs {pick['colour']} (request a spool_swap)",
                    "needs_colour": pick["colour"], "order_id": pick["id"]}
        gcode = self.settings.order_dir(pick["id"]) / pick["files"]["gcode_3mf"]
        self.pipeline.get_printer().start(gcode, pick["id"])
        self.db.set_state("printer_busy", True)
        self.db.set_state("bed_clear", False)
        self.set_status(pick["id"], "printing", actor, queue_position=None,
                        eta=_iso(time.time() + (pick["print_seconds"] or 0)))
        self._renumber_queue()
        return {"started": True, "order_id": pick["id"], "colour": loaded}

    def _printing_order(self) -> dict | None:
        rows = self.db.list_orders(status="printing")
        return rows[0] if rows else None

    def pause_print(self, reason: str, actor: str) -> dict:
        self.pipeline.get_printer().pause()
        order = self._printing_order()
        self.emit(order["id"] if order else None, actor, "print_paused", {"reason": reason})
        return {"paused": True, "order_id": order["id"] if order else None}

    def resume_print(self, actor: str) -> dict:
        self.pipeline.get_printer().resume()
        order = self._printing_order()
        self.emit(order["id"] if order else None, actor, "print_resumed", {})
        return {"resumed": True, "order_id": order["id"] if order else None}

    def cancel_print(self, reason: str, actor: str) -> dict:
        self.pipeline.get_printer().stop()
        order = self._printing_order()
        self.db.set_state("printer_busy", False)
        if order:
            self.set_status(order["id"], "failed", actor)
        self.request_human("bed_clear", f"Print cancelled ({reason}); remove the part and clean the bed.",
                           order["id"] if order else None, actor)
        return {"cancelled": True, "order_id": order["id"] if order else None}

    def save_snapshot(self, jpeg: bytes) -> tuple[dict | None, Path]:
        order = self._printing_order()
        if order:
            path = self.settings.order_dir(order["id"]) / "camera.jpg"
        else:
            path = self.settings.data_dir / "snapshots" / "latest.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg)
        return order, path

    def snapshot(self, actor: str) -> dict:
        order, path = self.save_snapshot(self.pipeline.get_printer().snapshot_jpeg())
        url = self.file_url(order, "camera.jpg") if order else None
        return {"url": url, "path": str(path), "order_id": order["id"] if order else None}

    def set_loaded_colour(self, colour: str, actor: str) -> dict:
        stock = self.db.get_state("colours_in_stock")
        if colour not in stock:
            raise ShopError(f"{colour} is not in stock ({', '.join(stock)})")
        self.db.set_state("loaded_colour", colour)
        self.emit(None, actor, "loaded_colour", {"colour": colour})
        return {"loaded_colour": colour}

    def request_human(self, kind: str, details: str, order_id: str | None, actor: str) -> dict:
        if kind not in HUMAN_KINDS:
            raise ShopError(f"kind must be one of {', '.join(HUMAN_KINDS)}")
        task = self.db.add_human_task(kind, details, order_id)
        self.emit(order_id, actor, "human_task", {"kind": kind, "task_id": task["id"], "details": details})
        return task

    # ---- support / finance --------------------------------------------------
    def list_orders(self, status: str | None = None) -> list[dict]:
        return [{"order_id": o["id"], "status": o["status"], "product": o["product"],
                 "colour": o["colour"], "price_cents": o["price_cents"], "created_at": _iso(o["created_at"])}
                for o in self.db.list_orders(status=status)]

    def refund(self, order_id: str, reason: str, actor: str) -> dict:
        order = self.require_order(order_id)
        if not order["payment_id"] or order["status"] == "refunded":
            raise ShopError(f"order {order_id} has no refundable payment (status {order['status']})")
        if (order["price_cents"] or 0) > REFUND_CAP_CENTS:
            task = self.request_human("qa", f"Refund over cap requested for {order_id}: {reason}", order_id, actor)
            return {"refunded": False, "escalated": True, "human_task_id": task["id"],
                    "reason": f"over the ${REFUND_CAP_CENTS / 100:.0f} cap; a human decides"}
        self.whop.refund(payment_id=order["payment_id"])
        self.set_status(order_id, "refunded", actor)
        self.db.add_event(order_id, actor, "refund", {"reason": reason, "amount_cents": order["price_cents"]})
        return {"refunded": True, "amount_cents": order["price_cents"]}

    def financials(self, days: int) -> dict:
        since = time.time() - max(1, int(days)) * 86400
        orders = [o for o in self.db.list_orders() if o["created_at"] >= since]
        paid = [o for o in orders if o["payment_id"]]
        revenue = sum(o["price_cents"] or 0 for o in paid)
        refunds = sum(o["price_cents"] or 0 for o in paid if o["status"] == "refunded")
        fees = sum(round((o["price_cents"] or 0) * WHOP_FEE_BPS / 10000) + WHOP_FEE_FIXED_CENTS for o in paid)
        filament = sum(round((o["filament_grams"] or 0) * FILAMENT_CENTS_PER_GRAM) for o in paid)
        generation = sum(o["gen_cost_cents"] or 0 for o in orders)
        return {"days": days, "orders": len(orders), "paid_orders": len(paid), "revenue_cents": revenue,
                "refunds_cents": refunds, "whop_fees_cents": fees, "filament_cost_cents": filament,
                "generation_cost_cents": generation,
                "margin_cents": revenue - refunds - fees - filament - generation}

    # ---- shared bot tools ---------------------------------------------------
    def post_customer_update(self, order_id: str, text: str, actor: str) -> dict:
        self.require_order(order_id)
        mid = self.add_message(order_id, "agent", text)
        self.db.add_event(order_id, actor, "customer_update", {"message_id": mid})
        return {"message_id": mid}

    def log_decision(self, order_id: str | None, decision: str, reason: str, actor: str) -> dict:
        eid = self.db.add_event(order_id, actor, "decision", {"decision": decision, "reason": reason})
        return {"event_id": eid}

    # ---- agents -------------------------------------------------------------
    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def run_agent(self, profile: str, input_text: str, session_id: str, *,
                        order_id: str | None = None, to_customer: bool = False,
                        idempotency_key: str | None = None) -> str | None:
        async def on_delta(text: str) -> None:
            if to_customer and order_id:
                self.bus.publish(order_id, "agent_delta", {"text": text})

        try:
            result = await self.hermes.run(profile, input_text, session_id,
                                           idempotency_key=idempotency_key, on_delta=on_delta)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("hermes %s run failed: %s", profile, e)
            self.db.add_event(order_id, "system", "agent_run_error", {"profile": profile, "error": str(e)})
            if to_customer and order_id:
                self.add_message(order_id, "system", "The shop agent is unavailable right now. Please try again shortly.")
            return None
        self.db.add_event(order_id, profile, "agent_run",
                          {"run_id": result.run_id, "status": result.status, "session_id": session_id})
        if to_customer and order_id:
            if result.status == "completed" and result.output:
                self.add_message(order_id, "agent", result.output)
            elif result.status != "completed":
                self.add_message(order_id, "system", "The shop agent could not finish that request. Please try again.")
        return result.output

    async def handle_customer_message(self, order_id: str, text: str, measurements: list[dict] | None) -> None:
        order = self.require_order(order_id)
        profile = "intake" if order["status"] in PRE_PAYMENT else "support"
        lines = [f"Customer message for order {order_id}:", text or "(no text)"]
        if measurements:
            lines.append("Measurements: " + "; ".join(f"{m['label']} = {m['mm']} mm" for m in measurements))
        if profile == "intake":
            lines.append("Photos (paths on the factory server): "
                         + json.dumps([str(p) for p in self.photos(order_id)]))
        lines.append("Order: " + json.dumps(self.order_view(order), default=str))
        await self.run_agent(profile, "\n".join(lines), session_id=order_id, order_id=order_id, to_customer=True)

    async def wake(self, profile: str, event: str, order_id: str | None = None,
                   idempotency_key: str | None = None) -> None:
        detail = {"event": event, "order_id": order_id, "shop_state": self.db.get_state(),
                  "open_human_tasks": [{k: t[k] for k in ("id", "kind", "order_id", "details")}
                                       for t in self.db.list_human_tasks(status="open")]}
        if order_id:
            detail["order"] = self.order_view(self.require_order(order_id))
        text = f"Event: {event}\n" + json.dumps(detail, default=str) + "\nAct on it per your rules."
        session = f"{profile}-{order_id or 'shop'}"
        await self.run_agent(profile, text, session_id=session, order_id=order_id, idempotency_key=idempotency_key)
