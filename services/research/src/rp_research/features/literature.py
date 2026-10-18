"""M4 workflows: provider search, identity verification, permitted full-text retrieval and evidence extraction,
model-assisted support assessment and gap proposals."""

from __future__ import annotations

import re
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.hashing import content_hash, sha256_hex
    from rp_contracts.literature import PaperRecord, normalize_doi, rights_for
    from rp_contracts.netpolicy import FetchBlocked
    from rp_contracts.scanning import scan
    from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH

    from ..adapters.base import ProviderError
    from ..adapters.providers import CrossrefAdapter, DataCiteAdapter, OpenAireAdapter, base_adapters
    from ..agents.base import run_agent
    from ..agents.literature import EXTRACTOR, OPPORTUNITY, SUPPORT
    from ..api_client import ApiCallError, ApiClient
    from ..fetch.fetcher import ControlledFetcher, FetchFailed
    from ..fetch.text import extract
    from ..gateway import GatewayError, ModelGateway
    from ..gateway.providers import ProviderError as ModelProviderError
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error, model_unavailable_reason


def adapters():
    return base_adapters()


def fetcher() -> ControlledFetcher:
    return ControlledFetcher()


def _status_for(exc: ProviderError) -> dict:
    return {"status": {"rate_limited": "rate_limited", "access_denied": "access_denied", "payment_required": "payment_required",
                       "not_found": "ok", "unsupported": "unsupported", "disabled": "disabled"}.get(exc.kind, "unavailable"),
            "error": str(exc), "retrieved": 0}


@activity.defn
async def literature_search_run(task_id: str, project_id: str, run_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            run = await api.get(f"/v1/internal/projects/{project_id}/search-runs/{run_id}")
        except ApiCallError as exc:
            raise app_error(exc) from exc
        filters = run["filters"] or {}
        limit = int(filters.get("max_results") or 25)
        ads = adapters()
        statuses: dict[str, dict] = {}
        results = []
        raw = {}
        for name in run["providers"]:
            ad = ads.get(name)
            if ad is None:
                statuses[name] = {"status": "unsupported", "error": "no adapter", "retrieved": 0}
                continue
            try:
                page = await ad.search(run["query"], filters, limit)
                statuses[name] = {"status": "partial" if page.partial else "ok", "total_reported": page.total,
                                  "retrieved": len(page.records), "notes": page.notes}
                raw[name] = [r.model_dump(mode="json") for r in page.records]
                results += [{"provider": name, "rank": i, "record": r.model_dump(mode="json")}
                            for i, r in enumerate(page.records, start=1)]
            except ProviderError as exc:
                if exc.retryable and exc.kind == "unavailable":
                    statuses[name] = _status_for(exc)
                else:
                    statuses[name] = _status_for(exc)
        record = {"query": run["query"], "filters": filters, "providers": statuses, "results": raw,
                  "note": "Normalized provider responses as retrieved; provider attribution applies."}
        try:
            art = await api.publish_json(project_id, "search_run_record", record, sha256_hex(run_id.encode()),
                                         slot="record", label=f"Search run: {run['query'][:120]}")
            res = await api.post(f"/v1/internal/projects/{project_id}/search-runs/{run_id}/results",
                                 {"provider_status": statuses, "results": results, "record_artifact_id": art.artifact_id})
            await api.record_usage(category="scholarly_api", provider="+".join(run["providers"]), units=len(run["providers"]),
                                   unit="requests", stage="literature_search")
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {**res, "provider_status": statuses, "artifact_id": art.artifact_id}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())}


def identity_verdict(claimed: dict, found: PaperRecord | None) -> tuple[str, dict]:
    """Deterministic identity check of a DOI against its authoritative registry record (Crossref or DataCite)."""
    if found is None:
        return "not_found", {"reason": "the DOI is not registered with Crossref or DataCite (possible fabricated or "
                                       "mistyped DOI)"}
    ev = {"record": {"title": found.title, "authors": found.authors[:10], "year": found.year, "venue": found.venue},
          "source": found.provider}
    title = claimed.get("title") or ""
    if not title or title.startswith("[DOI"):
        return "verified", {**ev, "basis": "DOI resolves; metadata taken from the authoritative record"}
    a, b = _tokens(title), _tokens(found.title)
    jacc = len(a & b) / max(len(a | b), 1)
    coverage = len(a & b) / max(len(a), 1)  # shortened titles: claimed terms contained in the registry title
    year_ok = claimed.get("year") is None or found.year is None or abs(int(claimed["year"]) - int(found.year)) <= 1
    ev.update({"title_similarity": round(jacc, 3), "title_coverage": round(coverage, 3), "year_match": year_ok})
    if (jacc >= 0.6 or (coverage >= 0.85 and len(a) >= 3)) and year_ok:
        return "verified", {**ev, "basis": "title and year match the DOI's authoritative record"}
    return "mismatch", {**ev, "basis": "the cited title/year do not match the DOI's record"}


@activity.defn
async def verify_identities(task_id: str, project_id: str, paper_ids: list[str]) -> dict:
    cr = CrossrefAdapter()
    out = {}
    async with ApiClient(task_id) as api:
        for pid in paper_ids:
            p = await api.get(f"/v1/internal/projects/{project_id}/papers/{pid}")
            if not p.get("doi"):
                continue
            try:
                found = await cr.lookup_identifier(p["doi"])
                if found is None:
                    found = await DataCiteAdapter().lookup_identifier(p["doi"])
            except ProviderError as exc:
                await api.post(f"/v1/internal/projects/{project_id}/papers/{pid}/identity",
                               {"status": "unavailable", "evidence": {"error": str(exc)}})
                out[pid] = "unavailable"
                continue
            status, ev = identity_verdict(p, found)
            await api.post(f"/v1/internal/projects/{project_id}/papers/{pid}/identity", {"status": status, "evidence": ev})
            out[pid] = status
    return out


@activity.defn
async def paper_fetch_permitted(task_id: str, project_id: str, paper_id: str) -> dict:
    """Locate full text and retrieve it only where the item licence permits storage (controlled fetch)."""
    async with ApiClient(task_id) as api:
        p = await api.get(f"/v1/internal/projects/{project_id}/papers/{paper_id}")
        if p.get("fulltext_artifact_id"):
            return {"artifact_id": p["fulltext_artifact_id"], "already": True}
        locations = list(p.get("fulltext_locations") or [])
        license_text, oa = p.get("license"), p.get("open_access")
        if p.get("doi"):
            try:
                rec = await OpenAireAdapter().locate_full_text(PaperRecord(provider="openaire", external_id="", doi=p["doi"],
                                                                           title=p["title"]))
                locations += [loc.model_dump() for loc in rec.fulltext if loc.url not in {x["url"] for x in locations}]
                license_text = license_text or rec.license
                oa = oa if oa is not None else rec.open_access
            except ProviderError:
                pass
        rights = rights_for(license_text, oa)
        if not rights.storage_permitted:
            await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/fulltext",
                           {"status": "not_permitted", "detail": rights.basis, "license": license_text,
                            "rights": rights.model_dump()})
            return {"status": "not_permitted", "basis": rights.basis}
        last_error = None
        for loc in locations:
            url = loc["url"]
            try:
                res = await fetcher().fetch(url, accept_types={"application/pdf", "text/html", "application/xml", "text/xml",
                                                               "text/plain"})
            except (FetchBlocked, FetchFailed) as exc:
                last_error = str(exc)
                continue
            report = scan(res.content, res.media_type)
            if report.verdict == "rejected" or report.sniffed_type not in ("application/pdf", "text/html", "text/plain", "application/xml"):
                last_error = f"quarantine rejected {url}"
                continue
            art = await api.publish(project_id, "paper_fulltext", res.content, report.sniffed_type,
                                    sha256_hex(res.content), slot=f"fulltext:{paper_id}",
                                    label=f"Full text: {p['title'][:200]}",
                                    metadata={"url": url, "final_url": res.final_url, "license": license_text,
                                              "scan": report.to_dict()},
                                    classification="internal")
            await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/fulltext",
                           {"status": "retrieved", "fulltext_artifact_id": art.artifact_id, "license": license_text,
                            "rights": rights.model_dump(), "detail": f"retrieved from {res.final_url}"})
            return {"artifact_id": art.artifact_id, "media_type": report.sniffed_type}
        await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/fulltext",
                       {"status": "inaccessible", "detail": last_error or "no full-text location found",
                        "license": license_text, "rights": rights.model_dump()})
        return {"status": "inaccessible"}


@activity.defn
async def evidence_extract(task_id: str, project_id: str, paper_id: str) -> dict:
    async with ApiClient(task_id) as api:
        p = await api.get(f"/v1/internal/projects/{project_id}/papers/{paper_id}")
        rights = p.get("rights") or {}
        text, source_kind, text_art = None, None, None
        if p.get("fulltext_artifact_id"):
            meta = await api.artifact_meta(p["fulltext_artifact_id"])
            data = await api.read_artifact(p["fulltext_artifact_id"])
            try:
                lt = extract(data, meta["media_type"])
            except Exception as exc:  # noqa: BLE001 - unparseable PDF is reported, not fatal
                await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/fulltext",
                               {"status": "inaccessible", "detail": f"could not parse: {exc}"})
                lt = None
            if lt is not None and lt.text.strip():
                text_art = await api.publish_json(project_id, "source_text", lt.to_dict(),
                                                  sha256_hex(f"{paper_id}:{p['fulltext_artifact_id']}".encode()),
                                                  slot=f"text:{paper_id}", depends_on=[p["fulltext_artifact_id"]],
                                                  label="Parsed paper text")
                await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/fulltext",
                               {"status": "parsed", "text_artifact_id": text_art.artifact_id})
                text, source_kind = lt.text, "fulltext"
        if text is None and p.get("abstract") and (p.get("abstract_rights") == "cc_by_openaire_metadata"
                                                   or rights.get("model_use_permitted")):
            text, source_kind = p["abstract"], "abstract"
        if text is None:
            return {"status": "no_permitted_text", "detail": rights.get("basis")}
        if not rights.get("model_use_permitted") and source_kind == "fulltext":
            return {"status": "model_use_not_permitted", "detail": rights.get("basis"),
                    "note": "full text stored for human reading only"}
        try:
            run = await run_agent(EXTRACTOR, ModelGateway(api), {"text": text, "title": p["title"],
                                                                 "input_artifact_ids": [text_art.artifact_id] if text_art else []},
                                  scope=f"{task_id}:{paper_id}")
        except (GatewayError, ModelProviderError) as exc:
            reason = model_unavailable_reason(exc)
            if reason is None:
                raise app_error(exc) from exc
            return {"status": reason, "source_kind": source_kind}
        out = run.output
        ex_art = await api.publish_json(project_id, "evidence_extraction", {**out, "problems": run.problems,
                                                                           "provenance": run.provenance},
                                        content_hash({"paper": paper_id, "text": sha256_hex(text.encode())}),
                                        slot=f"extraction:{paper_id}",
                                        depends_on=[text_art.artifact_id] if text_art else None, label="Evidence extraction")
        res = await api.post(f"/v1/internal/projects/{project_id}/papers/{paper_id}/extraction", {
            "source_artifact_id": text_art.artifact_id if text_art else None, "extraction_artifact_id": ex_art.artifact_id,
            "method": "model_assisted", "extractor": f"{run.provenance['provider']}:{run.provenance['model']}",
            "passages": [{**x, "source_kind": source_kind} for x in out["passages"]], "claims": out["claims"],
            "study": {k: out.get(k) for k in ("methods", "population_or_dataset", "results", "limitations")}})
    return {"status": "extracted", "source_kind": source_kind, **res, "problems": run.problems}


@activity.defn
async def assess_support(task_id: str, project_id: str, claim_id: str, support_ids: list[str]) -> dict:
    async with ApiClient(task_id) as api:
        c = await api.get(f"/v1/internal/claims/{claim_id}")
        passages = {x["id"]: x for x in c["passages"]}
        done = []
        for s in c["supports"]:
            if s["id"] not in support_ids or not s["passage_id"]:
                continue
            ps = passages.get(s["passage_id"])
            paper = await api.get(f"/v1/internal/projects/{project_id}/papers/{ps['paper_id']}")
            if not (paper.get("rights") or {}).get("model_use_permitted") and paper.get("abstract_rights") != "cc_by_openaire_metadata":
                done.append({"support_id": s["id"], "skipped": "licence does not permit sending this passage to a model"})
                continue
            try:
                run = await run_agent(SUPPORT, ModelGateway(api), {"claim": c["proposition"], "quote": ps["quote"],
                                                                   "paper_title": paper["title"]},
                                      scope=f"{task_id}:{s['id']}")
            except (GatewayError, ModelProviderError) as exc:
                reason = model_unavailable_reason(exc)
                if reason is None:
                    raise app_error(exc) from exc
                done.append({"support_id": s["id"], "skipped": reason})
                continue
            await api.post(f"/v1/internal/claims/{claim_id}/support-assessment",
                           {"support_id": s["id"], **run.output, "provenance": run.provenance})
            done.append({"support_id": s["id"], "verdict": run.output["verdict"]})
    return {"assessments": done}


@activity.defn
async def opportunity_generate(task_id: str, project_id: str) -> dict:
    async with ApiClient(task_id) as api:
        inputs = await api.get(f"/v1/internal/projects/{project_id}/opportunity-inputs")
        try:
            run = await run_agent(OPPORTUNITY, ModelGateway(api), inputs, scope=task_id)
        except (GatewayError, ModelProviderError) as exc:
            reason = model_unavailable_reason(exc)
            if reason is None:
                raise app_error(exc) from exc
            return {"status": reason}
        art = await api.publish_json(project_id, "opportunity_set", {**run.output, "problems": run.problems,
                                                                    "provenance": run.provenance},
                                     content_hash(inputs), slot="opportunities", label="Opportunity proposals")
        res = await api.post(f"/v1/internal/projects/{project_id}/opportunities",
                             {"set_artifact_id": art.artifact_id, "proposals": run.output["proposals"],
                              "negative_findings": run.output.get("negative_findings", []), "provenance": run.provenance})
    return {"status": "proposed", **res, "agent_problems": run.problems, "artifact_id": art.artifact_id}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=5),
                    maximum_attempts=4, non_retryable_error_types=["fetch_blocked"])
LONG = timedelta(minutes=20)


@workflow.defn(name="LiteratureSearchWorkflow")
class LiteratureSearchWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            if inp.params.get("mode") == "verify_identity":
                res = await workflow.execute_activity(verify_identities, args=[inp.task_id, inp.project_id,
                                                                               inp.params["paper_ids"]],
                                                      start_to_close_timeout=LONG, retry_policy=RETRY)
                return TaskOutcome(state="succeeded", result={"identity": res})
            res = await workflow.execute_activity(literature_search_run, args=[inp.task_id, inp.project_id,
                                                                               inp.params["search_run_id"]],
                                                  start_to_close_timeout=LONG, retry_policy=RETRY)
            ident = {}
            if res.get("unverified_paper_ids"):
                ident = await workflow.execute_activity(verify_identities, args=[inp.task_id, inp.project_id,
                                                                                 res["unverified_paper_ids"][:200]],
                                                        start_to_close_timeout=LONG, retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[res["artifact_id"]],
                               result={"status": res["status"], "created": res["created"],
                                       "provider_status": res["provider_status"],
                                       "identity": {k: v for k, v in ident.items()}})
        return await run_task(inp, body)


@workflow.defn(name="EvidenceExtractionWorkflow")
class EvidenceExtractionWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            pid = inp.params["paper_id"]
            got = await workflow.execute_activity(paper_fetch_permitted, args=[inp.task_id, inp.project_id, pid],
                                                  task_queue=QUEUE_FETCH, start_to_close_timeout=timedelta(minutes=5),
                                                  retry_policy=RETRY)
            res = await workflow.execute_activity(evidence_extract, args=[inp.task_id, inp.project_id, pid],
                                                  start_to_close_timeout=LONG, retry_policy=RETRY)
            return TaskOutcome(state="succeeded", result={"fulltext": got, "extraction": res})
        return await run_task(inp, body)


@workflow.defn(name="ClaimSupportWorkflow")
class ClaimSupportWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            res = await workflow.execute_activity(assess_support, args=[inp.task_id, inp.project_id, inp.params["claim_id"],
                                                                        inp.params["support_ids"]],
                                                  start_to_close_timeout=LONG, retry_policy=RETRY)
            return TaskOutcome(state="succeeded", result=res)
        return await run_task(inp, body)


@workflow.defn(name="OpportunityWorkflow")
class OpportunityWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            res = await workflow.execute_activity(opportunity_generate, args=[inp.task_id, inp.project_id],
                                                  start_to_close_timeout=LONG, retry_policy=RETRY)
            outs = [res["artifact_id"]] if res.get("artifact_id") else []
            return TaskOutcome(state="succeeded", output_artifact_ids=outs, result=res)
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[LiteratureSearchWorkflow, EvidenceExtractionWorkflow, ClaimSupportWorkflow,
                                    OpportunityWorkflow],
         activities=[literature_search_run, verify_identities, evidence_extract, assess_support, opportunity_generate])
register(QUEUE_FETCH, activities=[paper_fetch_permitted])
_ = normalize_doi
