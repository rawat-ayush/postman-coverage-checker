import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(
    Path.home().joinpath("Downloads", "postman-coverage").glob("postman-coverage-checker-report-PRM-*.json")
)[-1]
d = json.loads(path.read_text(encoding="utf-8"))
print(f"report: {path}\n")
print(json.dumps({k: d[k] for k in ("core", "core_name", "generated_at_utc", "postman_collection_id", "summary")}, indent=2))
print("\n--- domains (worst first) ---")
for dm in d["domains"]:
    print(f"  {dm['domain']:15s}  {dm['summary']}")

# Show one missing entry
for dm in d["domains"]:
    if dm["missing"]:
        print("\n--- example missing entry ---")
        print(json.dumps(dm["missing"][0], indent=2))
        break

# Show one partial entry
for dm in d["domains"]:
    if dm["partial"]:
        print("\n--- example partial entry ---")
        print(json.dumps(dm["partial"][0], indent=2))
        break
