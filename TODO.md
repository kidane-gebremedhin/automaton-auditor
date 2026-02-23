# Automaton Auditor – TODO Checklist

Structured checklist for the Digital Courtroom implementation, grouped by phase.

---

## Phase 1: State & Graph Foundation

- [ ] **Typed AgentState** – Ensure `AgentState` in `src/state.py` supports all required fields
- [ ] **Evidence model** – Finalize `Evidence` (source, criterion_id, content, metadata)
- [ ] **JudicialOpinion model** – Finalize `JudicialOpinion` (judge, criterion_id, verdict, reasoning)
- [ ] **Graph wiring** – Wire nodes and edges in `src/graph.py`

---

## Phase 2: Detectives (Evidence Collection)

- [ ] **Safe git clone** – Implement `clone_repo()` in `src/tools/repo_investigator.py` using temp dir
- [ ] **RepoInvestigator** – Implement `investigate_repo()` to analyze structure, key files, tests
- [ ] **DocAnalyst** – Implement PDF parsing with docling in `src/tools/doc_analyst.py`
- [ ] **DocAnalyst** – Implement `analyze_document()` to extract Evidence from parsed PDF
- [ ] **VisionInspector** – Implement `inspect_images()` and `extract_images_from_pdf()` (optional)
- [ ] **Parallel detectives** – Use LangGraph parallel/send_all for fan-in of RepoInvestigator, DocAnalyst, VisionInspector

---

## Phase 3: Judges (Structured Evaluation)

- [ ] **Prosecutor** – LLM call with rubric + evidence; structured JSON output per criterion
- [ ] **Defense** – LLM call with rubric + evidence; structured output
- [ ] **Tech Lead** – LLM call with rubric + evidence; technical-focus output
- [ ] **Parallel judges** – Fan-in of Prosecutor, Defense, Tech Lead opinions
- [ ] **Structured JSON output** – Ensure each judge returns `JudicialOpinion` list with verdict, reasoning

---

## Phase 4: Chief Justice & Report

- [ ] **Chief Justice** – Deterministic synthesis rules (e.g. majority vote, tie-breaker)
- [ ] **Constitution loading** – Load `rubric/week2_rubric.json` as machine-readable constitution
- [ ] **Markdown report** – Generate report with Executive Summary, Criterion Breakdown, Remediation Plan

---

## Phase 5: Infrastructure & Ops

- [ ] **LangSmith tracing** – Integrate LangSmith for observability
- [ ] **.env-based secrets** – Use `python-dotenv` for API keys and config
- [ ] **CLI entrypoint** – Add `main.py` or CLI to accept repo URL + PDF path, run graph, write report to `audit/`

---

## Phase 6: Rubric & Polish

- [ ] **week2_rubric.json** – Replace placeholder with actual rubric criteria
- [ ] **Tests** – Unit tests for tools and nodes where feasible
- [ ] **README** – Usage instructions, setup, env vars
