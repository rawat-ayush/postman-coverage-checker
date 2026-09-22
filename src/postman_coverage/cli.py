"""CLI entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AppConfig, CoreConfig, load_config
from .coverage import check_core
from .github_client import GithubClient
from .matcher import Matcher
from .postman_client import PostmanClient
from .report import write_report

_DEFAULT_CONFIG = Path("config/cores.yaml")


def _default_reports_dir() -> Path:
    try:
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            return downloads / "postman-coverage"
    except Exception:  # noqa: BLE001
        pass
    return Path("reports")


_DEFAULT_REPORTS = _default_reports_dir()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    matcher = Matcher(
        service_subject_map=cfg.service_subject_map,
        action_synonyms=cfg.action_synonyms,
        type_synonyms=cfg.type_synonyms,
        suggestion_min_score=cfg.suggestion_min_score,
    )
    gh = GithubClient(cfg.github_token)
    pm = PostmanClient(cfg.postman_api_key)

    cores_to_run = _select_cores(cfg, args)
    if not cores_to_run:
        print("No cores selected. Use --core <CODE> or --all.", file=sys.stderr)
        return 2

    any_missing = False
    for core in cores_to_run:
        try:
            report = check_core(core, cfg, gh, pm, matcher, log=lambda m: sys.stderr.write(m))
        except Exception as exc:  # noqa: BLE001
            print(f"[{core.code}] FAILED: {exc}", file=sys.stderr)
            any_missing = True
            continue
        out_path = write_report(report, args.reports_dir)
        print(
            f"[{core.code}] domains={len(report.domains)} "
            f"yaml={report.total_yaml} covered={report.covered} "
            f"partial={report.partial} missing={report.missing} "
            f"unparseable={len(report.unparseable_files)} -> {out_path}"
        )
        for d in report.domains:
            print(
                f"  - {d.github_domain}: "
                f"yaml={d.total_yaml} covered={d.covered} "
                f"partial={d.partial} missing={d.missing}"
            )
        if report.missing > 0 or report.partial > 0:
            any_missing = True

    return 1 if any_missing else 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="postman-coverage",
        description="Check YAML API specs against a Postman workspace.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--core", help="Core code to check (e.g. PRM). Case-insensitive.")
    g.add_argument("--all", action="store_true", help="Check every core in config.")
    p.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help=f"Path to cores.yaml (default: {_DEFAULT_CONFIG}).",
    )
    p.add_argument(
        "--reports-dir",
        type=Path,
        default=_DEFAULT_REPORTS,
        help=f"Directory for JSON reports (default: {_DEFAULT_REPORTS}).",
    )
    return p


def _select_cores(cfg: AppConfig, args: argparse.Namespace) -> list[CoreConfig]:
    if args.all:
        return list(cfg.cores.values())
    if args.core:
        core = cfg.resolve_core(args.core)
        return [core] if core else []
    return []
