"""Tests for the OpenAPI operation extractor and operation-level expansion."""
from postman_coverage.coverage import _match_with_operation_expansion
from postman_coverage.matcher import Matcher, MatchTier
from postman_coverage.openapi import extract_operations
from postman_coverage.parser import parse_filename
from postman_coverage.postman_client import PostmanRequest


_SWEEP_YAML = """
openapi: 3.0.1
info:
  title: Sweep Service
paths:
  /acctservice/sweep/sweeps/secured:
    post:
      tags: [Get Sweep]
      summary: Get Sweep.
      operationId: getSweepBySecuredPath
  /acctservice/sweep/sweeps/secured/list:
    post:
      tags: [Get Sweep List]
      summary: Get Sweep List.
      operationId: getSweepListBySecuredPath
  /acctservice/sweep/sweeps:
    put:
      tags: [Update Sweep]
      summary: Update Sweep.
      operationId: modSweep
    post:
      tags: [Add Sweep]
      summary: Add Sweep.
      operationId: addSweep
    delete:
      tags: [Delete Sweep]
      summary: Delete Sweep.
      operationId: delSweep
"""


def test_extract_operations_from_sweep_yaml():
    ops = extract_operations(_SWEEP_YAML)
    assert len(ops) == 5
    actions = [op.action for op in ops]
    assert set(actions) == {"Inq", "ListInq", "Mod", "Add", "Del"}
    # tags -> derived action
    by_tag = {op.tag: op.action for op in ops}
    assert by_tag["Get Sweep"] == "Inq"
    assert by_tag["Get Sweep List"] == "ListInq"
    assert by_tag["Update Sweep"] == "Mod"
    assert by_tag["Add Sweep"] == "Add"
    assert by_tag["Delete Sweep"] == "Del"


def test_extract_operations_empty_on_garbage():
    assert extract_operations("") == []
    assert extract_operations("just a scalar") == []
    assert extract_operations("openapi: 3.0.1\n") == []
    # Missing HTTP method entries are skipped.
    assert extract_operations("paths:\n  /x:\n    parameters: []\n") == []


def _matcher() -> Matcher:
    return Matcher(
        service_subject_map={"SweepService": ["sweep"]},
        action_synonyms={
            "Add": ["add", "create"],
            "Inq": ["get", "inquire"],
            "ListInq": ["list"],
            "Mod": ["update", "modify"],
            "Del": ["delete", "remove"],
        },
        type_synonyms={},
    )


def _req(name: str) -> PostmanRequest:
    return PostmanRequest(name=name, folder_path=["Sweep Service"])


def test_operation_expansion_all_covered_yields_covered():
    spec = parse_filename("SweepService-11.0.0_PRM.yaml")
    requests = [
        _req("Get Sweep"),
        _req("Get Sweep List"),
        _req("Update Sweep"),
        _req("Add Sweep"),
        _req("Delete Sweep"),
    ]
    result = _match_with_operation_expansion(
        spec, lambda: _SWEEP_YAML, _matcher(), requests
    )
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert result.is_covered
    actions = {sm.spec.action for sm in result.sub_matches}
    assert actions == {"Inq", "ListInq", "Mod", "Add", "Del"}


def test_operation_expansion_partial_when_some_missing():
    spec = parse_filename("SweepService-11.0.0_PRM.yaml")
    requests = [
        _req("Get Sweep"),
        _req("Update Sweep"),
        # ListInq / Add / Del are all missing
    ]
    result = _match_with_operation_expansion(
        spec, lambda: _SWEEP_YAML, _matcher(), requests
    )
    assert result.tier is MatchTier.PARTIAL
    missing_actions = [
        sm.spec.action for sm in result.sub_matches if not sm.is_covered
    ]
    assert set(missing_actions) == {"ListInq", "Add", "Del"}


def test_operation_expansion_falls_back_when_no_content():
    spec = parse_filename("SweepService-11.0.0_PRM.yaml")
    requests = [_req("Get Sweep")]
    result = _match_with_operation_expansion(
        spec, lambda: None, _matcher(), requests
    )
    # No content -> single-spec match. Base-service spec has action=None so
    # the matcher's relaxed tier fires as long as the folder matches.
    assert result.tier is MatchTier.RELAXED_SCOPED
    assert not result.sub_matches


def test_operation_expansion_all_missing():
    spec = parse_filename("SweepService-11.0.0_PRM.yaml")
    result = _match_with_operation_expansion(
        spec, lambda: _SWEEP_YAML, _matcher(), []
    )
    assert result.tier is MatchTier.NONE
    assert not result.is_covered
