import json
import sys
from pathlib import Path

path = sorted(Path("reports").glob("PRM-*.json"))[-1]
d = json.loads(path.read_text(encoding="utf-8"))

print(f"Report: {path}")
print(f"unparseable: {d['unparseable_files']}")
for dm in d["domains"]:
    if not dm["missing"]:
        continue
    print(f"\n[{dm['github_domain']}] missing={len(dm['missing'])}")
    for m in dm["missing"]:
        sugs = [f"{s['postman_request']} ({s['score']})" for s in m["suggestions"][:2]]
        print(f"  {m['yaml_file']}  suggestions: {sugs}")

for dm in d["domains"]:
    if not dm.get("misplaced"):
        continue
    print(f"\n[{dm['github_domain']}] misplaced={len(dm['misplaced'])}")
    for m in dm["misplaced"]:
        print(f"  {m['yaml_file']}  -> {m['matched_request']}")
