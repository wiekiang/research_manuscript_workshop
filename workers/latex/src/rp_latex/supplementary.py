"""Supplementary material selection against the selected track's official rule, with a manifest."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from hashlib import sha256


@dataclass
class SupplementaryRule:
    allowed: bool | None  # None = the CFP does not say (requires human resolution)
    max_total_mb: float | None = None
    allowed_extensions: list[str] | None = None
    anonymous: bool = False
    source_rule_id: str | None = None

    @classmethod
    def from_text(cls, value_text: str | None, value: str | None, anonymous: bool, rule_id: str | None) -> SupplementaryRule:
        if not value_text and not value:
            return cls(None, anonymous=anonymous, source_rule_id=rule_id)
        txt = f"{value_text or ''} {value or ''}".lower()
        if re.search(r"not (be )?(permitted|allowed)|no supplementary", txt):
            return cls(False, anonymous=anonymous, source_rule_id=rule_id)
        m = re.search(r"(\d+(?:\.\d+)?)\s*mb", txt)
        return cls(True, float(m.group(1)) if m else None, None, anonymous, rule_id)


@dataclass
class ManifestEntry:
    name: str
    sha256: str
    size: int
    included: bool
    reason: str


@dataclass
class SupplementaryManifest:
    status: str  # passed | failed | manual_check
    entries: list[ManifestEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def select(files: dict[str, bytes], rule: SupplementaryRule, identity_terms: list[str] | None = None) -> SupplementaryManifest:
    out = SupplementaryManifest(status="passed")
    if not files:
        out.notes.append("no supplementary material")
        return out
    if rule.allowed is None:
        out.status = "manual_check"
        out.notes.append("the official rules do not state whether supplementary material is allowed; a human must decide")
        for n, d in files.items():
            out.entries.append(ManifestEntry(n, sha256(d).hexdigest(), len(d), False, "excluded pending human decision"))
        return out
    total = 0
    for name, data in sorted(files.items()):
        digest = sha256(data).hexdigest()
        if not rule.allowed:
            out.entries.append(ManifestEntry(name, digest, len(data), False, "track rules do not allow supplementary material"))
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if rule.allowed_extensions and ext not in rule.allowed_extensions:
            out.entries.append(ManifestEntry(name, digest, len(data), False, f".{ext} files are not permitted"))
            continue
        if rule.max_total_mb is not None and (total + len(data)) / 1e6 > rule.max_total_mb:
            out.entries.append(ManifestEntry(name, digest, len(data), False,
                                             f"would exceed the {rule.max_total_mb:g} MB limit"))
            out.status = "failed"
            continue
        if rule.anonymous:
            low_name = name.lower()
            hits = [t for t in (identity_terms or []) if len(t) >= 3 and t.lower().replace(" ", "") in low_name.replace("_", "")]
            text = data[:2_000_000].decode("utf-8", "ignore").lower()
            hits += [t for t in (identity_terms or []) if len(t) >= 3 and t.lower() in text]
            if hits:
                out.entries.append(ManifestEntry(name, digest, len(data), False,
                                                 f"identifying content in a double-blind package: {sorted(set(hits))}"))
                out.status = "failed"
                continue
        total += len(data)
        out.entries.append(ManifestEntry(name, digest, len(data), True, "permitted by the track rule"))
    return out
