"""Required product copy (PRODUCT_SPEC §1). Exported to contracts/schemas/copy.json for the web app so both
surfaces render byte-identical text. Changing a string here changes the acknowledgment version."""

from __future__ import annotations

HOME_HEADLINE = "From Call for Papers to Submission-Ready Manuscripts."
HOME_SUBHEAD = "You contribute the original research. We help turn it into a submission-ready manuscript."

RESPONSIBILITY_MESSAGE = (
    "Our platform helps with discovery, evidence review, research planning, manuscript development, and conference "
    "checks. You are responsible for the originality, validity, and integrity of your contribution."
)
RESPONSIBILITY_VERSION = "responsibility-1"

LITERATURE_SETUP_MESSAGE = (
    "You can use the core research workflow without an Elicit or Consensus subscription. We search available "
    "scholarly sources and review full text only when access allows. Some relevant studies may be missed. You can "
    "add papers and check the search coverage before using the review."
)

PROVIDER_CONNECTION_TEMPLATE = (
    "Connecting your own {provider} account may add search or synthesis features. Your provider's access limits and "
    "charges may apply. This connection does not guarantee a complete literature review."
)

COVERAGE_TEMPLATE = (
    "Searched {sources} on {date}. Found {n} records; reviewed {m} full texts; {k} records have metadata or "
    "abstracts only. This review may miss relevant work. Check excluded or inaccessible papers and add important "
    "sources before approving claims."
)

CONTRIBUTION_WORKSPACE_TITLE = "Your Original Research Contribution"
CONTRIBUTION_WORKSPACE_FIELDS = [
    "Question and rationale",
    "Methodological decisions",
    "Data or theoretical work",
    "Result interpretation",
    "Limitations",
]

FINAL_APPROVAL_DECLARATION = (
    "I have critically reviewed the scientific content, verified key findings and references, considered the "
    "documented literature coverage and access limits, made a substantive intellectual contribution, checked "
    "applicable venue policies and disclosures, and accept responsibility for this submission."
)

SUBMISSION_READY_DEFINITION = (
    "“Submission-ready” means the package passes the checks the platform can perform and has completed human gates. "
    "It is neither a guarantee of scientific validity, policy compliance, acceptance, nor eligibility for authorship."
)


def all_copy() -> dict[str, object]:
    return {
        "home_headline": HOME_HEADLINE,
        "home_subhead": HOME_SUBHEAD,
        "responsibility_message": RESPONSIBILITY_MESSAGE,
        "responsibility_version": RESPONSIBILITY_VERSION,
        "literature_setup_message": LITERATURE_SETUP_MESSAGE,
        "provider_connection_template": PROVIDER_CONNECTION_TEMPLATE,
        "coverage_template": COVERAGE_TEMPLATE,
        "contribution_workspace_title": CONTRIBUTION_WORKSPACE_TITLE,
        "contribution_workspace_fields": CONTRIBUTION_WORKSPACE_FIELDS,
        "final_approval_declaration": FINAL_APPROVAL_DECLARATION,
        "submission_ready_definition": SUBMISSION_READY_DEFINITION,
    }
