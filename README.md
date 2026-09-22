# Postman Coverage Checker

Checks that every YAML API spec in a GitHub repo has at least one matching
request in the corresponding Postman collection. Produces a JSON report of
missing APIs per core.

## How it works

For each YAML file like `AcctService-11.0.0_PRM-Add_DDA.yaml`:

1. Parse the filename into `(core, service, action, type)`.
2. Locate the Postman collection for that core.
3. Locate the domain folder inside the collection (e.g. `Account Service`).
4. Search for a request name matching the action + subject + type
   (with synonym expansion; numbering prefixes like `1.1.` are stripped).
5. Fall back to a relaxed match, then a collection-wide search.
6. If nothing matches, add to the missing list with top-3 fuzzy suggestions.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
# then edit .env with your tokens
```

Edit `config/cores.yaml` and fill in:

- The GitHub owner/repo/path for each core.
- The Postman `collection_id` for each core (find it in Postman → collection → Info → copy UID).

## Run

```powershell
# One core
python -m postman_coverage --core PRM

# All configured cores
python -m postman_coverage --all
```

Reports land in `reports/<core>-<timestamp>.json`.

## Exit codes

- `0` — all YAMLs have coverage.
- `1` — at least one YAML has no matching Postman request.
- `2` — configuration or credential error.
