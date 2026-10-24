"""HTTP API (SPEC.md "HTTP API (service/app.py, FastAPI)")."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .core import CATALOG, PRODUCTS, SSE_TYPES, Core, ShopError
from .monitor import PrinterMonitor
from .voice import mint_conversation_token
from .whop import WebhookError, verify_webhook

log = logging.getLogger("factory.app")

HEARTBEAT_S = 15
MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
               "image/heic": ".heic", "image/heif": ".heic"}
PHOTO_EXTS = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".heic": ".heic", ".heif": ".heic"}


class OrderIn(BaseModel):
    product: str


class Measurement(BaseModel):
    label: str
    mm: float


class MessageIn(BaseModel):
    text: str = ""
    measurements: list[Measurement] | None = None
    colour: str | None = None


class VoiceIn(BaseModel):
    order_id: str


class SpoolIn(BaseModel):
    colour: str


class StockIn(BaseModel):
    colours: list[str] = Field(min_length=1)


def create_app(core: Core | None = None, *, start_monitor: bool = True) -> FastAPI:
    core = core or Core(Settings.from_env())
    settings = core.settings
    monitor = PrinterMonitor(core)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(monitor.run()) if start_monitor else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Micro Factory", lifespan=lifespan)
    app.state.core = core
    app.state.monitor = monitor

    @app.exception_handler(ShopError)
    async def shop_error(_: Request, exc: ShopError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ---- auth ---------------------------------------------------------------
    def app_key_ok(request: Request) -> bool:
        key = request.headers.get("x-app-key", "")
        if settings.app_shared_secret:
            return hmac.compare_digest(key, settings.app_shared_secret)
        return settings.mock and bool(key)      # no secret configured: mock mode only

    def device(request: Request) -> str:
        dev = request.headers.get("x-device-id", "").strip()
        if not dev or not app_key_ok(request):
            raise HTTPException(401, "X-App-Key and X-Device-Id required")
        return dev

    def admin(request: Request) -> None:
        key = request.headers.get("x-admin-key", "")
        if not settings.admin_key or not hmac.compare_digest(key, settings.admin_key):
            raise HTTPException(401, "X-Admin-Key required")

    def owned(order_id: str, dev: str) -> dict:
        order = core.db.get_order(order_id)
        if order is None or order["device_id"] != dev:
            raise HTTPException(404, "order not found")
        return order

    # ---- public -------------------------------------------------------------
    @app.get("/health")
    async def health():
        try:
            state = (await asyncio.to_thread(core.printer_status))["state"]
        except Exception:
            state = "OFFLINE"
        return {"ok": True, "mock": settings.mock, "printer_state": state}

    @app.get("/catalog")
    async def catalog(dev: str = Depends(device)):
        floors = core.get_policy().get("floors_cents", {})
        products = [{**p, "from_price_cents": floors.get(p["id"])} for p in CATALOG]
        return {"products": products, "colours_in_stock": core.db.get_state("colours_in_stock"),
                "loaded_colour": core.db.get_state("loaded_colour")}

    # ---- orders -------------------------------------------------------------
    @app.post("/orders")
    async def create_order(body: OrderIn, dev: str = Depends(device)):
        if body.product not in PRODUCTS:
            raise HTTPException(400, f"unknown product {body.product}")
        order = core.db.create_order(dev, body.product, None)
        core.db.add_event(order["id"], "app", "order_created", {"product": body.product})
        return core.order_view(order)

    @app.get("/orders")
    async def list_orders(dev: str = Depends(device)):
        return {"orders": [core.order_view(o) for o in core.db.list_orders(device_id=dev)]}

    @app.get("/orders/{order_id}")
    async def get_order(order_id: str, dev: str = Depends(device)):
        order = owned(order_id, dev)
        view = core.order_view(order)
        view["messages"] = [{k: m[k] for k in ("id", "role", "text", "media", "created_at")}
                            for m in core.db.list_messages(order_id)]
        view["photos"] = [core.file_url(order, p.name) for p in core.photos(order_id)]
        return view

    @app.post("/orders/{order_id}/photos")
    async def upload_photos(order_id: str, request: Request, dev: str = Depends(device)):
        order = owned(order_id, dev)
        form = await request.form()
        uploads = list(form.getlist("files[]")) + list(form.getlist("files"))
        existing = core.photos(order_id)
        if not uploads:
            raise HTTPException(400, "no files[] in form")
        if len(existing) + len(uploads) > MAX_PHOTOS:
            raise HTTPException(400, f"at most {MAX_PHOTOS} photos per order")
        d = settings.upload_dir(order_id)
        d.mkdir(parents=True, exist_ok=True)
        urls = []
        for i, up in enumerate(uploads, start=len(existing) + 1):
            ext = PHOTO_TYPES.get((up.content_type or "").lower()) or PHOTO_EXTS.get(Path(up.filename or "").suffix.lower())
            if not ext:
                raise HTTPException(415, "photos must be jpeg, heic or png")
            data = await up.read()
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "photo too large")
            name = f"photo_{i}{ext}"
            (d / name).write_bytes(data)
            urls.append(core.file_url(order, name))
        core.db.add_event(order_id, "app", "photos_uploaded", {"count": len(urls)})
        return {"urls": urls}

    @app.post("/orders/{order_id}/messages", status_code=202)
    async def post_message(order_id: str, body: MessageIn, tasks: BackgroundTasks, dev: str = Depends(device)):
        order = owned(order_id, dev)
        if body.colour:
            stock = core.db.get_state("colours_in_stock")
            if body.colour not in stock:
                raise HTTPException(400, f"colour must be one of {', '.join(stock)}")
            core.db.update_order(order_id, colour=body.colour)
        measurements = [m.model_dump() for m in body.measurements or []]
        text = body.text
        if measurements:
            text = (text + "\n" if text else "") + "Measurements: " + ", ".join(
                f"{m['label']} {m['mm']:g} mm" for m in measurements)
        if body.colour:
            text = (text + "\n" if text else "") + f"Colour: {body.colour}"
        mid = core.add_message(order_id, "user", text)
        if order["status"] in ("draft", "review", "quoted"):
            core.set_status(order_id, "designing", "app")
        tasks.add_task(core.handle_customer_message, order_id, body.text, measurements)
        return {"message_id": mid}

    @app.get("/orders/{order_id}/stream")
    async def stream(order_id: str, request: Request, dev: str = Depends(device)):
        owned(order_id, dev)

        async def events():
            sub = core.bus.subscribe(order_id)
            try:
                yield ": connected\n\n"
                while not await request.is_disconnected():
                    ev = await sub.get(timeout=HEARTBEAT_S)
                    if ev is None:
                        yield ": heartbeat\n\n"
                    elif ev.type in SSE_TYPES:
                        yield f"event: {ev.type}\ndata: {json.dumps(ev.data, default=str)}\n\n"
            finally:
                sub.close()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/orders/{order_id}/accept", status_code=202)
    async def accept(order_id: str, tasks: BackgroundTasks, dev: str = Depends(device)):
        order = owned(order_id, dev)
        if order["status"] == "quoted":
            return {"status": "quoted", "quote": core.quote_view(order)}
        if order["status"] != "review":
            raise HTTPException(409, f"order is {order['status']}; nothing to accept")
        core.db.add_event(order_id, "app", "design_accepted", {"version": order["design_version"]})

        async def quote_then_wake_sales():
            try:
                await asyncio.to_thread(core.prepare_quote, order_id, "sales")
            except Exception as e:
                log.exception("prepare_quote failed for %s", order_id)
                core.db.add_event(order_id, "system", "quote_failed", {"error": str(e)})
                core.add_message(order_id, "system", "We could not price this design yet. The shop agent will follow up.")
                return
            await core.wake("sales", "design_accepted", order_id)

        tasks.add_task(quote_then_wake_sales)
        return {"status": "quoting"}

    @app.get("/files/{order_id}/{name}")
    async def files(order_id: str, name: str, request: Request, sig: str = ""):
        order = core.db.get_order(order_id)
        if order is None:
            raise HTTPException(404, "not found")
        signed = bool(sig) and hmac.compare_digest(sig, core.file_sig(order))
        header_ok = (request.headers.get("x-device-id") == order["device_id"] and app_key_ok(request))
        if not (signed or header_ok):
            raise HTTPException(401, "bad signature")
        path = core.file_path(order_id, name)
        if path is None:
            raise HTTPException(404, "not found")
        media = {".usdz": "model/vnd.usdz+zip", ".glb": "model/gltf-binary", ".stl": "model/stl",
                 ".heic": "image/heic"}.get(path.suffix.lower())
        return FileResponse(path, media_type=media)

    @app.get("/orders/{order_id}/camera.jpg")
    async def camera(order_id: str, dev: str = Depends(device)):
        order = owned(order_id, dev)
        if order["status"] != "printing":
            raise HTTPException(409, "camera is only available while this order is printing")
        try:
            jpeg = await asyncio.to_thread(lambda: core.pipeline.get_printer().snapshot_jpeg())
            core.save_snapshot(jpeg)
        except Exception:
            cached = settings.order_dir(order_id) / "camera.jpg"
            if not cached.is_file():
                raise HTTPException(503, "camera unavailable")
            jpeg = cached.read_bytes()
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/voice/token")
    async def voice_token(body: VoiceIn, dev: str = Depends(device)):
        owned(body.order_id, dev)
        return await mint_conversation_token(settings)

    # ---- payments -----------------------------------------------------------
    def find_paid_order(data: dict) -> dict | None:
        """Map a Whop payment object to our order: `plan.id` (the `plan_` id we stored as
        whop_variant_id), else `metadata.order_id` (plan metadata is copied into payment
        webhooks per the create-plan docs; checked on the payment and on its plan)."""
        plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
        for vid in (plan.get("id"), data.get("plan_id")):
            if vid and (order := core.db.find_order_by_variant(vid)):
                return order
        for meta in (data.get("metadata"), plan.get("metadata")):
            if isinstance(meta, dict) and meta.get("order_id"):
                return core.db.get_order(str(meta["order_id"]))
        return None

    @app.post("/webhooks/whop")
    async def whop_webhook(request: Request, tasks: BackgroundTasks):
        body = await request.body()
        try:
            webhook_id = verify_webhook(settings.whop_webhook_secret, request.headers, body)
        except WebhookError as e:
            raise HTTPException(401, f"invalid webhook: {e}")
        event = json.loads(body)
        if event.get("type") != "payment.succeeded":
            core.db.add_event(None, "whop", "webhook_ignored", {"type": event.get("type"), "id": webhook_id})
            return {"ok": True, "ignored": True}
        data = event.get("data") or {}
        payment_id = data.get("id")
        order = find_paid_order(data)
        if not payment_id or order is None:
            core.db.add_event(None, "whop", "webhook_unmatched", {"id": webhook_id, "payment_id": payment_id})
            return {"ok": True, "matched": False}
        if not core.mark_paid(order, payment_id, "whop"):
            return {"ok": True, "duplicate": True}
        tasks.add_task(core.wake, "production", "payment_succeeded", order["id"], payment_id)
        return {"ok": True, "order_id": order["id"]}

    @app.post("/dev/pay/{order_id}")
    async def dev_pay(order_id: str, tasks: BackgroundTasks, dev: str = Depends(device)):
        if not settings.mock:
            raise HTTPException(404, "not found")
        order = owned(order_id, dev)
        if order["status"] != "quoted":
            raise HTTPException(409, f"order is {order['status']}, not quoted")
        payment_id = f"pay_dev_{order_id}"
        if core.mark_paid(order, payment_id, "whop"):
            tasks.add_task(core.wake, "production", "payment_succeeded", order_id, payment_id)
        return {"ok": True, "order_id": order_id, "payment_id": payment_id}

    # ---- admin --------------------------------------------------------------
    @app.get("/admin/state", dependencies=[Depends(admin)])
    async def admin_state():
        try:
            printer = await asyncio.to_thread(core.printer_status)
        except Exception as e:
            printer = {"state": "OFFLINE", "error": str(e)}
        return {"shop_state": core.db.get_state(), "queue": core.queue(), "printer": printer,
                "open_human_tasks": core.db.list_human_tasks(status="open")}

    @app.post("/admin/spool", dependencies=[Depends(admin)])
    async def admin_spool(body: SpoolIn, tasks: BackgroundTasks):
        result = core.set_loaded_colour(body.colour, "admin")
        for t in core.db.list_human_tasks(status="open", kind="spool_swap"):
            core.db.finish_human_task(t["id"])
        tasks.add_task(core.wake, "production", "spool_loaded")
        return result

    def bed_cleared(tasks: BackgroundTasks) -> None:
        core.db.set_state("bed_clear", True)
        for t in core.db.list_human_tasks(status="open", kind="bed_clear"):
            core.db.finish_human_task(t["id"])
        core.db.add_event(None, "admin", "bed_cleared", {})
        tasks.add_task(core.wake, "production", "bed_cleared")

    @app.post("/admin/bed-cleared", dependencies=[Depends(admin)])
    async def admin_bed_cleared(tasks: BackgroundTasks):
        bed_cleared(tasks)
        return {"bed_clear": True}

    @app.get("/admin/human-tasks", dependencies=[Depends(admin)])
    async def admin_human_tasks(status: str | None = None):
        return {"tasks": core.db.list_human_tasks(status=status)}

    @app.post("/admin/human-tasks/{task_id}/done", dependencies=[Depends(admin)])
    async def admin_task_done(task_id: int, tasks: BackgroundTasks):
        task = core.db.get_human_task(task_id)
        if task is None:
            raise HTTPException(404, "no such task")
        if task["kind"] == "bed_clear" and task["status"] == "open":
            bed_cleared(tasks)
        return core.db.finish_human_task(task_id)

    @app.post("/admin/stock", dependencies=[Depends(admin)])
    async def admin_stock(body: StockIn):
        colours = [c.strip() for c in body.colours if c.strip()]
        core.db.set_state("colours_in_stock", colours)
        core.db.add_event(None, "admin", "stock", {"colours": colours})
        return {"colours_in_stock": colours}

    return app
