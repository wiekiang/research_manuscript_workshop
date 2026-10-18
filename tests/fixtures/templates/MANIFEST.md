# Official LaTeX template fixtures (PRODUCT_SPEC §2.3, M3)

Retrieved 2026-10-18 from CTAN, the distribution channel the publishers' template pages point to. The publishers'
own download URLs (ACM `portalparts.acm.org`, IEEE `ieee.org/.../Conference-LaTeX-template_10-17-19.zip`)
refused scripted retrieval (HTTP 403 / 202 with an empty body), so for those venues the product's
"researcher-supplied file with declared origin" path is the documented fallback.

| File | Template | Publisher / venues | Version | Source URL | SHA-256 | License | Permitted test use |
|---|---|---|---|---|---|---|---|
| `acmart.zip` | ACM Primary Article Template (`acmart`, `sigconf` mode; generated from `acmart.dtx` via `acmart.ins`) | ACM conference proceedings | 2.20 (CTAN, Aug 2026) | https://mirrors.ctan.org/macros/latex/contrib/acmart.zip | `93933ce58fbeffa13e23398bb523fcb68275ecc73369c6bc73b421eeef2c10de` | LPPL 1.3c | Redistribution of the unmodified package is permitted by the LPPL; used unmodified as protected files. |
| `IEEEtran.zip` | IEEEtran (`conference` mode, `bare_conf.tex` conventions) | IEEE conferences | 1.8b | https://mirrors.ctan.org/macros/latex/contrib/IEEEtran.zip | `e0cd4f5afbd42c8076092280e72b3e0a5111efe501d35de9f715cfb8da313cb4` | LPPL | Unmodified redistribution permitted. |
| `llncs.zip` | Springer LNCS (`llncs`, `splncs04.bst`) | Springer LNCS proceedings | 2.26 (2025/02/25) | https://mirrors.ctan.org/macros/latex/contrib/llncs.zip | `932940fb23574fbc8c61afe6094e2debe0955e1bc6f971f734f3cb4de5d1167a` | CC BY 4.0 | Redistribution with attribution permitted. |

## Compatibility matrix coverage (§2.3)

| Configuration | Fixture(s) | Test |
|---|---|---|
| Standard conference submission | acmart, IEEEtran, llncs | `workers/latex/tests/test_template_matrix.py::test_standard_compile` |
| Double-blind submission (no author/ack/file-name/PDF-metadata leakage) | acmart (`review,anonymous`), IEEEtran, llncs | `::test_double_blind` |
| BibTeX mode | acmart (ACM-Reference-Format), IEEEtran (IEEEtran.bst), llncs (splncs04) | `::test_standard_compile` |
| Biber mode | acmart (`acmnumeric` biblatex style) | `::test_biber_mode` |
| Figures and tables | all (sample figure PDF + booktabs table) | `::test_standard_compile` |
| Supplementary material include/exclude by rule | package builder | `::test_supplementary_rules` |
| Unsupported or ambiguous template | Word-only zip, unknown class, two classes, unsafe archives | `::test_unsupported_and_unsafe` |

A passing fixture does not imply support for an untested venue. Before production each venue's current
official template must be re-verified ([VERIFY]) and recorded in the template register.
