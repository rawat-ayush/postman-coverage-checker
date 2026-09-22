import json
import os
from pathlib import Path

base = Path.home() / "Downloads" / "postman-coverage"
for core in ("PRM", "SIG", "PRC", "DNA", "FNX", "CT"):
    reports = sorted(base.glob(f"postman-coverage-checker-report-{core}-*.json"))
    if not reports:
        print(f"[{core}] no report")
        continue
    d = json.loads(reports[-1].read_text(encoding="utf-8"))
    files = d.get("unparseable_files", [])
    print(f"[{core}] {len(files)} unparseable")
    for f in files:
        print(f"  {f}")
