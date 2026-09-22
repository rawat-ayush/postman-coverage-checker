"""Ad-hoc script: print the real GitHub + Postman structure."""
import sys
from pathlib import Path

# Use the Windows system trust store so corporate MITM CAs are trusted.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, "src")
from postman_coverage.config import load_config  # noqa: E402
from postman_coverage.github_client import GithubClient  # noqa: E402
from postman_coverage.postman_client import PostmanClient  # noqa: E402
import requests  # noqa: E402


def gh_list(cfg, path):
    h = {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"https://api.github.com/repos/Fiserv/banking-hub/contents/{path}"
    r = requests.get(url, params={"ref": "Develop-InWork"}, headers=h, timeout=30)
    if r.status_code != 200:
        print(f"  !! {r.status_code}: {r.text[:200]}")
        return []
    return r.json()


def main():
    cfg = load_config(Path("config/cores.defaults.yaml"))

    print("=== GitHub: reference/ children ===")
    cores = gh_list(cfg, "reference")
    core_dirs = [e["name"] for e in cores if e["type"] == "dir"]
    for c in cores:
        print(f"  {c['type']:4s}  {c['name']}")

    print("\n=== GitHub: reference/<Core>/ children (domains) ===")
    domain_map = {}
    for core in core_dirs:
        print(f"\n[{core}]")
        children = gh_list(cfg, f"reference/{core}")
        subs = [e["name"] for e in children if e["type"] == "dir"]
        files = [e["name"] for e in children if e["type"] == "file"]
        for e in children:
            print(f"  {e['type']:4s}  {e['name']}")
        domain_map[core] = {"dirs": subs, "files": files}

    # -------- Postman side --------
    print("\n=== Postman: workspace collections ===")
    pm = PostmanClient(cfg.postman_api_key)
    s = requests.Session()
    s.headers.update({"X-Api-Key": cfg.postman_api_key})
    params = {}
    if cfg.postman_workspace_id:
        params["workspace"] = cfg.postman_workspace_id
    r = s.get("https://api.getpostman.com/collections", params=params, timeout=30)
    if r.status_code != 200:
        print(f"  !! {r.status_code}: {r.text[:300]}")
        return
    cols = r.json().get("collections", [])
    for c in cols:
        print(f"  {c.get('uid'):40s}  {c.get('name')}")

    print("\n=== Postman: top-level folders per collection ===")
    for c in cols:
        uid = c.get("uid")
        name = c.get("name")
        try:
            coll = pm.get_collection(uid)
        except Exception as exc:  # noqa: BLE001
            print(f"\n[{name}] ERROR: {exc}")
            continue
        tops = coll.folder_names_at(0)
        second = coll.folder_names_at(1)
        print(f"\n[{name}] uid={uid}")
        print(f"  top-level folders : {tops[:20]}{' ...' if len(tops) > 20 else ''}")
        print(f"  depth-1 folders   : {second[:20]}{' ...' if len(second) > 20 else ''}")
        print(f"  total requests    : {len(coll.requests)}")

    # -------- Sample YAML filenames per (core, domain) --------
    print("\n=== Sample GitHub YAML filenames per (core, domain) ===")
    services: set[str] = set()
    for core in ["Premier", "Signature", "Precision", "DNA", "Finxact", "Cleartouch"]:
        for domain in domain_map.get(core, {}).get("dirs", []):
            entries = gh_list(cfg, f"reference/{core}/{domain}")
            yamls = [e["name"] for e in entries if e["type"] == "file" and e["name"].lower().endswith((".yaml", ".yml"))]
            print(f"\n[{core}/{domain}] {len(yamls)} yaml(s)")
            for name in yamls[:6]:
                print(f"  {name}")
                svc = name.split("-", 1)[0]
                services.add(svc)

    print("\n=== Distinct YAML service tokens seen ===")
    for s in sorted(services):
        print(f"  {s}")


if __name__ == "__main__":
    main()
