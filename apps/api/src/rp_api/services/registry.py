"""Provider rights registry seeds (global reference data, written only by the ingestion role).

Gate statuses:
  cleared           production use reviewed and recorded by the product owner
  development_only  usable in local/staging with recorded documentation; production review outstanding
  pending           not usable until access/terms are verified
  blocked           must not be enabled (explicit legal/contractual blocker)

Seeds never overwrite a row whose gate was changed by an administrator (only missing rows are inserted and
capability metadata refreshed).
"""

from __future__ import annotations

from sqlalchemy import select

from ..db.engine import session_scope
from ..db.models.core import ProviderDefinition

REVIEW_DATE_NOTE = "Documentation reviewed 2026-10-18 during implementation; production terms review outstanding."

SEEDS: list[dict] = [
    {
        "key": "openaire", "display_name": "OpenAIRE Graph", "kind": "scholarly", "enabled": True,
        "gate_status": "development_only",
        "docs_url": "https://graph.openaire.eu/docs/apis/graph-api/",
        "terms_url": "https://graph.openaire.eu/docs/10.1.0/apis/terms/",
        "attribution": "Metadata from the OpenAIRE Graph, licensed CC-BY 4.0 (attribution required on display).",
        "allowed_uses": "Broad discovery and open-access links. " + REVIEW_DATE_NOTE,
        "caching_allowed": True,
        "fulltext_rights": "Linked full text carries item-level licenses; check each item before storage or model use.",
        "rate_limit": "Unauthenticated requests are rate limited; register a token for higher limits [VERIFY].",
        "capabilities": {
            "search": {"supported": True}, "lookup_identifier": {"supported": True},
            "retrieve_metadata": {"supported": True}, "locate_full_text": {"supported": True},
            "retrieve_permitted_full_text": {"supported": False, "note": "links only; retrieval goes through controlled fetch"},
            "report_quota": {"supported": False},
        },
    },
    {
        "key": "crossref", "display_name": "Crossref", "kind": "scholarly", "enabled": True,
        "gate_status": "development_only",
        "docs_url": "https://www.crossref.org/documentation/retrieve-metadata/rest-api",
        "terms_url": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
        "attribution": "Bibliographic metadata from Crossref.",
        "allowed_uses": "DOI and bibliographic cross-checks via the polite pool (mailto). Abstracts may carry "
                        "publisher copyright distinct from metadata. " + REVIEW_DATE_NOTE,
        "caching_allowed": True,
        "fulltext_rights": "Crossref metadata is not full text.",
        "rate_limit": "Polite pool with mailto; respect X-Rate-Limit headers.",
        "capabilities": {
            "search": {"supported": True}, "lookup_identifier": {"supported": True},
            "retrieve_metadata": {"supported": True}, "locate_full_text": {"supported": True, "note": "license/link metadata only"},
            "retrieve_permitted_full_text": {"supported": False}, "report_quota": {"supported": False},
        },
    },
    {
        "key": "datacite", "display_name": "DataCite", "kind": "scholarly", "enabled": True,
        "gate_status": "development_only", "docs_url": "https://support.datacite.org/docs/api",
        "terms_url": "https://datacite.org/terms-of-use/",
        "attribution": "DOI metadata from DataCite (CC0).",
        "allowed_uses": "Identity verification of non-Crossref DOIs (Zenodo, figshare, arXiv). " + REVIEW_DATE_NOTE,
        "caching_allowed": True, "fulltext_rights": "DataCite metadata is not full text.",
        "capabilities": {"lookup_identifier": {"supported": True}, "retrieve_metadata": {"supported": True},
                         "search": {"supported": False}},
    },
    {
        "key": "core", "display_name": "CORE", "kind": "scholarly", "enabled": False, "gate_status": "pending",
        "docs_url": "https://core.ac.uk/services/api", "terms_url": "https://core.ac.uk/faq",
        "gate_notes": "Adapter implemented against the published v3 OpenAPI spec (api.core.ac.uk/swagger/v3.json, "
                      "checked 2026-10-18) with a spec-derived contract test. Before enabling: an API key, confirmation "
                      "of free-license eligibility for this product, item-level full-text rights, and a check that live "
                      "response field names match the spec (PRODUCT_SPEC §2.5).",
        "requires_user_connection": False,
        "capabilities": {
            "search": {"supported": True}, "lookup_identifier": {"supported": True},
            "retrieve_metadata": {"supported": True}, "locate_full_text": {"supported": True},
            "retrieve_permitted_full_text": {"supported": True}, "report_quota": {"supported": False},
        },
    },
    {
        "key": "elicit", "display_name": "Elicit", "kind": "scholarly", "enabled": False, "gate_status": "blocked",
        "docs_url": "https://docs.elicit.com/", "terms_url": "https://elicit.com/operations/api-terms",
        "gate_notes": "Launch blocker: Elicit API terms restrict building competing research products. Do not expose "
                      "the connection until Elicit confirms in writing that this integration and output storage are "
                      "permitted (PRODUCT_SPEC §2.5).",
        "requires_user_connection": True,
        "capabilities": {"search": {"supported": True}, "report_quota": {"supported": True}},
    },
    {
        "key": "consensus", "display_name": "Consensus", "kind": "scholarly", "enabled": False, "gate_status": "pending",
        "docs_url": "https://docs.consensus.app/",
        "terms_url": "https://help.consensus.app/en/articles/16516328-the-consensus-api",
        "gate_notes": "Requires verification of plan eligibility, credential model, reuse/display and retention terms. "
                      "Only the consensus.app scholarly API is in scope. The published docs index (docs.consensus.app/"
                      "llms.txt, checked 2026-10-18) names GET /v1/search as the supported endpoint (quick_search is "
                      "deprecated, removal 2027-02-07), but the API reference is behind a bot challenge, so request and "
                      "response fields are not verified; no response parser is shipped until a researcher with an "
                      "eligible account verifies them.",
        "requires_user_connection": True,
        "capabilities": {"search": {"supported": True}, "report_quota": {"supported": True}},
    },
    {
        "key": "anthropic", "display_name": "Anthropic Claude", "kind": "model", "enabled": False,
        "gate_status": "pending",
        "docs_url": "https://docs.anthropic.com/", "terms_url": "https://www.anthropic.com/legal/commercial-terms",
        "gate_notes": "Enable after an API key is provisioned in the secrets manager and the deployment records the "
                      "provider's retention/training settings. Restricted data is never sent.",
        "allowed_classifications": ["public", "internal"],
        "retention": "[VERIFY] account-level data retention settings before enabling.",
        "capabilities": {"generate": {"supported": True}, "review": {"supported": True}},
    },
    {
        "key": "claude_cli", "display_name": "Claude via local CLI login (personal, local only)", "kind": "model",
        "enabled": True, "gate_status": "development_only",
        "docs_url": "https://code.claude.com/docs/en/agent-sdk/overview",
        "terms_url": "https://www.anthropic.com/legal/consumer-terms",
        "gate_notes": "Runs the operator's installed Claude CLI with their own login, only when the API and worker run "
                      "with environment=local on that operator's machine. Anthropic's Agent SDK docs (checked "
                      "2026-10-18): unless previously approved, third-party developers may not offer claude.ai login or "
                      "rate limits in their products - deployments must use an API key (provider 'anthropic'). Usage "
                      "counts against the operator's plan; whether a given use fits that plan's terms is the operator's "
                      "decision. Restricted data is never sent.",
        "allowed_classifications": ["public", "internal"],
        "retention": "Governed by the operator's own Claude plan settings.",
        "capabilities": {"generate": {"supported": True}, "review": {"supported": True}},
    },
    {
        "key": "fixture", "display_name": "Fixture model (tests and demos only)", "kind": "model", "enabled": True,
        "gate_status": "development_only",
        "gate_notes": "Deterministic recorded responses for automated tests and local demos. Never used in production; "
                      "outputs are labelled as fixture outputs.",
        "allowed_classifications": ["public", "internal", "restricted"],
        "capabilities": {"generate": {"supported": True}, "review": {"supported": True}},
    },
]


async def ensure_registry() -> None:
    try:
        async with session_scope("ingest") as db:
            existing = {p.key: p for p in (await db.execute(select(ProviderDefinition))).scalars()}
            for seed in SEEDS:
                row = existing.get(seed["key"])
                if row is None:
                    db.add(ProviderDefinition(**seed))
                else:
                    row.capabilities = seed.get("capabilities", row.capabilities)
                    row.docs_url = seed.get("docs_url", row.docs_url)
                    row.terms_url = seed.get("terms_url", row.terms_url)
                    row.gate_notes = seed.get("gate_notes", row.gate_notes)  # documentation; gate decisions stay with operators
            from rp_contracts.verification import POLICY_V1

            from ..db.models.literature import VerificationPolicyRecord

            if (await db.execute(select(VerificationPolicyRecord))).first() is None:
                db.add(VerificationPolicyRecord(version=POLICY_V1.version, rules=POLICY_V1.model_dump(), active=True,
                                                published_by="platform-seed"))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("rp_api").warning("provider registry seed skipped: %s", exc)
