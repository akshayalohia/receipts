"""Print-failure check on a camera snapshot with a Gemini Flash vision call. Mock returns ok."""
from __future__ import annotations

import json
import logging
import os

from . import is_mock

log = logging.getLogger(__name__)

# Google's rolling alias for the newest Flash model; pinned ids change too often to hard-code here.
GEMINI_MODEL = "gemini-flash-latest"
VERDICTS = ("ok", "spaghetti", "detached", "empty_bed", "unknown")
_PROMPT = (
    "You are watching a Bambu Lab A1 3D printer through its built-in camera. Judge the print on the bed. "
    "ok = a print is visibly building normally (or the bed shows a normal first layer); "
    "spaghetti = loose tangled filament strands instead of a solid part; "
    "detached = the part has come loose, toppled or moved on the bed; "
    "empty_bed = no part at all on the bed while a print should be running; "
    "unknown = the image is too dark/blurry/obstructed to tell. "
    'Reply as JSON: {"verdict": one of ok|spaghetti|detached|empty_bed|unknown, "confidence": 0..1}.'
)
_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "confidence": {"type": "number"}},
    "required": ["verdict", "confidence"],
}


def check_snapshot(jpeg: bytes) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "")
    if is_mock() or not key:
        return {"verdict": "ok", "confidence": 1.0}
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), _PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               response_json_schema=_SCHEMA, temperature=0.0),
        )
        data = json.loads(resp.text)
        verdict = data.get("verdict") if data.get("verdict") in VERDICTS else "unknown"
        conf = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
        return {"verdict": verdict, "confidence": conf}
    except Exception as e:  # a failed check must never crash the printer monitor
        log.warning("failure check failed: %s", e)
        return {"verdict": "unknown", "confidence": 0.0}
