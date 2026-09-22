from postman_coverage.coverage import _match_with_type_expansion, _split_types
from postman_coverage.matcher import Matcher, MatchTier, sub_is_type_covered
from postman_coverage.parser import parse_filename
from postman_coverage.postman_client import PostmanRequest

_SERVICE_MAP = {
    "AcctService": ["account", "acct"],
}
_ACTIONS = {"Add": ["add", "create"], "Inq": ["get", "inquire", "fetch"]}
_TYPES = {"DDA": ["dda"], "SDA": ["sda"], "CDA": ["cda"]}


def _matcher():
    return Matcher(_SERVICE_MAP, _ACTIONS, _TYPES)


def _req(name, folder=("Account Service",)):
    return PostmanRequest(name=name, folder_path=list(folder))


def test_split_types():
    assert _split_types("DDA_SDA_CDA") == ["DDA", "SDA", "CDA"]
    assert _split_types("DDA") == ["DDA"]
    assert _split_types(None) == [None]
    assert _split_types("") == [""]


def test_multi_type_all_present_marks_covered():
    spec = parse_filename("AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml")
    assert spec.type == "DDA_SDA_CDA"
    requests = [
        _req("Add Account - DDA"),
        _req("Add Account - SDA"),
        _req("Add Account - CDA"),
    ]
    result = _match_with_type_expansion(spec, _matcher(), requests)
    assert result.tier is MatchTier.STRICT_SCOPED
    assert result.is_covered
    assert len(result.sub_matches) == 3
    assert {sm.spec.type for sm in result.sub_matches} == {"DDA", "SDA", "CDA"}
    assert all(sub_is_type_covered(sm) for sm in result.sub_matches)


def test_multi_type_combined_single_request_marks_covered():
    """Postman collapses all types into one request name (`_DDA_SDA_CDA`)."""
    spec = parse_filename("AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml")
    requests = [_req("Add Account - DDA_SDA_CDA")]
    result = _match_with_type_expansion(spec, _matcher(), requests)
    assert result.tier is MatchTier.STRICT_SCOPED
    assert result.is_covered
    # All three sub-checks should resolve to the same Postman request.
    matched_names = {sm.matched_request.name for sm in result.sub_matches}
    assert matched_names == {"Add Account - DDA_SDA_CDA"}


def test_multi_type_only_some_present_marks_partial():
    spec = parse_filename("AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml")
    requests = [
        _req("Add Account - DDA"),
        # SDA and CDA are absent
    ]
    result = _match_with_type_expansion(spec, _matcher(), requests)
    assert result.tier is MatchTier.PARTIAL
    assert not result.is_covered
    missing = [sm.spec.type for sm in result.sub_matches if not sub_is_type_covered(sm)]
    assert set(missing) == {"SDA", "CDA"}
    covered = [sm.spec.type for sm in result.sub_matches if sub_is_type_covered(sm)]
    assert covered == ["DDA"]


def test_multi_type_none_present_marks_missing():
    spec = parse_filename("AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml")
    requests = [_req("Add Card - CARD", folder=("Card Service",))]
    result = _match_with_type_expansion(spec, _matcher(), requests)
    assert result.tier is MatchTier.NONE
    assert not result.is_covered
