"""Build and write JSON reports."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .matcher import MatchResult, MatchTier, sub_is_type_covered


@dataclass
class DomainReport:
    github_domain: str
    total_yaml: int
    covered: int
    partial: int
    missing: int
    results: list[MatchResult]

    def to_dict(self) -> dict:
        missing = sorted(
            (r for r in self.results if r.tier is MatchTier.NONE),
            key=lambda r: r.spec.filename,
        )
        partial = sorted(
            (r for r in self.results if r.tier is MatchTier.PARTIAL),
            key=lambda r: r.spec.filename,
        )
        misplaced = sorted(
            (r for r in self.results if r.tier is MatchTier.COLLECTION_WIDE),
            key=lambda r: r.spec.filename,
        )
        covered = sorted(
            (r for r in self.results
             if r.tier in (MatchTier.STRICT_SCOPED, MatchTier.RELAXED_SCOPED)),
            key=lambda r: r.spec.filename,
        )
        return {
            "domain": self.github_domain,
            "summary": {
                "yaml_files": self.total_yaml,
                "missing": self.missing,
                "partial": self.partial,
                "covered": self.covered,
            },
            "missing": [_missing_entry(r) for r in missing],
            "partial": [_partial_entry(r) for r in partial],
            "misplaced": [
                {
                    "yaml_file": r.spec.filename,
                    "matched_request": r.matched_request.full_path if r.matched_request else None,
                }
                for r in misplaced
            ],
            "covered": [r.spec.filename for r in covered],
        }


def _spec_display(r: MatchResult) -> str:
    parts: list[str] = [r.spec.service]
    if r.spec.action:
        parts.append(r.spec.action)
    if r.spec.type:
        parts.append(r.spec.type)
    return " / ".join(parts)


def _closest_matches(r: MatchResult) -> list[dict]:
    return [{"request": s.full_path, "score": score} for s, score in r.suggestions]


def _missing_entry(r: MatchResult) -> dict:
    return {
        "yaml_file": r.spec.filename,
        "spec": _spec_display(r),
        "closest_matches": _closest_matches(r),
    }


def _partial_entry(r: MatchResult) -> dict:
    covered_subs = [sm for sm in r.sub_matches if sub_is_type_covered(sm)]
    missing_subs = [sm for sm in r.sub_matches if not sub_is_type_covered(sm)]
    return {
        "yaml_file": r.spec.filename,
        "spec": _spec_display(r),
        "missing_types": [sm.spec.type for sm in missing_subs],
        "covered_types": [sm.spec.type for sm in covered_subs],
        "matches": [
            f"{sm.spec.type} -> {sm.matched_request.full_path}"
            for sm in covered_subs
            if sm.matched_request
        ],
        "closest_matches_for_missing": [
            {
                "type": sm.spec.type,
                "candidates": _closest_matches(sm),
            }
            for sm in missing_subs
        ],
    }


@dataclass
class CoreReport:
    core_code: str
    core_name: str
    postman_collection_id: str
    total_yaml: int
    covered: int
    partial: int
    missing: int
    unparseable_files: list[str]
    results: list[MatchResult]
    domains: list[DomainReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        # Worst domains first: highest missing count, then highest partial.
        ordered = sorted(
            self.domains,
            key=lambda d: (-d.missing, -d.partial, d.github_domain),
        )
        return {
            "core": self.core_code,
            "core_name": self.core_name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "postman_collection_id": self.postman_collection_id,
            "summary": {
                "yaml_files": self.total_yaml,
                "missing": self.missing,
                "partial": self.partial,
                "covered": self.covered,
                "unparseable": len(self.unparseable_files),
                "domains": len(self.domains),
            },
            "unparseable_files": sorted(self.unparseable_files),
            "domains": [d.to_dict() for d in ordered],
        }


def write_report(report: CoreReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"postman-coverage-checker-report-{report.core_code}-{stamp}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path
