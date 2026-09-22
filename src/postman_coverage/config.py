"""Configuration + environment loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class GithubSource:
    owner: str
    repo: str
    path: str
    branch: str = "main"


@dataclass
class CoreConfig:
    code: str
    name: str
    github: GithubSource
    postman_collection_id: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    cores: dict[str, CoreConfig]
    service_subject_map: dict[str, list[str]]
    action_synonyms: dict[str, list[str]]
    type_synonyms: dict[str, list[str]]
    suggestion_min_score: int
    github_token: str
    postman_api_key: str
    postman_workspace_id: str

    def resolve_core(self, code: str) -> CoreConfig | None:
        code_u = code.upper()
        if code_u in self.cores:
            return self.cores[code_u]
        for core in self.cores.values():
            if code_u in {a.upper() for a in core.aliases}:
                return core
        return None


def _require_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _kr_get(key: str) -> str | None:
    """Best-effort OS keyring lookup; returns None if unavailable."""
    try:
        from . import credentials

        return credentials.get(key)
    except Exception:  # noqa: BLE001
        return None


# Filenames are merged left-to-right; later entries win. This lets a
# `cores.local.yaml` hold just credentials while the shared file supplies
# the cores and matcher tables (and vice versa).
_MERGE_ORDER = ("cores.defaults.yaml", "cores.yaml", "cores.local.yaml")


def _deep_merge(base: dict, overlay: dict) -> dict:
    out: dict = dict(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_and_merge(config_path: Path) -> dict[str, Any]:
    """Load `config_path`, then overlay any sibling files in `_MERGE_ORDER`.

    The chosen file is always applied last so its values win, even if it
    comes earlier in `_MERGE_ORDER`.
    """
    merged: dict[str, Any] = {}
    parent = config_path.parent
    for name in _MERGE_ORDER:
        sibling = parent / name
        if sibling.exists() and sibling.resolve() != config_path.resolve():
            merged = _deep_merge(merged, _read_yaml(sibling))
    merged = _deep_merge(merged, _read_yaml(config_path))
    return merged


def load_config(
    config_path: Path,
    *,
    github_token: str | None = None,
    postman_api_key: str | None = None,
    postman_workspace_id: str | None = None,
) -> AppConfig:
    load_dotenv()

    raw = _read_and_merge(config_path)

    cores: dict[str, CoreConfig] = {}
    for code, data in (raw.get("cores") or {}).items():
        gh = data.get("github") or {}
        cores[code.upper()] = CoreConfig(
            code=code.upper(),
            name=data.get("name", code),
            github=GithubSource(
                owner=gh.get("owner", ""),
                repo=gh.get("repo", ""),
                path=gh.get("path", ""),
                branch=gh.get("branch", "main"),
            ),
            postman_collection_id=data.get("postman_collection_id", ""),
            aliases=list(data.get("aliases") or []),
        )

    matcher = raw.get("matcher") or {}

    yaml_gh = (raw.get("github") or {})
    yaml_pm = (raw.get("postman") or {})

    def _pick(*values: str | None) -> str:
        for v in values:
            if v is None:
                continue
            s = str(v).strip()
            if s and s != "CHANGE_ME":
                return s
        return ""

    gh_tok = _pick(
        github_token,
        yaml_gh.get("token"),
        os.getenv("GITHUB_TOKEN"),
        _kr_get("github_token"),
    )
    pm_key = _pick(
        postman_api_key,
        yaml_pm.get("api_key"),
        os.getenv("POSTMAN_API_KEY"),
        _kr_get("postman_api_key"),
    )
    ws_id = _pick(
        postman_workspace_id,
        yaml_pm.get("workspace_id"),
        os.getenv("POSTMAN_WORKSPACE_ID"),
        _kr_get("postman_workspace_id"),
    )
    if not gh_tok:
        raise RuntimeError(
            "Missing GitHub token (set GITHUB_TOKEN env, save via GUI to OS keyring, "
            "or put github.token in the config)."
        )
    if not pm_key:
        raise RuntimeError(
            "Missing Postman API key (set POSTMAN_API_KEY env, save via GUI to OS keyring, "
            "or put postman.api_key in the config)."
        )

    return AppConfig(
        cores=cores,
        service_subject_map=raw.get("service_subject_map") or {},
        action_synonyms=raw.get("action_synonyms") or {},
        type_synonyms=raw.get("type_synonyms") or {},
        suggestion_min_score=int(matcher.get("suggestion_min_score", 55)),
        github_token=gh_tok,
        postman_api_key=pm_key,
        postman_workspace_id=ws_id,
    )
