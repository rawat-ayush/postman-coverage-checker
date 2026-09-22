"""Extract operations from an OpenAPI YAML body.

Used only for *base-service* YAMLs where the filename has no action, e.g.
`SweepService-11.0.0_PRM.yaml`. For every entry under `paths:` we read the
first `tags` value (falling back to `summary`, `operationId`, and finally
the HTTP method) and derive one of the tool's action codes:

    Add / Inq / Mod / Del / ListInq

which are exactly the keys used in `action_synonyms` in the config, so
the matcher can look up Postman requests the same way it does for a
filename that already carries the action.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

# Order matters: more specific patterns first (e.g. "list" before "get").
_ACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\blist\b|\blistinq\b"), "ListInq"),
    (re.compile(r"\bget\b|\binquire\b|\binquiry\b|\bfetch\b|\bretrieve\b|\bread\b|\bview\b|\blookup\b|\bsearch\b"), "Inq"),
    (re.compile(r"\badd\b|\bcreate\b|\bnew\b|\bregister\b|\bpost\b"), "Add"),
    (re.compile(r"\bupdate\b|\bmodify\b|\bmod\b|\bedit\b|\bchange\b|\bpatch\b|\bset\b|\bactivate\b|\bdeactivate\b|\bput\b"), "Mod"),
    (re.compile(r"\bdelete\b|\bremove\b|\bdel\b"), "Del"),
]

_METHOD_TO_ACTION: dict[str, str] = {
    "get": "Inq",
    "head": "Inq",
    "post": "Add",
    "put": "Mod",
    "patch": "Mod",
    "delete": "Del",
}

_HTTP_METHODS = set(_METHOD_TO_ACTION.keys())


@dataclass(frozen=True)
class Operation:
    path: str
    method: str            # uppercase: GET / POST / PUT / DELETE / PATCH / HEAD
    tag: str
    summary: str
    operation_id: str
    action: str            # one of Add / Inq / Mod / Del / ListInq


def extract_operations(yaml_text: str) -> list[Operation]:
    """Parse `yaml_text` as OpenAPI and return one Operation per path+method.

    Silent on parse errors: returns [] so the caller can fall back to the
    filename-only match path.
    """
    try:
        doc: Any = yaml.safe_load(yaml_text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(doc, dict):
        return []

    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return []

    ops: list[Operation] = []
    for path_key, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method_key, op_spec in methods.items():
            method_l = str(method_key).lower()
            if method_l not in _HTTP_METHODS or not isinstance(op_spec, dict):
                continue
            tags = op_spec.get("tags") or []
            tag = str(tags[0]) if tags else ""
            summary = str(op_spec.get("summary") or "")
            op_id = str(op_spec.get("operationId") or "")
            action = _derive_action(tag, summary, op_id, method_l)
            ops.append(
                Operation(
                    path=str(path_key),
                    method=method_l.upper(),
                    tag=tag,
                    summary=summary,
                    operation_id=op_id,
                    action=action,
                )
            )
    return ops


def _derive_action(tag: str, summary: str, op_id: str, method: str) -> str:
    for text in (tag, summary, op_id):
        text_l = text.lower()
        if not text_l:
            continue
        for pat, code in _ACTION_PATTERNS:
            if pat.search(text_l):
                return code
    return _METHOD_TO_ACTION.get(method, "Inq")
