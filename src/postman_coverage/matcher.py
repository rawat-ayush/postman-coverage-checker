"""Match a parsed YAML spec against Postman requests using tiered rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz

from .parser import YamlSpec
from .postman_client import PostmanRequest


class MatchTier(str, Enum):
    STRICT_SCOPED = "strict_scoped"        # right folder + action + subject + type
    RELAXED_SCOPED = "relaxed_scoped"      # right folder + action + subject (no type)
    COLLECTION_WIDE = "collection_wide"    # any folder + action + subject + type
    PARTIAL = "partial"                    # multi-type yaml: only some types found
    NONE = "none"


# Lower value = better match. Used to pick the "weakest of the good tiers"
# when aggregating multiple sub-matches for a multi-type YAML.
_TIER_RANK: dict[MatchTier, int] = {
    MatchTier.STRICT_SCOPED: 0,
    MatchTier.RELAXED_SCOPED: 1,
    MatchTier.COLLECTION_WIDE: 2,
    MatchTier.PARTIAL: 3,
    MatchTier.NONE: 4,
}

# Tiers that mean "the matched Postman request actually contains the type
# token". RELAXED_SCOPED explicitly drops the type to find a match, so it
# is not a real per-type coverage claim.
_TYPE_STRICT_TIERS = {MatchTier.STRICT_SCOPED, MatchTier.COLLECTION_WIDE}


def sub_is_type_covered(r: "MatchResult") -> bool:
    return r.tier in _TYPE_STRICT_TIERS


@dataclass
class MatchResult:
    spec: YamlSpec
    tier: MatchTier
    matched_request: PostmanRequest | None
    suggestions: list[tuple[PostmanRequest, int]]  # (request, fuzzy score)
    # Per-sub-type breakdown when the YAML combined multiple types (e.g.
    # `_DDA_SDA_CDA`). Empty for single-type YAMLs.
    sub_matches: list["MatchResult"] = field(default_factory=list)

    @property
    def is_covered(self) -> bool:
        return self.tier not in (MatchTier.NONE, MatchTier.PARTIAL)


_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+(\.\d+)*\.?\s*)+")
_TOKEN_SPLIT_RE = re.compile(r"[\s\-_/]+")
_CAMEL_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def _camel_tokens(name: str) -> list[str]:
    """Split a CamelCase service name into lowercase tokens, dropping the
    trailing 'service' word so unknown services still map onto their folder.
    E.g. 'PortfolioAddrService' -> ['portfolio', 'addr'].
    """
    parts = [p.lower() for p in _CAMEL_SPLIT_RE.findall(name)]
    return [p for p in parts if p and p != "service"]


def _normalize(name: str) -> set[str]:
    """Lowercase, strip numbering prefix, split into token set."""
    n = _NUMBER_PREFIX_RE.sub("", name or "")
    n = n.lower()
    tokens = {t for t in _TOKEN_SPLIT_RE.split(n) if t}
    return tokens


def _lower_set(values: list[str]) -> set[str]:
    out: set[str] = set()
    for v in values:
        out.add(v.lower())
        # also add multi-word items as individual tokens
        for t in _TOKEN_SPLIT_RE.split(v.lower()):
            if t:
                out.add(t)
    return out


class Matcher:
    def __init__(
        self,
        service_subject_map: dict[str, list[str]],
        action_synonyms: dict[str, list[str]],
        type_synonyms: dict[str, list[str]],
        suggestion_min_score: int = 55,
    ) -> None:
        self._service_subject_map = service_subject_map
        self._action_synonyms = action_synonyms
        self._type_synonyms = type_synonyms
        self._min_score = suggestion_min_score

    def match(self, spec: YamlSpec, requests: list[PostmanRequest]) -> MatchResult:
        subject_values = self._service_subject_map.get(spec.service)
        if subject_values is None:
            subject_values = _camel_tokens(spec.service) or [spec.service]
        subject_tokens = _lower_set(subject_values)
        action_tokens = _lower_set(self._action_synonyms.get(spec.action, [spec.action])) if spec.action else set()
        type_tokens = _lower_set(self._type_synonyms.get(spec.type, [spec.type])) if spec.type else set()

        scoped = [r for r in requests if self._request_in_service_folder(r, subject_tokens)]

        # Tier 1: scoped + all three axes.
        if type_tokens and action_tokens:
            hit = self._find(scoped, subject_tokens, action_tokens, type_tokens)
            if hit:
                return MatchResult(spec, MatchTier.STRICT_SCOPED, hit, [])

        # Tier 2: scoped + action + subject (drop type). If there is no action
        # (base-service YAML), the presence of the folder itself counts as a
        # relaxed match.
        if action_tokens:
            hit = self._find(scoped, subject_tokens, action_tokens, set())
            if hit:
                return MatchResult(spec, MatchTier.RELAXED_SCOPED, hit, [])
        elif scoped:
            return MatchResult(spec, MatchTier.RELAXED_SCOPED, scoped[0], [])

        # Tier 3: collection-wide + all axes we have.
        if action_tokens:
            hit = self._find(requests, subject_tokens, action_tokens, type_tokens)
            if hit:
                return MatchResult(spec, MatchTier.COLLECTION_WIDE, hit, [])

        return self._miss(spec, requests)

    def _miss(self, spec: YamlSpec, pool: list[PostmanRequest]) -> MatchResult:
        target = spec.display.lower()
        scored: list[tuple[PostmanRequest, int]] = []
        for r in pool:
            candidate = _NUMBER_PREFIX_RE.sub("", r.full_path).lower()
            score = int(fuzz.token_set_ratio(target, candidate))
            if score >= self._min_score:
                scored.append((r, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return MatchResult(spec, MatchTier.NONE, None, scored[:3])

    def _request_in_service_folder(
        self, req: PostmanRequest, subject_tokens: set[str]
    ) -> bool:
        for folder in req.folder_path:
            folder_tokens = _normalize(folder)
            if folder_tokens & subject_tokens:
                return True
        return False

    def _find(
        self,
        requests: list[PostmanRequest],
        subject_tokens: set[str],
        action_tokens: set[str],
        type_tokens: set[str],
    ) -> PostmanRequest | None:
        for r in requests:
            name_tokens = _normalize(r.name)
            if not (name_tokens & action_tokens):
                continue
            if not (name_tokens & subject_tokens):
                continue
            if type_tokens and not (name_tokens & type_tokens):
                continue
            return r
        return None
