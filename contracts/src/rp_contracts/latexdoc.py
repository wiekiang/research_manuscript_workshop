"""Template-independent manuscript document model rendered by the LaTeX content adapters.

Text is restricted markup, never raw LaTeX: everything is escaped except inline citation markers `[@key]` /
`[@a; @b]`, `**bold**`, `*italic*`, `` `code` `` and math blocks whose commands come from a whitelist. This
keeps model- or user-supplied text from injecting TeX primitives into the compile.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

BlockType = Literal["paragraph", "subsection", "subsubsection", "bullet_list", "numbered_list", "equation",
                    "figure", "table"]


class Author(BaseModel):
    name: str
    affiliation: str | None = None
    country: str | None = None
    email: str | None = None
    orcid: str | None = None


class Block(BaseModel):
    type: BlockType
    text: str | None = None
    items: list[str] = Field(default_factory=list)
    figure_file: str | None = None
    caption: str | None = None
    label: str | None = None
    width: float = 0.95
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    span_id: str | None = None


class Section(BaseModel):
    heading: str
    label: str | None = None
    blocks: list[Block]
    unnumbered: bool = False


class ManuscriptDocument(BaseModel):
    title: str
    abstract: str
    keywords: list[str] = Field(default_factory=list)
    authors: list[Author] = Field(default_factory=list)
    sections: list[Section]
    appendix: list[Section] = Field(default_factory=list)
    acknowledgments: str | None = None
    bibtex: str = ""
    figures: dict[str, str] = Field(default_factory=dict, description="figure file name -> artifact id")


class RenderOptions(BaseModel):
    mode: Literal["submission", "camera_ready"] = "submission"
    anonymous: bool = False
    bib_mode: Literal["bibtex", "biber"] = "bibtex"


SPECIALS = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{",
            "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}"}
CITE_RE = re.compile(r"\[(@[A-Za-z0-9_:\-./]+(?:\s*;\s*@[A-Za-z0-9_:\-./]+)*)\]")
KEY_RE = re.compile(r"^[A-Za-z0-9_:\-./]{1,120}$")
MATH_COMMANDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "lambda", "mu", "nu", "xi",
    "pi", "rho", "sigma", "tau", "phi", "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Sigma",
    "Phi", "Psi", "Omega", "frac", "sqrt", "sum", "prod", "int", "log", "ln", "exp", "max", "min", "arg", "argmax",
    "argmin", "cdot", "times", "pm", "leq", "geq", "neq", "approx", "sim", "propto", "infty", "partial", "nabla",
    "mathbb", "mathbf", "mathrm", "mathcal", "hat", "bar", "tilde", "vec", "left", "right", "in", "notin", "subset",
    "subseteq", "cup", "cap", "forall", "exists", "to", "mid", "ldots", "cdots", "quad", "qquad", "text", "operatorname",
    "mathit", "top", "lVert", "rVert", "lvert", "rvert", "langle", "rangle", "binom", "lim", "sup", "inf", "Pr", "E",
}


def escape(text: str) -> str:
    return "".join(SPECIALS.get(c, c) for c in text)


def inline(text: str) -> str:
    """Escape text and convert the restricted inline markup."""
    out = []
    pos = 0
    for m in CITE_RE.finditer(text):
        out.append(_emphasis(text[pos:m.start()]))
        keys = [k.strip().lstrip("@") for k in m.group(1).split(";")]
        out.append(r"\cite{" + ",".join(k for k in keys if KEY_RE.match(k)) + "}")
        pos = m.end()
    out.append(_emphasis(text[pos:]))
    return "".join(out)


def _emphasis(text: str) -> str:
    parts = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", text)
    res = []
    for p in parts:
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            res.append(r"\textbf{" + escape(p[2:-2]) + "}")
        elif p.startswith("*") and p.endswith("*") and len(p) > 2:
            res.append(r"\emph{" + escape(p[1:-1]) + "}")
        elif p.startswith("`") and p.endswith("`") and len(p) > 2:
            res.append(r"\texttt{" + escape(p[1:-1]) + "}")
        else:
            res.append(escape(p))
    return "".join(res)


class UnsafeMath(ValueError):
    pass


def sanitize_math(expr: str) -> str:
    for cmd in re.findall(r"\\([A-Za-z]+)", expr):
        if cmd not in MATH_COMMANDS:
            raise UnsafeMath(f"math command \\{cmd} is not allowed")
    if re.search(r"\\[^A-Za-z,;:!{}|\\ ]", expr) or "$" in expr or "%" in expr or "#" in expr:
        raise UnsafeMath("math contains disallowed characters")
    return expr


def safe_label(label: str | None) -> str | None:
    if not label:
        return None
    clean = re.sub(r"[^A-Za-z0-9:_\-]", "", label)[:60]
    return clean or None


def safe_filename(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}\.(pdf|png|jpg|jpeg)", name):
        raise ValueError(f"figure file name {name!r} is not allowed")
    return name
