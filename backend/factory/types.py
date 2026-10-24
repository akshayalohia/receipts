from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Artifact:
    stl: Path
    glb: Path
    usdz: Path
    png: Path  # all four always produced
    bbox_mm: tuple[float, float, float]  # x, y, z after finishing
    watertight: bool
    volume_cm3: float


@dataclass
class SliceResult:
    gcode_3mf: Path
    print_seconds: int
    filament_grams: float


@dataclass
class Quote:
    price_cents: int
    print_seconds: int
    filament_grams: float
    breakdown: dict[str, int]


@dataclass
class PrinterStatus:
    state: str  # IDLE | PREPARE | RUNNING | PAUSE | FINISH | FAILED | OFFLINE
    progress_pct: int
    remaining_min: int
    layer: int
    total_layers: int
    job_name: str | None
    raw: dict = field(default_factory=dict)
