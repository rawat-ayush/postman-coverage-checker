# postman-coverage-checker

Check whether every YAML API spec on GitHub has a matching request in a
Postman collection, and report the gaps.

## How it works

1. Reads `reference/<Core>/<Domain>/*.yaml` from GitHub for every core in
   the config.
2. Parses each filename into `Service`, `Action`, `Type`
   (e.g. `AcctService-11.0.0_PRM-Add_DDA.yaml` → `AcctService / Add / DDA`).
3. Looks up the Postman folder that matches the *Service* (via a
   configurable synonym map) and searches inside it for a request whose
   name matches the *Action* + *Type*.
4. Rolls per-YAML outcomes up by GitHub *domain* (`Accountholder`,
   `Accounts`, `Debit Cards`, `Servicing`, `Transactions`, `Transfers`,
   …) and writes one JSON report per core to
   `~/Downloads/postman-coverage/`.

Three special cases beyond the plain filename match:

- **Multi-type YAMLs** (`AcctService-…-Add_DDA_SDA_CDA.yaml`) — split
  into per-type sub-checks; covered only when every sub-type has a
  Postman request.
- **Base-service YAMLs** (`SweepService-…_PRM.yaml`, no action in the
  filename) — the tool fetches the YAML content, walks its OpenAPI
  `paths[].tags`, derives one action per operation
  (`Add` / `Inq` / `Mod` / `Del` / `ListInq`) and runs one match per
  distinct action.
- **Unusual filenames** — mixed hyphen/underscore separators, hyphenated
  `region-service`, or services that don't end in "Service"
  (`TellerSignOn`, `TransactionCode`) all parse; the tool anchors on the
  `_<CORE>` token, not a rigid CamelCase pattern.

Each YAML lands in one of four buckets: **covered**, **partial** (some
sub-parts covered), **missing**, or **unparseable**.


## Install

```powershell
git clone <this repo>
cd postman-coverage-checker

python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
```

Two commands become available:

| Command | Purpose |
|---|---|
| `postman-coverage` | headless CLI |
| `postman-coverage-gui` | Tkinter GUI |

Python 3.10+.

## Run

### GUI

```powershell
postman-coverage-gui
```

1. **Config tab** — paste GitHub PAT + Postman API key (+ optional
   workspace ID) into the three fields. Click **Save to OS keyring** so
   future launches load them automatically.
2. **Work tab** — pick a core from the dropdown (or tick *Run all
   cores*), click **Run**.
3. Explore the tree — each core expands into per-domain rows; missing
   and partial YAMLs are color-coded red / yellow with per-part detail.
   Use **Filter** to jump to a specific service or file.

### CLI

```powershell
# one core
postman-coverage --core PRM

# every core in the config
postman-coverage --all

# custom config / reports directory
postman-coverage --config path\to\cores.yaml --reports-dir path\to\reports --all
```

Prints a per-core summary plus a per-domain breakdown. Exits with code
`1` if any YAML is missing or partial (useful for CI gating).

### Where reports go

Default: `%USERPROFILE%\Downloads\postman-coverage\` (Windows) or
`~/Downloads/postman-coverage/` (macOS/Linux). One JSON per core, named
`postman-coverage-checker-report-<CORE>-<UTC timestamp>.json`.

### Credentials — where they're read from

First non-empty value wins per field, in this order:

1. Value typed into the GUI for the current session.
2. `github.token` / `postman.api_key` in the merged config yaml.
3. Environment variables `GITHUB_TOKEN`, `POSTMAN_API_KEY`,
   `POSTMAN_WORKSPACE_ID`.
4. OS keyring (Windows Credential Manager / macOS Keychain / Linux
   Secret Service).

So once you've saved to the keyring from the GUI, both GUI and CLI
work without touching the yaml or the environment.
