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
    COLLECTION_WIDE = "collection_wide"    # deprecated: retained for backwards-compat, never emitted
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
# Generic filler words that appear in Postman folder names but carry no
# service identity. Ignored when doing strict folder-name comparisons for
# unknown (unconfigured) services.
_FOLDER_FILLER = {"service", "services", "svc"}


def _camel_tokens(name: str) -> list[str]:
    """Split a CamelCase service name into lowercase tokens, dropping the
    trailing 'service' word so unknown services still map onto their folder.
    E.g. 'PortfolioAddrService' -> ['portfolio', 'addr'].
    """
    parts = [p.lower() for p in _CAMEL_SPLIT_RE.findall(name)]
    return [p for p in parts if p and p != "service"]


def _normalize(name: str) -> set[str]:
    """Lowercase, strip numbering prefix, split into token set. Also splits
    CamelCase runs so a Postman request named 'Update SafeDepositBoxService'
    yields {'update', 'safe', 'deposit', 'box', 'service', ...} instead of
    a single opaque 'safedepositboxservice' token.
    """
    n = _NUMBER_PREFIX_RE.sub("", name or "")
    tokens: set[str] = set()
    for part in _TOKEN_SPLIT_RE.split(n):
        if not part:
            continue
        tokens.add(part.lower())
        for cam in _CAMEL_SPLIT_RE.findall(part):
            c = cam.lower()
            if c:
                tokens.add(c)
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


def _variant_token_sets(values: list[str]) -> list[set[str]]:
    """One token set per subject variant, filler-stripped. Preserves the
    variant boundary so a multi-word variant like 'client defined field' is
    only satisfied by a folder that contains ALL three tokens."""
    variants: list[set[str]] = []
    for v in values:
        tokens = {t for t in _TOKEN_SPLIT_RE.split(v.lower()) if t} - _FOLDER_FILLER
        if tokens:
            variants.append(tokens)
    return variants


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
        is_configured = subject_values is not None
        if subject_values is None:
            # Combine the camel-split tokens into a single variant so the
            # fallback compares the whole service name against the folder,
            # not each token independently.
            camel = _camel_tokens(spec.service)
            subject_values = [" ".join(camel)] if camel else [spec.service]
        subject_tokens = _lower_set(subject_values)
        subject_variants = _variant_token_sets(subject_values)
        action_tokens = _lower_set(self._action_synonyms.get(spec.action, [spec.action])) if spec.action else set()
        type_tokens = _lower_set(self._type_synonyms.get(spec.type, [spec.type])) if spec.type else set()

        scoped = [
            r for r in requests
            if self._request_in_service_folder(r, subject_variants, strict=not is_configured)
        ]

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

        # No collection-wide fallback: a YAML with no matching Postman folder
        # is reported as missing, with fuzzy suggestions from `_miss` pointing
        # to any look-alike request that lives in another folder.
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
        self,
        req: PostmanRequest,
        subject_variants: list[set[str]],
        strict: bool = False,
    ) -> bool:
        """A folder qualifies as this service's folder iff one of the
        configured subject variants is *fully contained* in the folder's
        meaningful tokens (i.e. every token of that variant appears in the
        folder name). For unconfigured/fallback services, require exact
        equality with a variant to avoid picking a look-alike folder.
        """
        if not subject_variants:
            return False
        for folder in req.folder_path:
            folder_tokens = _normalize(folder) - _FOLDER_FILLER
            for variant in subject_variants:
                if strict:
                    if folder_tokens == variant:
                        return True
                else:
                    if variant.issubset(folder_tokens):
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
