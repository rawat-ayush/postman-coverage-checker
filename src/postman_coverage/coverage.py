"""Coverage check shared by the CLI and the GUI.

Model
-----
- On GitHub, each core lives at `reference/<Core>/<Domain>/*.yaml` where
  <Domain> is a business grouping (Accountholder, Accounts, Debit Cards,
  Servicing, Transactions, Transfers, ...).

- In Postman, the collection for that core has folders named after the
  YAML *Service* (e.g. `Account Service`, `Address Service`, `Card
  Service`). Postman folders are NOT named after the GitHub domains.

For every YAML we therefore:
  1. Parse the filename into (Service, Action, Type).
  2. If Type combines multiple sub-types (e.g. `DDA_SDA_CDA`), split it
     and require each sub-type to have its own matching Postman request.
  3. Ask the matcher to find a request whose Postman folder name
     matches the Service (via `service_subject_map`) and whose request
     name matches the Action + Type.

Aggregation for multi-type YAMLs:
  - all sub-types matched  -> covered (weakest of the good tiers)
  - some sub-types matched -> PARTIAL (report which types are missing)
  - none matched           -> NONE   (missing)

Domain grouping is preserved only for the *report rollup* so the user
can see "Accounts: 20 covered, 3 missing" per domain, but every YAML is
matched against the whole collection using the Service axis.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from .config import AppConfig, CoreConfig
from .github_client import GithubClient
from .matcher import _TIER_RANK, Matcher, MatchResult, MatchTier, sub_is_type_covered
from .parser import YamlSpec, parse_filename
from .postman_client import PostmanClient
from .report import CoreReport, DomainReport

Logger = Callable[[str], None]


def _split_types(t: str | None) -> list[str | None]:
    """Split a multi-type suffix like `DDA_SDA_CDA` into its parts.

    Only splits when the type contains `_`; single-type YAMLs are returned
    unchanged. A `None` type is returned as `[None]` so callers can treat
    the loop uniformly.
    """
    if not t:
        return [t]
    if "_" not in t:
        return [t]
    parts = [p for p in t.split("_") if p]
    return parts if len(parts) > 1 else [t]


def _sub_is_covered(r: MatchResult) -> bool:
    return sub_is_type_covered(r)


def _match_with_type_expansion(
    spec: YamlSpec, matcher: Matcher, requests: list
) -> MatchResult:
    """Run the matcher; if the YAML combines multiple types, run one match
    per type and aggregate into a single result with per-type sub_matches.
    """
    types = _split_types(spec.type)
    if len(types) == 1:
        return matcher.match(spec, requests)

    sub_results: list[MatchResult] = []
    for t in types:
        sub_spec = replace(spec, type=t)
        sub_results.append(matcher.match(sub_spec, requests))

    covered_subs = [r for r in sub_results if _sub_is_covered(r)]
    missing_subs = [r for r in sub_results if not _sub_is_covered(r)]

    if not missing_subs:
        # All types covered -> use the weakest of the good tiers.
        tier = max((r.tier for r in sub_results), key=lambda t: _TIER_RANK[t])
        matched = covered_subs[0].matched_request if covered_subs else None
        return MatchResult(spec, tier, matched, [], sub_matches=sub_results)

    if covered_subs:
        matched = covered_subs[0].matched_request
        merged_suggestions: list = []
        for r in missing_subs:
            merged_suggestions.extend(r.suggestions)
        return MatchResult(spec, MatchTier.PARTIAL, matched, merged_suggestions[:5], sub_matches=sub_results)

    merged_suggestions = []
    for r in sub_results:
        merged_suggestions.extend(r.suggestions)
    return MatchResult(spec, MatchTier.NONE, None, merged_suggestions[:5], sub_matches=sub_results)


def check_core(
    core: CoreConfig,
    cfg: AppConfig,
    gh: GithubClient,
    pm: PostmanClient,
    matcher: Matcher,
    log: Logger | None = None,
) -> CoreReport:
    if not core.postman_collection_id or "CHANGE_ME" in core.postman_collection_id:
        raise RuntimeError("postman_collection_id not configured")
    if "CHANGE_ME" in (core.github.owner + core.github.repo + core.github.path):
        raise RuntimeError("github source not configured")

    _log = log or (lambda _msg: None)

    files = gh.list_yaml_files(
        core.github.owner, core.github.repo, core.github.path, core.github.branch
    )
    collection = pm.get_collection(core.postman_collection_id)
    _log(
        f"[{core.code}] fetched {len(files)} yaml file(s) and "
        f"{len(collection.requests)} Postman request(s)\n"
    )

    aliases_upper = {a.upper() for a in core.aliases}
    prefix = core.github.path.strip("/") + "/"

    unparseable: list[str] = []
    by_domain: dict[str, list[tuple[str, YamlSpec]]] = {}
    for f in files:
        rel = f.path[len(prefix):] if f.path.startswith(prefix) else f.path
        parts = rel.split("/")
        domain = parts[0] if len(parts) > 1 else "(root)"

        spec = parse_filename(f.name)
        if spec is None:
            unparseable.append(f.path)
            continue
        if spec.core.upper() != core.code and spec.core.upper() not in aliases_upper:
            continue
        by_domain.setdefault(domain, []).append((f.path, spec))

    domain_reports: list[DomainReport] = []
    all_results: list[MatchResult] = []

    for github_domain in sorted(by_domain):
        entries = by_domain[github_domain]
        results = [
            _match_with_type_expansion(spec, matcher, collection.requests)
            for _p, spec in entries
        ]
        covered = sum(1 for r in results if r.tier not in (MatchTier.NONE, MatchTier.PARTIAL))
        partial = sum(1 for r in results if r.tier is MatchTier.PARTIAL)
        missing = sum(1 for r in results if r.tier is MatchTier.NONE)
        domain_reports.append(
            DomainReport(
                github_domain=github_domain,
                total_yaml=len(results),
                covered=covered,
                partial=partial,
                missing=missing,
                results=results,
            )
        )
        _log(
            f"[{core.code}] {github_domain}: "
            f"yaml={len(results)} covered={covered} partial={partial} missing={missing}\n"
        )
        all_results.extend(results)

    total_covered = sum(d.covered for d in domain_reports)
    total_partial = sum(d.partial for d in domain_reports)
    total_missing = sum(d.missing for d in domain_reports)
    return CoreReport(
        core_code=core.code,
        core_name=core.name,
        postman_collection_id=core.postman_collection_id,
        total_yaml=len(all_results),
        covered=total_covered,
        partial=total_partial,
        missing=total_missing,
        unparseable_files=unparseable,
        results=all_results,
        domains=domain_reports,
    )
