from postman_coverage.matcher import Matcher, MatchTier
from postman_coverage.parser import parse_filename
from postman_coverage.postman_client import PostmanRequest

_SERVICE_MAP = {
    "AcctService": ["account", "acct"],
    "ParticipationService": ["participation"],
}
_ACTIONS = {
    "Add": ["add", "create"],
    "Inq": ["get", "inquire", "inquiry", "fetch"],
    "Mod": ["update", "modify", "edit"],
    "Del": ["delete", "remove"],
}
_TYPES = {"DDA": ["dda"], "LOAN": ["loan"], "SDA": ["sda"], "CDA": ["cda"]}


def _matcher():
    return Matcher(_SERVICE_MAP, _ACTIONS, _TYPES)


def _req(name, folder=("Account Service",)):
    return PostmanRequest(name=name, folder_path=list(folder))


def test_strict_scoped_match_add_dda():
    spec = parse_filename("AcctService-11.0.0_PRM-Add_DDA.yaml")
    requests = [
        _req("1.1. Add Account - DDA"),
        _req("1.2. Get Account - DDA"),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.STRICT_SCOPED
    assert result.matched_request.name == "1.1. Add Account - DDA"


def test_relaxed_when_type_missing_on_postman_side():
    spec = parse_filename("ParticipationService-11.0.0_PRM-Mod_LOAN.yaml")
    requests = [
        _req("Update Participation Risk", folder=("Participation Service",)),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.RELAXED_SCOPED


def test_no_collection_wide_fallback_when_folder_wrong():
    """A request filed in the wrong folder is no longer credited as
    collection-wide; the YAML is reported as missing."""
    spec = parse_filename("AcctService-11.0.0_PRM-Inq_LOAN.yaml")
    requests = [
        _req("Get Account - LOAN", folder=("Uncategorized",)),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.NONE
    assert result.matched_request is None


def test_no_match_returns_suggestions():
    spec = parse_filename("AcctService-11.0.0_PRM-Mod_SDA.yaml")
    requests = [
        _req("2.4. Delete Account - SDA"),
        _req("Get Card - CARD"),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.NONE
    assert result.suggestions, "expected at least one fuzzy suggestion"


# --- Regression tests -------------------------------------------------------


def test_camelcase_request_name_matches_multi_word_subject():
    """A Postman request name like 'Update SafeDepositBoxService' must be
    tokenised via CamelCase splitting so its subject tokens (safe/deposit/
    box) can be matched against the configured multi-word subject values.
    Regression for the PRM SafeDepositBoxService `Mod` false-negative.
    """
    service_map = {"SafeDepositBoxService": ["safe deposit box", "sdb"]}
    actions = {"Mod": ["update", "modify", "edit"]}
    matcher = Matcher(service_map, actions, {})
    spec = parse_filename("SafeDepositBoxService-11.0.0_PRM-Mod.yaml")
    requests = [
        PostmanRequest(
            name="Update SafeDepositBoxService",
            folder_path=["Safe Deposit Box Service"],
        ),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert result.matched_request is not None
    assert result.matched_request.name == "Update SafeDepositBoxService"


def test_unknown_service_does_not_match_similar_folder():
    """An unconfigured service must not be credited to a look-alike folder
    that just happens to share a token. Regression for the DNA
    ClientFieldService YAML being falsely matched against the
    'Client Field Specifications Service' Postman folder.
    """
    matcher = Matcher(
        service_subject_map={},  # ClientFieldService is intentionally absent
        action_synonyms={"Inq": ["get", "inquire"], "Mod": ["update", "modify"]},
        type_synonyms={},
    )
    spec = parse_filename("ClientFieldService-11.0.0_DNA-Inq.yaml")
    requests = [
        PostmanRequest(
            name="Get Client Field Specification",
            folder_path=["Client Field Specifications Service"],
        ),
        PostmanRequest(
            name="Get Client Defined Field",
            folder_path=["Client Defined Field Service"],
        ),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.NONE
    assert result.matched_request is None


def test_unknown_service_still_matches_exact_folder():
    """The strict fallback must not regress exact-name matches: an
    unconfigured `FooBarService` should still bind to a `Foo Bar Service`
    folder.
    """
    matcher = Matcher(
        service_subject_map={},
        action_synonyms={"Inq": ["get"]},
        type_synonyms={},
    )
    spec = parse_filename("FooBarService-11.0.0_PRM-Inq.yaml")
    requests = [
        PostmanRequest(name="Get Foo Bar", folder_path=["Foo Bar Service"]),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert result.matched_request is not None


def test_configured_multi_word_subject_does_not_leak_across_services():
    """A configured multi-word subject like `[client defined field]` must
    only bind to a folder that contains *all three* tokens. Regression for
    the DNA `ClientDefinedFieldService` YAML being falsely credited to the
    `Client Field Specifications Service` folder because it shared 'client'
    and 'field'.
    """
    matcher = Matcher(
        service_subject_map={"ClientDefinedFieldService": ["client defined field"]},
        action_synonyms={"Inq": ["get"], "Mod": ["update"]},
        type_synonyms={},
    )
    spec = parse_filename("ClientDefinedFieldService-11.0.0_DNA-Inq.yaml")
    requests = [
        PostmanRequest(
            name="Get Client Field Specification",
            folder_path=["Party Account Service", "Client Field Specifications Service"],
        ),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.NONE
    assert result.matched_request is None


def test_configured_multi_word_subject_matches_exact_folder():
    """When the exact folder DOES exist, the multi-word subject binds to it."""
    matcher = Matcher(
        service_subject_map={"ClientDefinedFieldService": ["client defined field"]},
        action_synonyms={"Inq": ["get"], "Mod": ["update"]},
        type_synonyms={},
    )
    spec = parse_filename("ClientDefinedFieldService-11.0.0_PRM-Inq.yaml")
    requests = [
        PostmanRequest(
            name="Get Client Defined Field",
            folder_path=["Client Defined Field Service"],
        ),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert result.matched_request is not None


def test_configured_subject_allows_longer_folder_name():
    """Superset (not equality) so a service configured as `[account document]`
    still binds to a longer, more descriptive folder like
    `Account Document Type Relationship Service`.
    """
    matcher = Matcher(
        service_subject_map={"AcctDocTypeRelService": ["account document", "document type"]},
        action_synonyms={"Inq": ["get"]},
        type_synonyms={},
    )
    spec = parse_filename("AcctDocTypeRelService-11.0.0_PRM-Inq.yaml")
    requests = [
        PostmanRequest(
            name="Get Account Document",
            folder_path=["Account Document Type Relationship Service"],
        ),
    ]
    result = matcher.match(spec, requests)
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert result.matched_request is not None
