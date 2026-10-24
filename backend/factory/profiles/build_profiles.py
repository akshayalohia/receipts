"""Regenerate the flattened Bambu Lab A1 profiles in this folder from an OrcaSlicer install.

OrcaSlicer's CLI wants self-contained JSON, but its bundled BBL profiles inherit from a chain
of parents. This resolves each `inherits` chain by `name` (child keys override the parent),
then makes the result loadable from the CLI:
  - `from` = "User", `is_custom_defined` = "0", no `inherits`;
  - process + filament: `""` added to `compatible_printers`, `compatible_printers_condition` cleared;
  - machine + process: `curr_bed_type` = "Textured PEI Plate".

usage (stdlib only; -I keeps the Orca resources folder off the import path):
    python3 -I backend/factory/profiles/build_profiles.py \
        tools/orca/squashfs-root/resources/profiles/BBL [out_dir]
out_dir defaults to this folder. Last regenerated from OrcaSlicer v2.4.2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGETS = {  # kind -> (Orca profile name, output file)
    "machine": ("Bambu Lab A1 0.4 nozzle", "machine_a1_0.4.json"),
    "process": ("0.20mm Standard @BBL A1", "process_0.20mm_standard_a1.json"),
    "filament": ("Generic PLA @BBL A1", "filament_generic_pla_a1.json"),
}
BED_TYPE = "Textured PEI Plate"


def load_index(bbl_dir: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for kind in TARGETS:
        for p in sorted((bbl_dir / kind).rglob("*.json")):
            d = json.loads(p.read_text())
            if "name" in d:
                index[d["name"]] = d
    return index


def resolve(index: dict[str, dict], name: str) -> dict:
    d = index[name]
    merged = resolve(index, d["inherits"]) if d.get("inherits") else {}
    merged.update({k: v for k, v in d.items() if k != "inherits"})
    return merged


def flatten(index: dict[str, dict], kind: str, name: str) -> dict:
    d = resolve(index, name)
    d.pop("inherits", None)
    d["from"] = "User"
    d["is_custom_defined"] = "0"
    if kind in ("process", "filament"):
        cp = list(d.get("compatible_printers", []))
        if "" not in cp:
            cp.append("")
        d["compatible_printers"] = cp
        d["compatible_printers_condition"] = ""
    if kind in ("machine", "process"):
        d["curr_bed_type"] = BED_TYPE
    return d


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__.strip().split("usage")[1], file=sys.stderr)
        return 2
    bbl_dir = Path(argv[1])
    out = Path(argv[2]) if len(argv) == 3 else Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    index = load_index(bbl_dir)
    for kind, (name, filename) in TARGETS.items():
        d = flatten(index, kind, name)
        (out / filename).write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
        print(f"{kind}: {name!r} -> {out / filename} ({len(d)} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
