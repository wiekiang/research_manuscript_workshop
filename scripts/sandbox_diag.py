#!/usr/bin/env python3
"""Print a short failure summary of a saved compile report or run output JSON.

Usage: uv run scripts/sandbox_diag.py var/report.json [more.json ...]
"""
import sys

from rp_latex.diagnostics import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
