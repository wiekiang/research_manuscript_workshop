"""Quarantine scanning for fetched or researcher-supplied bytes (before any commit or agent access)."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

SCANNER_VERSION = "rp-scan/1"
PDF_ACTIVE = [rb"/JavaScript", rb"/JS\b", rb"/Launch", rb"/EmbeddedFile", rb"/RichMedia", rb"/XFA"]


@dataclass
class ScanReport:
    sniffed_type: str
    declared_type: str
    matches_declared: bool
    verdict: str  # clean | suspicious | rejected
    flags: list[str] = field(default_factory=list)
    antivirus: str = "not_configured"
    scanner_version: str = SCANNER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def sniff(data: bytes) -> str:
    head = data[:2048].lstrip()
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    low = head[:512].lower()
    if low.startswith(b"<!doctype html") or b"<html" in low or b"<head" in low or b"<body" in low:
        return "text/html"
    if low.startswith(b"<?xml"):
        return "application/xml"
    try:
        data[:4096].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def _antivirus(data: bytes) -> tuple[str, list[str]]:
    exe = shutil.which("clamdscan") or shutil.which("clamscan")
    if not exe:
        return "not_configured", []
    proc = subprocess.run([exe, "--no-summary", "-"], input=data, capture_output=True, timeout=120)
    if proc.returncode == 0:
        return "clean", []
    if proc.returncode == 1:
        return "infected", [proc.stdout.decode(errors="replace")[:300]]
    return "error", [proc.stderr.decode(errors="replace")[:300]]


def scan(data: bytes, declared_type: str) -> ScanReport:
    sniffed = sniff(data)
    declared = declared_type.split(";")[0].strip().lower()
    compatible = {
        "text/html": {"text/html", "application/xhtml+xml", "text/plain"},
        "application/pdf": {"application/pdf"},
        "application/zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
        "text/plain": {"text/plain", "text/html", "application/octet-stream", "text/markdown"},
        "application/xml": {"application/xml", "text/xml", "application/atom+xml", "application/rss+xml"},
    }
    matches = declared in compatible.get(sniffed, {sniffed})
    flags: list[str] = []
    verdict = "clean"
    if not matches:
        flags.append(f"declared {declared} but content looks like {sniffed}")
        verdict = "suspicious"
    if sniffed == "application/pdf":
        if re.search(rb"/Encrypt\b", data):
            flags.append("encrypted PDF")
            verdict = "rejected"
        for pat in PDF_ACTIVE:
            if re.search(pat, data):
                flags.append(f"active PDF content {pat.decode()}")
                verdict = "suspicious" if verdict == "clean" else verdict
    if sniffed == "text/html":
        scripts = len(re.findall(rb"<script", data, re.I))
        if scripts:
            flags.append(f"{scripts} script elements (never executed; stripped before text extraction)")
    av, av_flags = _antivirus(data)
    flags += av_flags
    if av == "infected":
        verdict = "rejected"
    return ScanReport(sniffed, declared, matches, verdict, flags, av)
