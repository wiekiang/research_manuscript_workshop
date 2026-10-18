"""Safe analysis of LaTeX template archives (PRODUCT_SPEC §2.3).

The archive is never extracted to the host filesystem. Members are read in memory after validation:
path traversal, absolute paths, symlinks, nested archives, executables, decompression bombs and oversized
archives are rejected; dangerous TeX primitives are flagged. The result is a manifest that marks style/class/
bibliography files as protected so later compiles can prove they were not modified.
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath

MAX_MEMBERS = 3000
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_RATIO = 200
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".zst", ".cab"}
EXEC_EXT = {".exe", ".dll", ".so", ".dylib", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".com", ".app", ".bin",
            ".msi", ".scr", ".vbs", ".jse"}
MAGIC_BINARIES = [b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe"]
MAGIC_ARCHIVES = [b"PK\x03\x04", b"\x1f\x8b", b"7z\xbc\xaf", b"Rar!", b"BZh", b"\xfd7zXZ"]
PROTECTED_EXT = {".cls", ".sty", ".bst", ".bbx", ".cbx", ".dbx", ".lbx", ".clo", ".def", ".fd", ".dtx", ".ins",
                 ".pfb", ".tfm", ".vf", ".otf", ".ttf", ".map", ".enc"}
TEX_EXT = {".tex", ".cls", ".sty", ".dtx", ".ins", ".def", ".clo", ".ltx"}
DANGEROUS = [
    (re.compile(rb"\\(immediate\s*)?\\?write18"), "uses \\write18 (shell escape)"),
    (re.compile(rb"\\input\s*\|"), "pipes input from a shell command"),
    (re.compile(rb"\\(directlua|luaexec|luadirect)\b"), "executes Lua code"),
    (re.compile(rb"\\(ShellEscape|shellescape)\b"), "requests shell escape"),
    (re.compile(rb"\\usepackage(\[[^\]]*\])?\{(minted|pythontex|shellesc|sagetex|gnuplottex)\}"),
     "loads a package that needs shell escape"),
    (re.compile(rb"\\open(out|in)\s*\d*\s*=?\s*[/~]"), "reads or writes an absolute path"),
]


class ArchiveRejected(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class Member:
    path: str
    sha256: str
    size: int
    role: str
    protected: bool


@dataclass
class Issue:
    severity: str  # error | warning | info
    code: str
    message: str
    path: str | None = None


@dataclass
class TemplateManifest:
    family: str
    root: str
    class_name: str | None
    requires_generation: bool
    generation_inputs: list[str]
    bib_modes: list[str]
    bibtex_style: str | None
    members: list[Member]
    issues: list[Issue]
    readme_excerpt: str | None
    supported: bool
    unsupported_reasons: list[str] = field(default_factory=list)
    analyzer_version: str = "rp-template-analyzer/1"

    def to_dict(self) -> dict:
        return asdict(self)

    def protected_hashes(self) -> dict[str, str]:
        return {m.path: m.sha256 for m in self.members if m.protected}


def _role(path: str) -> str:
    p = PurePosixPath(path)
    ext = p.suffix.lower()
    name = p.name.lower()
    if ext == ".cls":
        return "class"
    if ext in (".sty", ".def", ".clo", ".fd"):
        return "style"
    if ext in (".bst", ".bbx", ".cbx", ".dbx", ".lbx"):
        return "bibliography_style"
    if ext in (".dtx", ".ins"):
        return "source_generator"
    if ext == ".tex":
        return "sample_tex"
    if ext == ".bib":
        return "bibliography_data"
    if ext in (".png", ".jpg", ".jpeg", ".eps", ".svg"):
        return "figure"
    if ext == ".pdf":
        return "figure" if ("sample" in name or "fig" in name) and "doc" not in name else "documentation"
    if name.startswith("readme") or name in ("license", "license.txt", "copying"):
        return "readme"
    if name == "makefile":
        return "build_script_ignored"
    if ext in (".pfb", ".tfm", ".vf", ".otf", ".ttf", ".map", ".enc"):
        return "font"
    return "other"


def _check_name(name: str) -> str | None:
    if "\x00" in name or any(ord(c) < 32 for c in name):
        return "control characters in member name"
    if name.startswith("/") or name.startswith("\\") or re.match(r"^[A-Za-z]:", name):
        return "absolute path"
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if ".." in parts:
        return "path traversal (..)"
    return None


def analyze(data: bytes, filename_hint: str = "template.zip") -> TemplateManifest:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveRejected(["not a valid ZIP archive"]) from exc
    infos = zf.infolist()
    reasons: list[str] = []
    if len(infos) > MAX_MEMBERS:
        reasons.append(f"too many members ({len(infos)} > {MAX_MEMBERS})")
    total = sum(i.file_size for i in infos)
    if total > MAX_TOTAL_BYTES:
        reasons.append(f"uncompressed size {total} exceeds {MAX_TOTAL_BYTES}")
    members: list[Member] = []
    issues: list[Issue] = []
    contents: dict[str, bytes] = {}
    for info in infos:
        name = info.filename
        bad = _check_name(name)
        if bad:
            reasons.append(f"{name!r}: {bad}")
            continue
        mode = (info.external_attr >> 16) & 0o177777
        if stat.S_ISLNK(mode):
            reasons.append(f"{name}: symbolic link")
            continue
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            reasons.append(f"{name}: encrypted member")
            continue
        if info.file_size > 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            reasons.append(f"{name}: suspicious compression ratio (possible zip bomb)")
            continue
        ext = PurePosixPath(name).suffix.lower()
        if ext in ARCHIVE_EXT:
            reasons.append(f"{name}: nested archive")
            continue
        if ext in EXEC_EXT:
            reasons.append(f"{name}: executable content")
            continue
        body = zf.read(info)
        if any(body.startswith(m) for m in MAGIC_BINARIES):
            reasons.append(f"{name}: binary executable")
            continue
        if any(body.startswith(m) for m in MAGIC_ARCHIVES) and ext not in (".pdf", ".docx", ".odt"):
            reasons.append(f"{name}: nested archive content")
            continue
        role = _role(name)
        members.append(Member(name, sha256(body).hexdigest(), len(body), role, ext in PROTECTED_EXT))
        contents[name] = body
        if ext in TEX_EXT:
            for pat, msg in DANGEROUS:
                if pat.search(body):
                    issues.append(Issue("warning", "dangerous_primitive", msg, name))
        if role == "build_script_ignored":
            issues.append(Issue("info", "build_script_ignored", "build scripts are never executed", name))
    if reasons:
        raise ArchiveRejected(reasons)
    return _detect(members, contents, issues)


def _detect(members: list[Member], contents: dict[str, bytes], issues: list[Issue]) -> TemplateManifest:
    names = {PurePosixPath(m.path).name.lower(): m.path for m in members}
    families = []
    if "acmart.cls" in names or "acmart.dtx" in names:
        families.append(("acmart", "acmart", names.get("acmart.cls") or names["acmart.dtx"]))
    if "ieeetran.cls" in names:
        families.append(("ieeetran", "IEEEtran", names["ieeetran.cls"]))
    if "llncs.cls" in names:
        families.append(("llncs", "llncs", names["llncs.cls"]))
    unsupported: list[str] = []
    if not families:
        classes = [m.path for m in members if m.role == "class"]
        if not classes and not any(m.role == "sample_tex" for m in members):
            unsupported.append("no LaTeX class or sample document found (e.g. a Word-only template)")
        else:
            unsupported.append(f"no adapter exists for this template class ({', '.join(classes) or 'unknown'}); "
                               "it cannot be labelled submission-ready")
        family, cls, anchor = "unknown", None, (classes[0] if classes else (members[0].path if members else ""))
    elif len(families) > 1:
        unsupported.append("ambiguous template: several conference classes are present: "
                           + ", ".join(f[1] for f in families))
        family, cls, anchor = "ambiguous", None, families[0][2]
    else:
        family, cls, anchor = families[0]
    root = str(PurePosixPath(anchor).parent) if anchor else ""
    root = "" if root == "." else root
    requires_generation = family == "acmart" and "acmart.cls" not in names
    gen_inputs = [names["acmart.ins"]] if requires_generation and "acmart.ins" in names else []
    if requires_generation and not gen_inputs:
        unsupported.append("class must be generated from .dtx but no .ins driver is present")
    bsts = [PurePosixPath(m.path).stem for m in members if m.path.lower().endswith(".bst")]
    bib_modes = []
    preferred = {"acmart": "ACM-Reference-Format", "ieeetran": "IEEEtran", "llncs": "splncs04"}.get(family)
    bib_style = preferred if preferred in bsts else (bsts[0] if bsts else None)
    if bib_style:
        bib_modes.append("bibtex")
    if any(m.path.lower().endswith((".bbx", ".cbx")) for m in members) and family == "acmart":
        bib_modes.append("biber")
    if family in ("acmart", "ieeetran", "llncs") and not bib_modes:
        unsupported.append("no bibliography style shipped with the template")
    readme = next((m for m in members if m.role == "readme"), None)
    excerpt = contents[readme.path][:1500].decode("utf-8", "replace") if readme else None
    return TemplateManifest(family=family, root=root, class_name=cls, requires_generation=requires_generation,
                            generation_inputs=gen_inputs, bib_modes=bib_modes, bibtex_style=bib_style, members=members,
                            issues=issues, readme_excerpt=excerpt, supported=not unsupported,
                            unsupported_reasons=unsupported)


def read_members(data: bytes, root: str) -> dict[str, bytes]:
    """Validated members under the template root, keyed by path relative to the root."""
    analyze(data)  # re-validate before reading
    zf = zipfile.ZipFile(io.BytesIO(data))
    out = {}
    prefix = f"{root}/" if root else ""
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix):]
        if rel:
            out[rel] = zf.read(info)
    return out
