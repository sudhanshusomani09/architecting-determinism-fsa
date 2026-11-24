# Iteration 3: Pilot Statutory Parser & Sprint-Ready 5-Agent MAS Blueprint

> **Implementation Status & Transparency Note**
> - **`xhtml_code_parser.py` (Validated Pilot):** Empirically validated on Indian Standard **IS 2190:2010** in September 2026 (achieving 97.87% word recovery across 96 clauses and 13 unfolded relational tables).
> - **`intake_schemas.py`, `qa_contracts.py`, `ast_repl_sandbox.py` (First-Draft Reference Blueprints):** Newly implemented architectural reference modules translating the whitepaper (Section 4.5) and the 13-page QA Agent V&V SOP (`docs/whitepaper/QA_Agent_SOP.pdf`) into unit-tested Python contracts. The full end-to-end 5-Agent MAS has **not** yet been wired to live LLM APIs or tested against real production audit cases.

## Modules
1. **`xhtml_code_parser.py`** — Deterministic `lxml`/BeautifulSoup parser that unfolds `rowspan`/`colspan` statutory tables, isolates footnotes, links tables via `[[TBL_REF::...]]`, and runs the **5-Test Deterministic Knowledge Base Audit Suite**.
2. **`intake_schemas.py`** — Agent 1 (Intake & Scoping) Pydantic schemas enforcing the **21-Document Prerequisite Matrix** (with automated RFI generation), the **Master Facility Envelope** (10 global NBC 2016 parameters), and the **Micro-Zone Array** (localized proactive triggers).
3. **`qa_contracts.py`** — Agent 5 (QA Auditor) Pydantic data contracts (`MathematicalContract`, `StatutoryContract`, `ContextualContract`, `ValidationReport`) aligned with **IEEE 1012**, **ASME V&V 40**, and **ASME V&V 20**.
4. **`ast_repl_sandbox.py`** — Isolated `ast.NodeVisitor` mathematical evaluation sandbox prohibiting `eval()`, paired with hardcoded fire engineering equations, Hazen-Williams physical Context-of-Use bounds (`4–14 °C`, `v <= 7.6 m/s`, verified C-factors), and Track A/B adjudication logic (`[FATAL ERROR]`, `[CONTEXTUAL FAILURE]`, `[OVERSIMPLIFICATION]`).
