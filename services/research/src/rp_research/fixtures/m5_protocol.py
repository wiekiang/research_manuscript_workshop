"""Fixture protocol used by the M5 workflow tests and its recorded methodology review (synthetic, test only)."""

SECTIONS = {
    "research_questions": "RQ1: Does recording library versions restore outputs of R data pipelines after dependency updates?",
    "hypotheses": "H1: at least half of affected pipelines are restored when recorded versions are reinstalled.",
    "operational_definitions": "Restored = byte-identical primary output after reinstalling recorded versions.",
    "sample_or_data_selection": "Eight public R pipelines from a curated list (selection criteria documented).",
    "inclusion_exclusion": "Include pipelines with public inputs; exclude pipelines needing credentials.",
    "baselines": "Re-execution without version records.",
    "metrics": "Accuracy of the restoration classifier against manual verification (proportion).",
    "analysis_plan": "Compute the proportion restored with a Wilson interval.",
    "statistical_tests": "Exact binomial test against 0.5.",
    "power_or_uncertainty": "Small sample; report intervals, not significance claims beyond the test.",
    "leakage_controls": "Manual verification labels produced before running the classifier.",
    "limitations": "Small, non-random sample of public pipelines.",
    "compute_estimate": "Under one CPU-day.",
    "reproducibility_plan": "Scripts, environment lockfile and raw outputs archived with hashes.",
}
ETHICS = {"involves_human_participants": False, "personal_data": False, "sensitive_data": False,
          "restricted_datasets": False, "data_licences": ["MIT/GPL source code"],
          "institutional_approval": {"required": False, "status": "not_applicable"},
          "declaration_text_accepted": True}
COMPUTE = "under one CPU-day"
COST_CENTS = 0
