"""Crossref and OpenAIRE Graph adapters (base no-fee stack) plus gated CORE / Elicit / Consensus adapters."""

from __future__ import annotations

import re
from html import unescape

from rp_contracts.literature import Capability, FullTextLocation, PaperRecord, normalize_doi

from ..config import get_worker_settings
from .base import Adapter, Disabled, ProviderError, SearchPage


def _strip_jats(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(t)).strip() or None


class CrossrefAdapter(Adapter):
    name = "crossref"
    capabilities = {Capability.SEARCH: True, Capability.LOOKUP_IDENTIFIER: True, Capability.RETRIEVE_METADATA: True,
                    Capability.LOCATE_FULL_TEXT: True, Capability.RETRIEVE_PERMITTED_FULL_TEXT: False,
                    Capability.REPORT_QUOTA: False}

    def __init__(self) -> None:
        s = get_worker_settings()
        self.base = s.crossref_base_url
        self.mailto = s.crossref_mailto

    def _record(self, it: dict) -> PaperRecord:
        lic = it.get("license") or []
        lic_url = lic[0].get("URL") if lic else None
        links = [FullTextLocation(url=lk["URL"], license=lic_url, access="unknown", content_type=lk.get("content-type"),
                                  source="crossref") for lk in (it.get("link") or [])
                 if lk.get("intended-application") in ("text-mining", "unspecified") and lk.get("URL")]
        issued = (it.get("issued") or {}).get("date-parts") or [[None]]
        authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
                   for a in (it.get("author") or [])]
        return PaperRecord(
            provider=self.name, external_id=it.get("DOI", ""), doi=normalize_doi(it.get("DOI")),
            title=((it.get("title") or [""])[0] or "").strip(), authors=[a for a in authors if a],
            year=issued[0][0] if issued and issued[0] else None,
            venue=((it.get("container-title") or [None])[0]), publisher=it.get("publisher"), type=it.get("type"),
            abstract=_strip_jats(it.get("abstract")), abstract_rights="publisher_copyright", license=lic_url,
            open_access=None, fulltext=links, metadata_license="CC0 (Crossref metadata)",
            attribution="Metadata from Crossref")

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        params = {"query": query, "rows": min(limit, 100), "mailto": self.mailto,
                  "select": "DOI,title,author,issued,container-title,publisher,type,abstract,license,link"}
        f = []
        if filters.get("year_from"):
            f.append(f"from-pub-date:{filters['year_from']}")
        if filters.get("year_to"):
            f.append(f"until-pub-date:{filters['year_to']}")
        if f:
            params["filter"] = ",".join(f)
        if cursor:
            params["cursor"] = cursor
        r = await self._get(f"{self.base}/works", params=params)
        try:
            msg = r.json()["message"]
        except (ValueError, KeyError) as exc:
            raise ProviderError(self.name, "bad_response", "unexpected response shape") from exc
        recs = [self._record(i) for i in msg.get("items", []) if (i.get("title") or [""])[0]]
        return SearchPage(recs, msg.get("total-results"), msg.get("next-cursor"),
                          partial=len(recs) < len(msg.get("items", [])), raw={"items": len(msg.get("items", []))})

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        d = normalize_doi(doi)
        if not d:
            return None
        try:
            r = await self._get(f"{self.base}/works/{d}", params={"mailto": self.mailto})
        except ProviderError as exc:
            if exc.kind == "not_found":
                return None
            raise
        return self._record(r.json()["message"])

    async def locate_full_text(self, record: PaperRecord) -> PaperRecord:
        return record  # links come with the metadata; Crossref never supplies full text itself


class OpenAireAdapter(Adapter):
    name = "openaire"
    capabilities = {Capability.SEARCH: True, Capability.LOOKUP_IDENTIFIER: True, Capability.RETRIEVE_METADATA: True,
                    Capability.LOCATE_FULL_TEXT: True, Capability.RETRIEVE_PERMITTED_FULL_TEXT: False,
                    Capability.REPORT_QUOTA: False}

    def __init__(self) -> None:
        self.base = get_worker_settings().openaire_base_url.rstrip("/")

    def _record(self, r: dict) -> PaperRecord:
        doi = next((p["value"] for p in (r.get("pids") or []) if p.get("scheme") == "doi"), None)
        locs = []
        for inst in r.get("instances") or []:
            access = ((inst.get("accessRight") or {}).get("label") or "").lower() or None
            lic = inst.get("license")
            for u in inst.get("urls") or []:
                locs.append(FullTextLocation(url=u, license=lic, access="open" if access and "open" in access else access,
                                             content_type=inst.get("type"), source="openaire"))
        best = ((r.get("bestAccessRight") or {}).get("label") or "").lower()
        year = None
        if r.get("publicationDate"):
            m = re.match(r"(\d{4})", r["publicationDate"])
            year = int(m.group(1)) if m else None
        desc = (r.get("descriptions") or [None])[0]
        return PaperRecord(
            provider=self.name, external_id=r.get("id", ""), doi=normalize_doi(doi), title=(r.get("mainTitle") or "").strip(),
            authors=[a.get("fullName") for a in (r.get("authors") or []) if a.get("fullName")], year=year,
            venue=(r.get("container") or {}).get("name"), publisher=r.get("publisher"), type=r.get("type"),
            abstract=_strip_jats(desc), abstract_rights="cc_by_openaire_metadata", license=next(
                (loc.license for loc in locs if loc.license), None),
            open_access=("open" in best) if best else (r.get("openAccessColor") is not None or None), fulltext=locs,
            metadata_license="CC-BY-4.0 (OpenAIRE Graph)", attribution="Metadata from the OpenAIRE Graph (CC-BY 4.0)")

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        params = {"search": query, "type": "publication", "pageSize": min(limit, 100), "page": int(cursor or 1)}
        if filters.get("year_from"):
            params["fromPublicationDate"] = f"{filters['year_from']}-01-01"
        if filters.get("year_to"):
            params["toPublicationDate"] = f"{filters['year_to']}-12-31"
        r = await self._get(f"{self.base}/v1/researchProducts", params=params)
        try:
            d = r.json()
            hdr = d["header"]
        except (ValueError, KeyError) as exc:
            raise ProviderError(self.name, "bad_response", "unexpected response shape") from exc
        recs = [self._record(x) for x in d.get("results") or [] if x.get("mainTitle")]
        total = hdr.get("numFound")
        nxt = str(hdr.get("page", 1) + 1) if total and hdr.get("page", 1) * hdr.get("pageSize", limit) < total else None
        return SearchPage(recs, total, nxt, raw={"page": hdr.get("page")})

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        d = normalize_doi(doi)
        if not d:
            return None
        r = await self._get(f"{self.base}/v1/researchProducts", params={"pid": d, "pageSize": 5})
        res = r.json().get("results") or []
        return self._record(res[0]) if res else None

    async def locate_full_text(self, record: PaperRecord) -> PaperRecord:
        if record.doi:
            found = await self.lookup_identifier(record.doi)
            if found:
                record.fulltext = record.fulltext + [f for f in found.fulltext if f.url not in {x.url for x in record.fulltext}]
                record.license = record.license or found.license
                record.open_access = record.open_access if record.open_access is not None else found.open_access
        return record


class DataCiteAdapter(Adapter):
    """DataCite DOI registry (Zenodo, figshare, arXiv and other non-Crossref DOIs): identity lookup only."""

    name = "datacite"
    capabilities = {Capability.LOOKUP_IDENTIFIER: True, Capability.RETRIEVE_METADATA: True}

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        d = normalize_doi(doi)
        if not d:
            return None
        try:
            r = await self._get(f"https://api.datacite.org/dois/{d}")
        except ProviderError as exc:
            if exc.kind == "not_found":
                return None
            raise
        a = r.json()["data"]["attributes"]
        rights = a.get("rightsList") or []
        return PaperRecord(provider=self.name, external_id=d, doi=d, title=((a.get("titles") or [{}])[0].get("title") or ""),
                           authors=[c.get("name") for c in a.get("creators") or [] if c.get("name")],
                           year=a.get("publicationYear"), venue=a.get("publisher"), publisher=a.get("publisher"),
                           type=(a.get("types") or {}).get("resourceTypeGeneral"),
                           license=rights[0].get("rightsUri") if rights else None, open_access=None,
                           fulltext=[FullTextLocation(url=a["url"], license=rights[0].get("rightsUri") if rights else None,
                                                      access="unknown", source="datacite")] if a.get("url") else [],
                           metadata_license="CC0 (DataCite metadata)", attribution="Metadata from DataCite")


class CoreAdapter(Adapter):
    """CORE API v3 (https://api.core.ac.uk/swagger/v3.json, retrieved 2026-10-18): ``GET /v3/search/works/`` with
    ``q``/``limit``/``offset`` and ``Authorization: Bearer <key>``; ``SearchResponse{total_hits, results}`` of ``Work``
    (``title``, ``authors`` [string], ``year_published``, ``doi``, ``download_url``, ``abstract``, ``links``).

    Disabled until the project's free-license eligibility, item-level content rights and the field naming of live
    responses are verified with a real key (gate ``pending``, §2.5). The parser also accepts the camelCase variant
    some clients report, so a naming difference fails visibly in contract tests rather than silently.
    """

    name = "core"
    base = "https://api.core.ac.uk/v3"
    capabilities = {Capability.SEARCH: True, Capability.LOOKUP_IDENTIFIER: True, Capability.RETRIEVE_METADATA: True,
                    Capability.LOCATE_FULL_TEXT: True, Capability.RETRIEVE_PERMITTED_FULL_TEXT: True,
                    Capability.REPORT_QUOTA: False}

    def __init__(self, enabled: bool = False, api_key: str | None = None):
        key = api_key or (get_worker_settings().core_api_key.get_secret_value()
                          if get_worker_settings().core_api_key else None)
        self.key = key
        self.enabled = enabled and key is not None

    def _check(self) -> None:
        if not self.enabled:
            raise Disabled(self.name, "CORE is disabled until its license eligibility and API key are verified")

    @staticmethod
    def _authors(x: dict) -> list[str]:
        out = []
        for a in x.get("authors") or []:
            n = a if isinstance(a, str) else (a or {}).get("name")
            if n:
                out.append(n)
        return out

    def _record(self, x: dict) -> PaperRecord:
        dl = x.get("download_url") or x.get("downloadUrl")
        return PaperRecord(
            provider=self.name, external_id=str(x.get("id")), doi=normalize_doi(x.get("doi")), title=x.get("title") or "",
            authors=self._authors(x), year=x.get("year_published") or x.get("yearPublished"),
            publisher=x.get("publisher"), type=x.get("document_type") or x.get("documentType"),
            abstract=x.get("abstract"), abstract_rights="unknown", license=None, open_access=bool(dl) or None,
            fulltext=[FullTextLocation(url=dl, source="core", access="open")] if dl else [],
            metadata_license="CORE API terms [VERIFY]", attribution="Data provided by CORE (core.ac.uk)")

    async def _search(self, q: str, limit: int, offset: int = 0) -> SearchPage:
        self._check()
        r = await self._get(f"{self.base}/search/works/", params={"q": q, "limit": min(limit, 100), "offset": offset},
                            headers={"Authorization": f"Bearer {self.key}"})
        d = r.json()
        recs = [self._record(x) for x in d.get("results") or [] if x.get("title")]
        total = d.get("total_hits", d.get("totalHits"))
        nxt = str(offset + len(d.get("results") or [])) if total and offset + len(d.get("results") or []) < total else None
        return SearchPage(recs, total, nxt)

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        return await self._search(query, limit, int(cursor or 0))

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        page = await self._search(f'doi:"{normalize_doi(doi) or doi}"', 1)
        return next((r for r in page.records if r.doi == normalize_doi(doi)), None)


class ConnectedAccountAdapter(Adapter):
    """Elicit / Consensus: researcher-owned connections. Never enabled unless the provider gate is cleared, the
    researcher has an eligible connected account, and the call is attributed to that connection (M10)."""

    capabilities = {Capability.SEARCH: True, Capability.REPORT_QUOTA: True}

    def __init__(self, name: str, gate_status: str, credential: str | None = None):
        self.name = name
        self.gate_status = gate_status
        self.credential = credential

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        if self.gate_status != "cleared":
            raise Disabled(self.name, f"{self.name} integration is not cleared for use ({self.gate_status})")
        if not self.credential:
            raise Disabled(self.name, "no eligible researcher connection")
        raise Disabled(self.name, "connector implementation is enabled only after the provider gate review (M10)")


def base_adapters() -> dict[str, Adapter]:
    return {"openaire": OpenAireAdapter(), "crossref": CrossrefAdapter()}
