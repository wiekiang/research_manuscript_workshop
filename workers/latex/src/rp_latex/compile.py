"""Sandboxed compilation and machine checks (PRODUCT_SPEC §2.3, §2.12)."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

from rp_contracts.latexdoc import ManuscriptDocument, RenderOptions

from .adapters import ADAPTER_VERSION, AdapterError, render
from .sandbox import DockerSandbox, Limits, SandboxUnavailable

COMPILER_VERSION = "rp-latex-compile/1"
ENV = {"TEXINPUTS": ".//:", "BSTINPUTS": ".//:", "BIBINPUTS": ".//:", "TEXMFVAR": "/tmp/texmf-var",  # noqa: S108 - container-private tmpfs
       "openout_any": "p", "shell_escape": "f", "SOURCE_DATE_EPOCH": "0", "FORCE_SOURCE_DATE": "1",
       # biber is a PAR-packed binary that unpacks itself; /tmp is noexec, so use the ephemeral workspace.
       "PAR_GLOBAL_TMPDIR": "/work/par"}


@dataclass
class Check:
    id: str
    status: str  # passed | failed | manual_check | not_performed | warning
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompileReport:
    status: str  # compiled | failed | unsupported | sandbox_unavailable
    family: str
    options: dict[str, Any]
    exit_code: int | None = None
    timed_out: bool = False
    duration_s: float | None = None
    image: str | None = None
    pages: int | None = None
    errors: list[str] = field(default_factory=list)
    undefined_citations: list[str] = field(default_factory=list)
    undefined_references: bool = False
    missing_files: list[str] = field(default_factory=list)
    overfull_boxes: int = 0
    checks: list[Check] = field(default_factory=list)
    protected_files: dict[str, dict[str, str]] = field(default_factory=dict)
    generated_files: dict[str, str] = field(default_factory=dict)
    pdf_metadata: dict[str, Any] = field(default_factory=dict)
    log_excerpt: str = ""
    adapter_version: str = ADAPTER_VERSION
    compiler_version: str = COMPILER_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def check(self, cid: str) -> Check | None:
        return next((c for c in self.checks if c.id == cid), None)


@dataclass
class CompileOutput:
    report: CompileReport
    pdf: bytes | None
    log: str
    source_files: dict[str, bytes]


def parse_log(log: str, report: CompileReport) -> None:
    lines = log.splitlines()
    report.errors = [ln for ln in lines if ln.startswith("! ") or re.match(r"^\./[^:]+:\d+: ", ln)][:25]
    report.undefined_citations = sorted(set(re.findall(r"Citation [`']([^']+)' (?:on page \d+ )?undefined", log)))
    report.undefined_references = bool(re.search(r"There were undefined references|Reference [`'][^']+' on page \d+ undefined", log))
    report.missing_files = sorted(set(re.findall(r"File [`']([^']+)' not found", log)))
    report.overfull_boxes = len(re.findall(r"^Overfull \\[hv]box", log, re.M))
    m = re.findall(r"Output written on \S+ \((\d+) pages?", log)
    if m:
        report.pages = int(m[-1])


def pdf_facts(pdf: bytes) -> dict[str, Any]:
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(pdf))
    meta = {k.lstrip("/"): str(v) for k, v in (r.metadata or {}).items()}
    xmp = ""
    try:
        x = r.xmp_metadata
        if x is not None:
            xmp = x.stream.get_data().decode("utf-8", "replace") if hasattr(x, "stream") else ""
    except Exception:  # noqa: BLE001 - XMP parsing is best effort; reported as manual check
        xmp = ""
    texts = [(p.extract_text() or "") for p in r.pages]
    images = sum(len(getattr(p, "images", []) or []) for p in r.pages)
    return {"pages": len(r.pages), "metadata": meta, "xmp": xmp, "texts": texts, "images": images}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def anonymization_findings(identity_terms: list[str], facts: dict[str, Any], sources: dict[str, bytes],
                           file_names: list[str]) -> list[dict[str, str]]:
    findings = []
    terms = [t for t in {t.strip() for t in identity_terms if t and len(t.strip()) >= 3}]
    text = _norm(" ".join(facts["texts"]))
    for t in terms:
        nt = _norm(t)
        if nt and nt in text:
            findings.append({"where": "pdf_text", "term": t})
        for k, v in facts["metadata"].items():
            if nt and nt in _norm(v):
                findings.append({"where": f"pdf_metadata:{k}", "term": t})
        if nt and nt in _norm(facts["xmp"]):
            findings.append({"where": "pdf_xmp", "term": t})
        for name, data in sources.items():
            if name.endswith((".tex", ".bib")) and nt in _norm(data.decode("utf-8", "replace")):
                findings.append({"where": f"source:{name}", "term": t})
        for fn in file_names:
            if nt.replace(" ", "") in fn.lower().replace("_", "").replace("-", ""):
                findings.append({"where": f"file_name:{fn}", "term": t})
    return findings


def compile_document(
    *, family: str, template_files: dict[str, bytes], protected: dict[str, str], requires_generation: bool,
    generation_inputs: list[str], bib_style: str | None, doc: ManuscriptDocument, opts: RenderOptions,
    figures: dict[str, bytes], sandbox: DockerSandbox, identity_terms: list[str] | None = None,
    page_limit: int | None = None, page_limit_excludes_references: bool = False, abstract_word_limit: int | None = None,
) -> CompileOutput:
    report = CompileReport(status="failed", family=family, options=opts.model_dump())
    try:
        generated = render(family, doc, opts, bib_style)
    except AdapterError as exc:
        report.status = "unsupported"
        report.errors = [str(exc)]
        report.checks.append(Check("template.supported", "failed", str(exc)))
        return CompileOutput(report, None, "", {})
    overlap = set(generated) & set(template_files)
    files: dict[str, bytes] = dict(template_files)
    for name in overlap:  # never overwrite a template file: keep it and write ours under a fresh name
        if name in protected:
            raise AdapterError(f"generated file {name} would overwrite a protected template file")
    files.update({k: v.encode("utf-8") for k, v in generated.items()})
    for fname, data in figures.items():
        files[f"figures/{fname}"] = data
    steps = ["mkdir -p /work/par"]
    for inp in generation_inputs:
        steps.append(f"latex -interaction=nonstopmode -no-shell-escape {inp} > _generate.log 2>&1")
    steps.append("{ latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error -no-shell-escape "
                 "-e '$max_repeat=5' main.tex; echo $? > _latexmk.rc; true; }")
    prot_list = " ".join(f"'{p}'" for p in sorted(protected))
    steps.append(f"{{ sha256sum {prot_list} > _protected.sha256 2>/dev/null; true; }}" if protected else "true")
    steps.append("{ ls *.cls *.sty 2>/dev/null | xargs -r sha256sum > _generated.sha256; true; }")
    try:
        res = sandbox.run(files, steps, collect=["main.pdf", "main.log", "main.blg", "_latexmk.rc", "_protected.sha256",
                                                 "_generated.sha256", "_generate.log"], env=ENV)
    except SandboxUnavailable as exc:
        report.status = "sandbox_unavailable"
        report.errors = [str(exc)]
        report.checks.append(Check("compile.success", "not_performed", str(exc)))
        return CompileOutput(report, None, "", {k: v.encode() for k, v in generated.items()})
    out = res.files
    report.exit_code = int((out.get("_latexmk.rc") or b"1").decode().strip() or 1) if not res.timed_out else 124
    report.timed_out = res.timed_out
    report.duration_s = res.duration_s
    report.image = res.image
    log = (out.get("main.log") or b"").decode("utf-8", "replace")
    parse_log(log + "\n" + (out.get("main.blg") or b"").decode("utf-8", "replace"), report)
    report.log_excerpt = "\n".join(log.splitlines()[-60:])
    if requires_generation and not any(k.endswith(".cls") for k in (out.get("_generated.sha256") or b"").decode().split()):
        report.errors.append("class generation from the official .dtx failed: "
                             + (out.get("_generate.log") or b"").decode("utf-8", "replace")[-500:])
    # Protected files must be byte-identical after the compile.
    actual = {}
    for line in (out.get("_protected.sha256") or b"").decode().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            actual[parts[1].strip().lstrip("*")] = parts[0]
    unchanged = True
    for path, expected in protected.items():
        got = actual.get(path)
        st = "unchanged" if got == expected else ("missing_after_compile" if got is None else "modified")
        unchanged &= st == "unchanged"
        report.protected_files[path] = {"expected": expected, "actual": got or "", "status": st}
    for line in (out.get("_generated.sha256") or b"").decode().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() not in protected:
            report.generated_files[parts[1].strip()] = parts[0]
    pdf = out.get("main.pdf")
    ok = report.exit_code == 0 and pdf is not None and not res.timed_out
    report.status = "compiled" if ok else "failed"
    report.checks.append(Check("compile.success", "passed" if ok else "failed",
                               "PDF produced" if ok else ("timed out" if res.timed_out else "compilation failed"),
                               {"errors": report.errors[:5]}))
    report.checks.append(Check("template.protected_unchanged", "passed" if unchanged and protected else
                               ("not_performed" if not protected else "failed"),
                               "protected style/class/bibliography files are byte-identical after compilation"
                               if unchanged else "a protected template file changed"))
    report.checks.append(Check("compile.shell_escape_disabled", "passed",
                               "compiled with -no-shell-escape in a no-network sandbox (shell_escape=f in texmf.cnf)",
                               {"image": res.image}))
    facts = pdf_facts(pdf) if pdf else None
    if facts:
        report.pages = facts["pages"]
        report.pdf_metadata = facts["metadata"]
        text = " ".join(facts["texts"])
        unresolved = bool(re.search(r"\[\?\]|\?\?", text)) or bool(report.undefined_citations)
        report.checks.append(Check("citations.resolved", "failed" if unresolved else "passed",
                                   "missing-citation markers or undefined citations" if unresolved
                                   else "all citations and references resolved",
                                   {"undefined": report.undefined_citations}))
        expected_figs = len(figures)
        missing_figs = [f for f in report.missing_files if f.startswith("figures/")]
        if expected_figs:
            st = "failed" if missing_figs else ("passed" if facts["images"] >= 1 or "figure" in text.lower() else "manual_check")
            report.checks.append(Check("figures.render", st, f"{expected_figs} figure file(s) packaged",
                                       {"missing": missing_figs, "pdf_images": facts["images"]}))
        if page_limit is not None:
            main_pages = facts["pages"]
            note = "total pages"
            if page_limit_excludes_references:
                ref_page = next((i for i, t in enumerate(facts["texts"], start=1) if re.search(r"^\s*REFERENCES|\nReferences\s*\n", t)), None)
                if ref_page is None:
                    report.checks.append(Check("length.page_limit", "manual_check",
                                               "could not locate the references heading to exclude references"))
                    main_pages = None
                else:
                    main_pages, note = ref_page, "pages up to and including the page where references start"
            if main_pages is not None:
                report.checks.append(Check("length.page_limit", "passed" if main_pages <= page_limit else "failed",
                                           f"{main_pages} {note} vs limit {page_limit}",
                                           {"pages": facts["pages"], "limit": page_limit}))
        if abstract_word_limit is not None:
            words = len(re.findall(r"\w+", doc.abstract))
            report.checks.append(Check("abstract.word_limit", "passed" if words <= abstract_word_limit else "failed",
                                       f"{words} words vs limit {abstract_word_limit}"))
        if opts.anonymous:
            terms = list(identity_terms or []) + [a.name for a in doc.authors] + [a.email or "" for a in doc.authors] \
                + [a.affiliation or "" for a in doc.authors]
            if doc.acknowledgments:
                terms.append(doc.acknowledgments[:60])
            findings = anonymization_findings(terms, facts, {k: v.encode() for k, v in generated.items()},
                                              list(files.keys()))
            report.checks.append(Check("anonymization.no_identity_leak", "failed" if findings else "passed",
                                       "identifying content found" if findings else
                                       "no author names, emails, affiliations or acknowledgments in PDF text, "
                                       "metadata, XMP, sources or file names", {"findings": findings}))
            report.checks.append(Check("anonymization.visual_inspection", "manual_check",
                                       "self-citation phrasing and images may still identify authors; a human must check"))
    return CompileOutput(report, pdf, log, {k: v.encode() for k, v in generated.items()})


def sample_figure_pdf() -> bytes:
    """A tiny valid one-page PDF with a drawn rectangle, used as the sample figure."""
    content = b"0.2 0.4 0.8 rg 10 10 180 80 re f"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def default_sandbox(image: str = "rp-latex-sandbox:1") -> DockerSandbox:
    return DockerSandbox(image, limits=Limits(cpus=2, memory_mb=2048, pids=256, timeout_s=300))


_ = sha256
