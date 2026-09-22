import json
import sys
from pathlib import Path

core = (sys.argv[1] if len(sys.argv) > 1 else "SIG").upper()
domain = sys.argv[2] if len(sys.argv) > 2 else "Transactions"
path = sorted(Path("reports").glob(f"{core}-*.json"))[-1]
data = json.loads(path.read_text(encoding="utf-8"))
print(f"report: {path}")
print(f"totals: {data['totals']}")
dm = next(x for x in data["domains"] if x["github_domain"] == domain)
print(f"\n[{domain}] totals: {dm['totals']}")
for entry in dm.get("partial", [])[:3]:
    print(f"\n  YAML: {entry['yaml_file']}")
    print(f"    type: {entry['type']}")
    for c in entry.get("sub_types_covered", []):
        print(f"    + {c['type']}: {c['matched_request']}")
    for m in entry.get("sub_types_missing", []):
        sugs = ", ".join(f"{s['postman_request']} ({s['score']})" for s in m["suggestions"][:1])
        print(f"    - {m['type']}: MISSING  (top suggestion: {sugs or '(none)'})")
