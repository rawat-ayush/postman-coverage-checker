from postman_coverage.parser import parse_filename


def test_parses_add_dda():
    spec = parse_filename("AcctService-11.0.0_PRM-Add_DDA.yaml")
    assert spec is not None
    assert spec.service == "AcctService"
    assert spec.version == "11.0.0"
    assert spec.core == "PRM"
    assert spec.action == "Add"
    assert spec.type == "DDA"


def test_parses_participation_mod_loan():
    spec = parse_filename("ParticipationService-11.0.0_PRM-Mod_LOAN.yaml")
    assert spec is not None
    assert spec.service == "ParticipationService"
    assert spec.action == "Mod"
    assert spec.type == "LOAN"


def test_parses_without_type_suffix():
    spec = parse_filename("AcctService-11.0.0_PRM-Inq.yaml")
    assert spec is not None
    assert spec.type is None


def test_rejects_garbage():
    assert parse_filename("random_file.yaml") is None
    assert parse_filename("README.md") is None


# --- Non-standard filenames that used to be flagged unparseable --------------


def test_service_name_without_service_suffix():
    spec = parse_filename("TellerSignOn-11.0.0_SIG.yaml")
    assert spec is not None
    assert spec.service == "TellerSignOn"
    assert spec.version == "11.0.0"
    assert spec.core == "SIG"
    assert spec.action is None


def test_service_name_without_service_suffix_with_action_type():
    spec = parse_filename("TellerSignOn-11.0.0_CT-Add_TellerSessKeyRefresh.yaml")
    assert spec is not None
    assert spec.service == "TellerSignOn"
    assert spec.core == "CT"
    assert spec.action == "Add"
    assert spec.type == "TellerSessKeyRefresh"


def test_hyphenated_camelcase_service():
    spec = parse_filename("Reinvestment-Service-11.0.0_SIG.yaml")
    assert spec is not None
    assert spec.service == "Reinvestment-Service"
    assert spec.version == "11.0.0"
    assert spec.core == "SIG"


def test_mixed_hyphen_underscore_service():
    spec = parse_filename("ach-external_transfer_service-11.0.0_SIG.yaml")
    assert spec is not None
    assert spec.service == "ach-external_transfer_service"
    assert spec.core == "SIG"


def test_gl_style_uppercase_prefix_service():
    spec = parse_filename("GL-account_service-11.0.0_DNA.yaml")
    assert spec is not None
    assert spec.service == "GL-account_service"
    assert spec.core == "DNA"


def test_service_without_version():
    spec = parse_filename("HostLogon_DNA.yaml")
    assert spec is not None
    assert spec.service == "HostLogon"
    assert spec.version is None
    assert spec.core == "DNA"
    assert spec.action is None


def test_lowercase_hyphenated_service_still_parses():
    spec = parse_filename("region-service-11.0.0_PRM.yaml")
    assert spec is not None
    assert spec.service == "region-service"
    assert spec.core == "PRM"


def test_underscore_separator_before_action():
    spec = parse_filename("XferService-11.0.0_DNA_ListInq.yaml")
    assert spec is not None
    assert spec.service == "XferService"
    assert spec.core == "DNA"
    assert spec.action == "ListInq"
    assert spec.type is None


def test_multi_type_preserved_in_type_field():
    spec = parse_filename("AcctService-11.0.0_DNA-Add_DDA_SDA_CDA.yaml")
    assert spec is not None
    assert spec.action == "Add"
    assert spec.type == "DDA_SDA_CDA"
