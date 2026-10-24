"""Micro Factory pipeline library (BE1). See README.md and SPEC.md section "BE1"."""
import os


def is_mock() -> bool:
    """True when FACTORY_MOCK=1. Each module also falls back to its mock when its key is missing."""
    return os.environ.get("FACTORY_MOCK", "") == "1"
