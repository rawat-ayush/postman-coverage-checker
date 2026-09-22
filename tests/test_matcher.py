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


def test_collection_wide_when_folder_wrong():
    spec = parse_filename("AcctService-11.0.0_PRM-Inq_LOAN.yaml")
    requests = [
        _req("Get Account - LOAN", folder=("Uncategorized",)),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.COLLECTION_WIDE


def test_no_match_returns_suggestions():
    spec = parse_filename("AcctService-11.0.0_PRM-Mod_SDA.yaml")
    requests = [
        _req("2.4. Delete Account - SDA"),
        _req("Get Card - CARD"),
    ]
    result = _matcher().match(spec, requests)
    assert result.tier is MatchTier.NONE
    assert result.suggestions, "expected at least one fuzzy suggestion"
