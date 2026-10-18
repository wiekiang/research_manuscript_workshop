"""Supplied-result assurance levels describe available checking only (PRODUCT_SPEC §2.9, acceptance #26)."""

from rp_contracts.contribution import (
    EthicsRightsDeclaration,
    InstitutionalApproval,
    ResultManifest,
    assess,
    ethics_blockers,
)
from rp_contracts.enums import AssuranceLevel

H = "a" * 64


def manifest(**kw):
    base = dict(title="Accuracy on held-out set", protocol_version=1, protocol_hash=H, data_origin="public benchmark",
                data_rights="CC-BY 4.0", methods="logistic regression", limitations="single dataset",
                metrics=[{"name": "accuracy", "value": 0.75, "unit": "proportion", "n": 8, "numerator": 6, "denominator": 8}],
                attestation_accepted=True)
    base.update(kw)
    return ResultManifest.model_validate(base)


PRED = b"y_true,y_pred\n1,1\n0,0\n1,1\n0,1\n1,1\n0,0\n1,0\n0,0\n"  # 6/8 correct


def test_aggregate_only_is_at_most_internally_consistent():
    r = assess(manifest(), predictions=None, protocol_frozen_hash=H)
    assert r.level == AssuranceLevel.INTERNALLY_CONSISTENT
    assert "raw predictions/outputs" in r.missing and any("recomputation impossible" in x for x in r.impossible_checks)
    assert "not independently" in r.wording_limits[0]


def test_lone_aggregate_without_raw_data_is_declared():
    m = manifest(metrics=[{"name": "accuracy", "value": 0.91, "unit": "proportion"}], files=[])
    r = assess(m, predictions=None, protocol_frozen_hash=H)
    assert r.level == AssuranceLevel.DECLARED
    assert r.level not in (AssuranceLevel.INDEPENDENTLY_CHECKED, AssuranceLevel.REPRODUCED)
    assert any("cannot be checked" in x for x in r.impossible_checks)


def test_aggregate_without_units_or_checks_is_declared():
    m = manifest(metrics=[{"name": "speedup", "value": 3.2, "unit": None}])
    assert assess(m, predictions=None, protocol_frozen_hash=H).level == AssuranceLevel.DECLARED


def test_recomputation_promotes_and_mismatch_demotes():
    ok = assess(manifest(), predictions=PRED, protocol_frozen_hash=H)
    assert ok.level == AssuranceLevel.INDEPENDENTLY_CHECKED and not ok.blockers
    bad = assess(manifest(metrics=[{"name": "accuracy", "value": 0.875, "unit": "proportion", "n": 8}]), predictions=PRED,
                 protocol_frozen_hash=H)
    assert bad.level == AssuranceLevel.DECLARED and any("failed" in b for b in bad.blockers)


def test_documented_rerun_reaches_reproduced():
    m = manifest(rerun_record={"values": {"accuracy": 0.75}, "tolerance": 0.001})
    assert assess(m, predictions=PRED, protocol_frozen_hash=H).level == AssuranceLevel.REPRODUCED


def test_unapproved_protocol_revision_blocks():
    r = assess(manifest(protocol_hash="b" * 64), predictions=PRED, protocol_frozen_hash=H)
    assert any("not the frozen" in b for b in r.blockers)
    assert any("no frozen" in b for b in assess(manifest(), predictions=None, protocol_frozen_hash=None).blockers)


def test_synthetic_and_exploratory_wording():
    r = assess(manifest(synthetic_or_simulated=True, run_type="exploratory"), predictions=None, protocol_frozen_hash=H)
    assert any("synthetic" in w for w in r.wording_limits) and any("Exploratory" in w for w in r.wording_limits)


def test_ethics_blockers():
    d = EthicsRightsDeclaration(involves_human_participants=True, personal_data=True, sensitive_data=False,
                                restricted_datasets=False, institutional_approval=InstitutionalApproval(required=True, status="pending"),
                                declaration_text_accepted=True)
    b = ethics_blockers(d)
    assert any("cannot grant" in x for x in b) and any("de-identification" in x for x in b)
    ok = d.model_copy(update={"institutional_approval": InstitutionalApproval(required=True, status="obtained", reference="IRB-42"),
                              "deidentification_plan": "pseudonymised IDs, keys held separately"})
    assert ethics_blockers(ok) == []
