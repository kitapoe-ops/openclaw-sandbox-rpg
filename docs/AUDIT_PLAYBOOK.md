# Audit Playbook

> Last updated: 2026-06-05
> Audience: engineers contributing to the framework and subagents
> running pre-work audits before a Phase D subagent starts.

---

## 1. Overview

The audit infra is a **local-only**, **fail-closed** architecture auditor
built on DeepSeek R1-Distill-Qwen-14B (R1-14B) running in LM Studio on
`127.0.0.1:1234`. It is invoked **before** a Phase D subagent begins work,
to surface architectural risks in the candidate files that the subagent
would otherwise discover only after coding. Use it when: (a) you are about
to merge / refactor shipped code (Phase B/C/D candidates), (b) you need a
second opinion on cross-module coupling, (c) you want a reproducible
adversarial review of new code before it lands. It is **not** a code
formatter, a test runner, or a security scanner — it is an architecture
critic that reads code and returns a structured verdict.

---

## 2. Quick Start

### 2.1 Prerequisites

- LM Studio running locally with `deepseek-r1-distill-qwen-14b` loaded
  (see §7).
- Python 3.11+, project venv activated.
- The audit infra lives in `backend/r1_audit_client.py`. No separate
  install step — it is in-tree.

### 2.2 Invoke an audit from the command line

```bash
# Activate venv first
.venv\Scripts\Activate.ps1      # Windows
source .venv/bin/activate       # Linux/macOS

# Run any of the 7 historical + Phase D audit functions
.venv\Scripts\python.exe -c "
import asyncio, json
from backend.r1_audit_client import audit_phase_d1_merge
result = asyncio.run(audit_phase_d1_merge(repo_root='.'))
print('verdict:', result['verdict'])
print('findings:', len(result['findings']))
for f in result['findings']:
    print(f'  [{f[\"severity\"]}] #{f[\"concern_index\"]}: {f[\"issue\"]}')
"
```

The function returns a `dict` with keys: `endpoint` (LM Studio metadata),
`verdict` (PASS / CONDITIONAL / FAIL / BLOCK), `findings` (list of
structured findings), and `raw_response` (R1's full unparsed output for
debugging).

### 2.3 From a pytest test

```python
import pytest, asyncio
from backend.r1_audit_client import audit_phase_d1_merge

@pytest.mark.asyncio
async def test_d1_passes_audit():
    result = await audit_phase_d1_merge(repo_root=".")
    assert result["verdict"] in ("PASS", "CONDITIONAL"), result["raw_response"][:500]
```

The 6 lightweight tests in `backend/tests/test_r1_audit_phase_d.py` are
**network-free** and run in CI. Use them as a smoke test that the audit
functions still exist, are callable, and accept the documented signature.

---

## 3. The 3 Historical Rounds

| Round | Function | Files Audited | Verdict | Findings | Fixed? |
|------:|----------|---------------|---------|---------:|:------:|
| 1 | `audit_memory_palace` | memory_palace.py + test_memory_palace.py + WAVE2_MEMORY_PALACE.md | CONDITIONAL | 8 | 3 (N+1, atomicity, exponential formula) — shipped in `fc1384b` |
| 2 | `audit_full_wave2` | memory_palace.py + soul_transfer.py + r1_audit_client.py + test_soul_transfer.py | FAIL | 6 | 1 of 6 (#4) — partial in `8cd60b9` |
| 3 | `audit_full_wave2_stack` | turn_system.py + etl_service.py + soul_transfer.py + memory_palace.py + r1_audit_client.py | PASS | 4 (informational) | n/a — informational only |

**Round 1** was run with an M3 mock (Phase A was too early for a real
local LLM). **Round 2** was the first real R1 audit and surfaced the
Soul Transfer atomicity contract. **Round 3** was the stack-level review
that cleared the framework for Phase B/C work.

The verdict counts above are recorded in
`docs/PHASE_ROADMAP.md` (Phase B section) and in the `context` field of
each Phase D audit function.

---

## 4. The 4 Phase D Audit Functions

Use the right audit function for the right subagent. **Always run the
matching audit BEFORE the subagent starts work** so the subagent can
incorporate R1's concerns into its plan.

| Function | Phase | Files Audited | When to Use |
|----------|------:|---------------|-------------|
| `audit_phase_d1_merge` | D1 | memory_palace.py + memory_palace_integration.py + test_memory_palace.py + test_memory_palace_integration.py | Before deciding the merge strategy (keep-both vs single-module-with-two-classes) or starting the migration of the 30 existing tests. |
| `audit_phase_d3_repository` | D3 | memory_palace_integration.py + persistence_pg.py + vector_store.py + WAVE2_MEMORY_PALACE.md | Before extracting the `MemoryRepository` interface and choosing the embedding-model load pattern. |
| `audit_phase_d5_pi5_deploy` | ~~D5~~ **DEPRECATED** | Pi5 deploy cancelled 2026-06-05. Function kept for historical reference, do not invoke. |n.py + r1_audit_client.py | Before deploying to kitahim.ddns.net (Pi5, 8GB RAM, no GPU). Verifies RAM budget, R1-14B absence, Postgres tradeoff, Caddy/Cloudflare-Tunnel topology. |
| `audit_phase_d6_llm_client` | D6 | llm_client.py + r1_audit_client.py + api/action.py + turn_system.py | Before replacing the existing MiniMax-M3 client (or adding retry / rate-limit / cache). Verifies retry contract, 429 handling, cache placement, and M3-specific quirks (thinking mode, 1M context). |

Each function carries a `context` block that includes the shipped
commits, the test count at audit time, and pointers to the previous
rounds' findings — so R1 can read its own history.

---

## 5. Adding a New Audit Function

If a future phase (E, F, ...) needs its own audit, follow this 5-step
procedure. **Do not factor out a common helper** — keep the functions
parallel and grep-able.

### Step 1 — read the phase brief and identify 3-4 specific concerns

Generic concerns ("is this code good?") get generic answers. Specific
concerns ("does the `forget()` race-safety hold under concurrent God
Agent ETL?") get actionable findings. Aim for 3-4 concerns that are
named, cited, and have a clear pass/fail criterion.

### Step 2 — pick the target files

Aim for **4 files**: 2-3 production files + 1 design-doc source of
truth. If the design doc doesn't exist, cite the relevant section of
`docs/PHASE_ROADMAP.md` instead. Never cite only one file — R1 needs
context to push back on.

### Step 3 — write the function (append to `backend/r1_audit_client.py`)

```python
async def audit_phase_eN_short_name(repo_root: str = ".") -> Dict[str, Any]:
    """
    Real R1 audit for Phase EN — <one-line scope>.

    Phase EN scope: <2-3 sentence description>.

    Verifies:
    1. <concern 1>
    2. <concern 2>
    3. <concern 3>
    4. <concern 4>
    """
    client = R1AuditClient()
    try:
        await client.verify_endpoint()
        result = await client.audit(
            target_files=[
                f"{repo_root}/backend/<file_1>.py",
                f"{repo_root}/backend/<file_2>.py",
                f"{repo_root}/docs/<design_doc>.md",
            ],
            concerns=[
                "<concern 1, with file:line or behavior reference>",
                "<concern 2, ...>",
                "<concern 3, ...>",
                "<concern 4, ...>",
            ],
            context={
                "phase": "EN",
                "shipped_commits": ["<sha> (<description>)", ...],
                "test_count": <N>,
                "previous_r1_audits": ["Round N: <verdict>, <N> findings"],
            },
        )
        return result
    finally:
        await client.close()
```

### Step 4 — add a 1-row entry to §4 of this playbook

Document the function, the files it audits, and when to use it. Future
contributors will grep this file for `audit_phase_*`.

### Step 5 — add a 1-test entry to `backend/tests/test_r1_audit_phase_d.py`

Either add a new test (`test_eN_function_exists_and_callable`) or
extend the existing parametrized loop in `test_all_d_functions_have_docstrings`
and `test_d_functions_take_repo_root_kwarg`. The test must be
network-free so it runs in CI without LM Studio.

---

## 6. Interpreting Audit Results

### 6.1 Verdict meanings

| Verdict | Meaning | Action |
|---------|---------|--------|
| **PASS** | R1 found no CRITICAL or HIGH findings. The code is safe to ship as-is. | Proceed. Optionally re-audit after any post-merge changes. |
| **CONDITIONAL** | R1 found MEDIUM/LOW findings but no blockers. Code is shippable; the findings are improvements. | Proceed, but file the findings as follow-up issues. Mention them in the PR description. |
| **FAIL** | R1 found at least one CRITICAL or HIGH finding. The code is **not** safe to ship. | Stop. Address each HIGH/CRITICAL finding. Re-run audit. The pre-merge audit cost is much lower than the post-merge fix cost. |
| **BLOCK** | R1 found a blocker that is **architectural** (e.g. fundamental data-model mismatch, unshippable assumption, missing piece of the design doc). | Stop. Escalate to the main session. Phase scope may need to be revised. |

### 6.2 Severity levels

| Severity | Meaning | Example |
|----------|---------|---------|
| **CRITICAL** | Data corruption, security hole, race condition that drops state under load. | `forget()` not atomic under concurrent God Agent ETL. |
| **HIGH** | Performance cliff, missing test coverage on a critical path, leaked internal state. | N+1 SQLite connection on `apply_decay()`. |
| **MEDIUM** | Code smell, missing error context, suboptimal pattern that can be fixed in a follow-up PR. | `datetime.utcnow()` used instead of `datetime.now(timezone.utc)`. |
| **LOW** | Style nit, naming inconsistency, missing comment. | Class docstring missing a "Why this exists" paragraph. |
| **INFO** | Observation or alternative-pattern suggestion, not a defect. | "Consider using a repository pattern here; Phase D3 plans to add one." |

### 6.3 Acting on findings

For each CRITICAL/HIGH finding, the post-audit workflow is:

1. **Cite**: copy the `evidence` field (must already be a `file:line`
   reference per the audit prompt's required format).
2. **Plan**: write a 1-2 line fix per finding.
3. **Fix**: apply the fix, add a regression test.
4. **Re-audit**: re-run the same audit function. The new run should
   return the same findings **except** the fixed one, plus any new
   findings the fix introduced (rare, but possible — re-audits surface
   regressions).

---

## 7. Local LM Studio Setup

### 7.1 Install + load the model

1. Download LM Studio from `https://lmstudio.ai/` (free, runs on CPU/GPU).
2. Search for `deepseek-r1-distill-qwen-14b` in the LM Studio model hub.
3. Download the GGUF variant matching your hardware (Q4_K_M is a good
   8GB-RAM balance; Q5_K_M for 12GB+).
4. Load the model in the LM Studio UI (left sidebar → Chat → select the
   model → wait for "Model loaded").

### 7.2 Enable the API server

1. LM Studio → **Developer** tab (left sidebar).
2. Find **Local Server** section.
3. Toggle **Enable Local Server** ON.
4. Confirm port is **1234**.
5. Verify with:

   ```bash
   curl http://127.0.0.1:1234/v1/models
   ```

   You should see `deepseek-r1-distill-qwen-14b` in the `data[].id` list.

### 7.3 Smoke-test the audit infra

```bash
.venv\Scripts\python.exe -c "
import asyncio
from backend.r1_audit_client import audit_memory_palace
result = asyncio.run(audit_memory_palace(repo_root='.'))
print('verdict:', result['verdict'])
"
```

If the model isn't loaded, you'll get a clear
`RuntimeError: Model 'deepseek-r1-distill-qwen-14b' not loaded in LM Studio.`
— not a silent fallback. This is intentional (fail-closed).

### 7.4 Hardware notes

- R1-14B Q4_K_M: ~9GB VRAM. Requires a discrete GPU.
- R1-14B Q4_K_M on CPU (no GPU): ~30s per audit. Tolerable for ad-hoc
  use, painful for CI.
- For Pi5 (Phase D5 ~~Planned~~ **REMOVED 2026-06-05**): R1-14B cannot run on Pi5 (8GB RAM, no GPU). User decision: deploy scope is local-only. The `audit_phase_d5_pi5_deploy` function is deprecated; do not invoke.`
  for the fail-gracefully path.

---

## 8. CI Integration

The 6 lightweight tests in `backend/tests/test_r1_audit_phase_d.py` are
network-free and safe for CI. Add them to your CI pipeline as:

```yaml
# GitHub Actions example (.github/workflows/test.yml)
- name: Run audit-function smoke tests
  run: .venv\Scripts\python.exe -m pytest backend/tests/test_r1_audit_phase_d.py -q
```

Full audit runs (which call LM Studio) are **not** recommended in CI:
they're slow (30s-5min per call), require a GPU runner, and produce
flaky results as the model's exact outputs drift between versions. Run
them locally before merging, not on every commit.

If you want CI-grade architecture review, consider:

- A nightly job that runs `audit_full_wave2_stack` against the latest
  main and posts a summary comment to a tracking issue.
- A pre-merge job that runs the matching `audit_phase_d*` function
  only when files in `backend/r1_audit_client.py` or the audited
  target files change.

---

## 9. Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: Cannot reach LM Studio at http://127.0.0.1:1234/v1` | LM Studio API server not enabled. | §7.2 — toggle **Enable Local Server** in Developer tab. |
| `RuntimeError: Model 'deepseek-r1-distill-qwen-14b' not loaded` | Model not loaded, or a different model is active. | §7.1 — load the exact model name that matches `R1_MODEL` env var (default `deepseek-r1-distill-qwen-14b`). |
| `json.JSONDecodeError: Expecting value: line 1 column 1` in `result["raw_response"]` | R1 returned prose-only output (no JSON block). | This is non-fatal — the client catches it and returns `verdict="UNKNOWN"`. Inspect `result["raw_response"]` and re-prompt R1 with a stricter system prompt if it persists. |
| `httpx.ReadTimeout` after 300s | R1 is reasoning for too long (large audit, complex files). | Increase `DEFAULT_TIMEOUT` env var or pass `timeout=600` to `R1AuditClient(...)`. Truncating the audited files (set `R1_MAX_LINES=50`) often helps. |
| Audit returns 0 findings despite obvious bugs | The concerns list was too generic. R1 only flags what you ask about. | Tighten the concerns — name the file, the line, and the specific behavior you want verified. |
| Audit takes 10+ minutes and returns truncated JSON | R1 hit its 8K `max_tokens` limit. | Bump `max_tokens` in `R1AuditClient.chat()` to 16000, or split the audit into two smaller calls. |

---

## 10. Future Work

| ID | Scope | Effort | Notes |
|----|-------|-------:|-------|
| **E1** | Expose audits as a FastAPI endpoint (`POST /audit/run`) | ~30 min | Lets the frontend trigger an audit from the UI. Useful for power users who want to verify a fork before deploying. |
| **E2** | Add tenacity-based retry + circuit breaker to `R1AuditClient` | ~1 hr | Mirror the patterns that Phase D6 will add to `llm_client.py`. Keep the audit infra symmetric with the production LLM client. |
| **E3** | Persist audit results to a SQLite table for diff-over-time | ~2 hr | Lets you grep the audit history ("did we have this finding last month?"). Plot verdict trends in a Grafana panel. |
| **E4** | Add a `audit_diff` function that audits only the diff between two git SHAs | ~1 hr | Drastically reduces token cost. Use case: pre-merge audit on a PR vs nightly full-stack audit. |
| **E5** | Swap R1-14B for MiniMax-M3 as a fallback auditor | ~1 hr | M3 has 1M context so it can audit the whole repo in one call. Higher cost per call but fewer calls. |

None of E1-E5 are scheduled; they're here as a backlog for when the
audit infra needs to grow.

---

_Style: technical, dry, like the other docs in `docs/`. Maintained by
the parent agent. Subagents: read §2 + §4 before starting Phase D work,
read §6 after getting a result._

---

## 10. Subagent Finalization Hand-off (M2 Standard)

OpenClaw subagents spawned with `mode="run"` have a **15-minute hard cap**. If a subagent spends most of its budget on code generation, the final regression + summary doc steps can push it over the cap. The subagent's status will be marked `timed out` but **disk work is 100% preserved**.

**The M2 standard** (since 2026-06-05):

| Step | Subagent | Main agent |
|------|----------|------------|
| Implement code per hard constraints | yes | — |
| Write unit tests for new code | yes | — |
| Run **isolated** new test file | yes | — |
| Run **full** regression suite (185 tests at L2-ship; 329 tests as of 2026-06-08) | no | yes |
| Write `PHASE_XXX_SUMMARY.md` | no | yes |
| Git commit + push | no | yes |

**Template (append to every subagent task brief):**

> This subagent should NOT do the following (main agent will do them):
> - Do NOT run the full regression suite (`pytest backend/tests/ -q`)
> - Do NOT write the `PHASE_XXX_SUMMARY.md`
> - Do NOT commit or push to git
>
> This subagent SHOULD do the following (stop here, return control):
> - Implement the code changes per the hard constraints
> - Write the unit tests for the new code
> - Run ONLY the new test file in isolation to confirm green
> - Report 4 fields: (1) files, (2) test count, (3) deviations, (4) summary
>
> Why: OpenClaw subagents have a 15-minute hard cap on `mode="run"`. The full regression suite (185 tests at L2-ship time; 329 tests as of 2026-06-08) takes 10-30 seconds; the summary doc is ~150 lines of writing. Both can push a subagent over the cap. Hand off finalization to main agent for 100% completion rate.

**Postmortem (Phase D2 + D4, 2026-06-05):** Two subagents timed out at 15 min cap. Both had 100% disk work preserved. Main agent did finalization: (a) ran full regression (185/185 PASS at the time), (b) wrote 1 missing summary doc, (c) fixed 1 test assertion bug subagent had introduced. Net result: zero quality loss, subagent wall time within cap, M2 standard adopted for future work.

**Update (2026-06-08):** Test suite has grown to 329 passing + 1 skipped (0 fail). Suite runs in ~10s. Subagent cap still 15 min; M2 hand-off pattern continues to apply.

---

_Last updated: 2026-06-05_
