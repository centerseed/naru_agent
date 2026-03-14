# /ship — Automated Feature Shipping Orchestrator

**Usage:** `/ship <feature-name>`

**Example:** `/ship knowledge-graph-store`

**Prerequisite:** A spec must exist at `.claude/specs/<feature-name>/spec.md` (created by `/plan` or `/spec`).

---

## Project Config

> When porting to another project, only modify this section.

```yaml
VERIFY_PYTHON: cd /Users/wubaizong/接案/naru_agent && pytest tests/unit/ -v --tb=short
VERIFY_JS: cd /Users/wubaizong/接案/naru_agent/js && npm run lint && npm run test && npm run build

DB_SCHEMA_PATH: none

DEPLOY_SCRIPTS:
  python: none
  js: none
DEPLOY_ORDER: []

ARCHITECTURE_RULES: |
  - SDK library — Python and TypeScript dual-port, no server, no DB
  - Python: naru_agent/ is the source of truth; tests/unit/ for fast unit tests; tests/integration/ for external-service tests (marked with @pytest.mark.integration)
  - JS: js/src/ is source; mirrors Python API surface; tests in js/tests/
  - Abstraction layers: base interfaces (BaseKnowledgeStore, BaseMemoryManager, etc.) → concrete implementations → optional adapters
  - New optional features MUST be in optional-dep extras (pyproject.toml [project.optional-dependencies]) to keep core lightweight
  - Never add mandatory heavy deps (torch, transformers, etc.) to core dependencies
  - No circular imports — base classes never import implementations
  - Integration tests must be marked @pytest.mark.integration and must not run in CI without explicit flag

E2E_SKILLS:
  python_integration: cd /Users/wubaizong/接案/naru_agent && pytest tests/integration/ -v --tb=short -m integration
  js_integration: cd /Users/wubaizong/接案/naru_agent/js && npm run test:integration

DEP_INSTALL:
  python: cd /Users/wubaizong/接案/naru_agent && pip install -e ".[dev,chromadb,graph,embeddings,redis]"
  js: cd /Users/wubaizong/接案/naru_agent/js && npm install
```

---

## Orchestration Flow

```
Phase 1: Setup → Phase 2: Implement → Phase 3: Review → Phase 4: Verify
    → Phase 5: Fix Loop (if needed) → Phase 6: E2E → Phase 7: Report
```

### Context Discipline Rule

The orchestrator MUST NOT read raw test output, full diffs, or verbose logs directly.
Every subagent MUST write a structured summary file. The orchestrator reads ONLY summary/verdict files.

Subagent output files (all under `.claude/specs/<feature-name>/`):
- `review-brief.md` — Phase 2 implementation summary
- `review-report.md` — Phase 3 PASS/NEEDS_REWORK verdict
- `fix-list.md` — Phase 3/5 blocking issues
- `verify-result.md` — Phase 4/5 structured pass/fail table
- `e2e-result.md` — Phase 6 E2E pass/fail table
- `ship-report.md` — Phase 7 final report

---

## Phase 1: Setup

1. Read `.claude/specs/<feature-name>/spec.md`. If it doesn't exist, STOP and tell the user to run `/plan <feature-name>` first.
2. Parse spec metadata: `affected`, `db_migration`, `deploy_required`.
3. Create a git worktree for isolation:
   ```bash
   git worktree add .claude/worktrees/<feature-name> -b ship/<feature-name>
   ```
4. Install dependencies in worktree for each affected platform (see `DEP_INSTALL` in Project Config).
5. If `db_migration: true`, snapshot the DB schema:
   ```bash
   cp <DB_SCHEMA_PATH> /tmp/db-schema-before
   ```
6. Copy the spec file into the worktree for subagent access.

---

## Phase 2: Implementation (Subagent in Worktree)

Launch an **implementation subagent** (Sonnet model, worktree isolation) with this mandate:

### Subagent Instructions

```
You are an implementation engineer working in a git worktree.
Working Directory: .claude/worktrees/<feature-name>

Read the spec at .claude/specs/<feature-name>/spec.md — this is your contract.

## ━━━ Phase 0: Codebase-First Exploration (MANDATORY before any code) ━━━

Never assume. Never invent. Always verify with search tools first.

1. **Read the affected area** — open and read every file listed in spec's "Files Expected to Change" + their neighbors
2. **Find your reference implementation** — search for the closest existing feature to what you're building. This is your north star for style, patterns, and naming.
3. **Grep before creating** — before writing ANY new function, class, type, or utility:
   - Search the entire codebase for existing implementations: `grep -r "functionName\|similar_keyword"`
   - If something similar exists, REUSE it. If it needs extension, EXTEND it. Only create new if nothing exists.
4. **Learn the naming conventions** — read 3-5 existing files in the same layer/module to extract:
   - File naming pattern (snake_case.py? What suffix — `_store.py`, `_manager.py`, `_adapter.py`?)
   - Export naming pattern (Python: `__all__`? TypeScript: named exports? barrel index.ts?)
   - Variable/function naming (snake_case Python / camelCase TS? What prefixes — `get_`, `find_`, `create_`, `handle_`?)
   - Class naming (PascalCase? Base prefix for abstracts? Suffix like `Store`, `Manager`, `Adapter`?)
   - Test file naming (Python: `test_*.py`; JS: `*.test.ts` co-located or separate tests/ dir?)
5. **Map the dependency chain** — for each file you'll touch, understand what imports it and what it imports. Never break existing consumers.

OUTPUT of Phase 0: Write a brief note (in your working memory, not a file) listing:
- Reference implementation file path
- Naming conventions discovered
- Existing utilities you'll reuse
- Files you'll create vs. edit

## ━━━ Phase 1: TDD Implementation (per AC, strict order) ━━━

### The Iron Law: RED → GREEN → REFACTOR
For EACH acceptance criterion, in strict order:
1. **RED** — Write a FAILING test. Run it. Watch it fail. If it passes immediately, your test is wrong — delete and rewrite.
2. **GREEN** — Write the MINIMAL production code to make it pass. Run it. Confirm green.
3. **REFACTOR** — Clean up while keeping green. Run tests again.

NO production code without a failing test first. No exceptions.
"I'll add tests later" = NO. "It's too simple to test" = NO. "Manual testing is sufficient" = NO.

### Test Quality Rules

**Mutation Resistance (MOST IMPORTANT)**:
- Every assertion must BREAK if someone flips a condition (`>` → `>=`), changes a constant, or removes a line
- `assert result is not None` / `assert result` is NEVER sufficient — assert specific values, counts, state changes
- If code checks `> 0`, you MUST test with -1, 0, and 1
- If code has a limit of N, test N-1, N, and N+1
- If a method updates multiple fields, assert ALL of them
- Ask yourself: "If I delete line X of production code, does any test fail?" — if no, add one

**No Tautological Mocks**:
- Mock ONLY external I/O (network, LLM API calls, filesystem) — everything else runs real
- NEVER: mock returns X → assert result is X (you tested the mock, not the code)
- NEVER: `mock.assert_called()` alone — also test the EFFECT of the call
- NEVER: add test-only methods to production code
- If your test would still pass with the function body replaced by `return mock_value`, it tests nothing

**Assertion Density**:
- Minimum 3 meaningful assertions per test (return value + side effects + state)
- Assert the THEN condition from the AC with specific values, not just "no exception raised"

**Mandatory Edge Cases** (at least one per AC):
- None, empty string, empty list, zero
- Boundary values (off-by-one)
- Duplicate/concurrent operations
- Unauthorized or missing inputs

**Test Naming**: `test_should_<expected_behavior>_when_<condition>` or descriptive GIVEN/WHEN/THEN docstrings

**Max 10 tests per file**: Focus on high-value behavioral tests covering real user flows. 3 excellent tests > 15 shallow ones.

**Fix Code, Not Tests**: If a test fails during GREEN phase, the implementation is wrong. Never weaken a test to make it pass.

### Anti-Patterns (Immediate Red Flags)
- Test passes immediately on RED → proves nothing, DELETE and rewrite
- Mock returns expected value, test asserts it back → tautology, REWRITE
- `assert_called()` without verifying call arguments AND effects → INCOMPLETE
- Testing private/internal methods instead of public behavior → WRONG LEVEL
- Copy-pasted test differing by one value → PARAMETERIZE instead
- 40+ tests that bury real user flows in noise → CUT to 10 high-value ones

## ━━━ Phase 2: Implementation Discipline ━━━

### DRY: Search Before You Create
- Before creating a new file → glob/grep for similar files. Does one already exist?
- Before creating a new function → search for existing functions with similar names or purposes
- Before creating a new base class/interface → check if a domain abstraction already models this concept
- Before adding a new dependency → check if an existing optional dep already covers the need
- If you find yourself copying code from another file → extract a shared utility instead

### Consistency: Follow, Don't Invent
- Match the EXACT patterns from your Phase 0 reference implementation
- Same import ordering style, same error handling pattern, same logging approach
- If existing code uses `async def` for LLM calls, don't add sync variants unless spec requires it
- If existing code uses `BaseXxx` abstract classes with `@abstractmethod`, follow the same pattern
- If existing tests use `pytest.mark.asyncio` + `AsyncMock`, don't switch to `unittest.mock`
- Match what's there

### Simplicity: YAGNI
- Solve each AC in order — do NOT jump ahead or parallelize
- Write the simplest code that passes the test — no speculative features
- Don't add configurability, flags, or options not in the spec
- Don't create abstractions for things that only happen once
- Prefer editing existing files over creating new ones

### Optional Dependencies Rule
- If new code requires a new library, it MUST go in `[project.optional-dependencies]` in pyproject.toml
- Never add heavy dependencies (networkx, sentence-transformers, etc.) to core `[project.dependencies]`
- Guard imports with try/except: `try: import foo; HAS_FOO = True except ImportError: HAS_FOO = False`

### Error Handling
- Every error must be logged or re-raised as a domain exception — never swallow silently
- Never `except Exception: pass` — at minimum log it
- For async operations: always handle rejection/exceptions

### Boundaries: Don't Touch What You Shouldn't
- Do NOT add comments, docstrings, or type annotations to code you didn't write
- Do NOT refactor existing code unless it's blocking your implementation
- Do NOT "improve" code quality of files outside your spec scope

## ━━━ PAUSE Gates ━━━

If you encounter any of these, output the exact marker and STOP:
- [PAUSE:DB_MIGRATION] <description of schema change needed>
- [PAUSE:DATA_DELETE] <description of data that would be deleted>

## ━━━ Architecture Rules ━━━

- SDK library: no server, no DB, no mandatory heavy deps
- Base interfaces (BaseKnowledgeStore, BaseMemoryManager, etc.) are in naru_agent/knowledge/, naru_agent/memory/, etc.
- Concrete implementations always import from base interfaces, never the other way around
- Optional extras in pyproject.toml keep core install lightweight
- Integration tests marked @pytest.mark.integration — do not break these markers

## ━━━ Adversarial Self-Review (before declaring done) ━━━

Before running final verification, attack your own code:
1. **Import guard** — if new dep is optional, is it guarded with try/except ImportError?
2. **Null/empty edges** — what if the input is None, empty string, empty list, zero?
3. **Async safety** — are all async methods awaited? No missing `await`?
4. **Regression** — did you accidentally change behavior of existing features?
5. **Naming audit** — do all your new names match the conventions you discovered in Phase 0?

If you find issues, fix them before proceeding.

## ━━━ Verification (MANDATORY — no claims without evidence) ━━━

Run the verification commands for each affected platform (from Project Config):
- Python changes: `pytest tests/unit/ -v --tb=short`
- JS changes: `npm run lint && npm run test && npm run build` (from js/ directory)

Rules:
- Run the FULL command. Read the FULL output. Check exit codes.
- "Should work" / "looks correct" / "probably passes" = NOT VERIFIED. Run it.
- If verification fails, fix the issue and re-run. Do NOT declare done with failing verification.
- Copy-paste the actual terminal output as evidence.

## ━━━ Output ━━━

When done, write .claude/specs/<feature-name>/review-brief.md containing:
- Implementation approach summary
- Reference implementation used (which existing feature you followed)
- Naming conventions followed (with examples)
- Existing utilities reused (list them)
- AC status (checked/unchecked with explanation)
- Key decisions made
- Changed files list (new files vs. edited files, clearly marked)
- Optional dep handling (if new deps added, confirm they're in extras not core)
- Adversarial self-review findings (what you checked, what you found)
- Verification command results (copy-paste actual terminal output)
```

### PAUSE Gate Handling

If the subagent outputs `[PAUSE:DB_MIGRATION]` or `[PAUSE:DATA_DELETE]`:
1. Present the details to the user
2. Wait for explicit confirmation before continuing
3. If user denies, adjust approach or STOP

---

## Phase 3: Review (Spec Review + /simplify)

Two parallel review tracks:

### Track A — Spec Reviewer (Subagent, Sonnet)

Launch a spec review subagent reading from the worktree:

```
Review the implementation against the spec. You are the quality gate — be thorough but fair.

Read:
- .claude/specs/<feature-name>/spec.md
- .claude/specs/<feature-name>/review-brief.md
- git diff in the worktree
- The actual test files (not just the diff — read the full test to understand coverage)

For each AC in the spec:
1. Is the GIVEN precondition properly set up in the test?
2. Is the WHEN action actually triggered (not mocked away)?
3. Does the test assert the THEN condition specifically (not just "no exception")?
4. Is there at least one error/edge case test per AC?
5. Would the test catch a regression if someone broke this feature later?

Anti-patterns to flag:
- Tests that only check `assert_called()` without verifying the call arguments
- Tests where the mock returns the expected value and the test just checks it back (tautology)
- Missing assertions — test runs but doesn't actually verify anything meaningful
- AC marked as done but no corresponding test exists
- New heavy dep added to core instead of optional extras

Verdict: PASS | NEEDS_REWORK
If NEEDS_REWORK, list each blocking issue as:
- [BLOCK] file:line — description — which AC is affected
```

### Track B — /simplify (Code Quality + Reuse + Efficiency)

Run the `/simplify` skill on the worktree changes. This is a built-in skill that launches **3 parallel review agents**:

1. **Code Reuse Review** — searches codebase for existing utilities that could replace newly written code, flags duplicate functionality, finds inline logic that could use existing helpers
2. **Code Quality Review** — catches redundant state, parameter sprawl, copy-paste with variation, leaky abstractions, stringly-typed code
3. **Efficiency Review** — flags unnecessary work, missed concurrency, hot-path bloat, N+1 patterns, memory leaks, overly broad operations

`/simplify` not only finds issues — **it fixes them directly**. This eliminates one round of fix loop for quality issues.

### Combine Results

After both tracks complete:
- Write `.claude/specs/<feature-name>/review-report.md` combining Spec Reviewer verdict + /simplify summary
- If Spec Reviewer says NEEDS_REWORK, create `.claude/specs/<feature-name>/fix-list.md` with blocking issues
- /simplify fixes are already applied — only Spec Reviewer blocking issues enter the fix loop

---

## Phase 4: Unit Test Verification (Subagent)

Launch a **verification subagent** (Sonnet model, worktree):

```
Working Directory: .claude/worktrees/<feature-name>

Run verification commands for each affected platform (from Project Config).
Run the FULL command. Read the FULL output. Check exit codes.

Write .claude/specs/<feature-name>/verify-result.md:

| Suite | Result | Passed | Failed | First Error (if any) |
|-------|--------|--------|--------|----------------------|

Include exit code for each command.
```

Orchestrator: read ONLY `verify-result.md`. Do NOT read raw test output.

---

## Phase 5: Fix Loop (Subagent per Iteration)

```
iteration = 0
while (has_blocking_issues OR verification_failed) AND iteration < 3:
    iteration++

    Launch **Fix-Review-Verify subagent** (Sonnet, worktree):
        - Read fix-list.md and/or verify-result.md
        - For each [BLOCK] item: read the referenced file in full, understand the context, then fix
        - Fix ONLY the flagged issues — no new features, no refactoring, no "while I'm here" changes
        - If a fix would require architectural changes beyond the scope, flag as ESCALATE
        - Re-run spec review (Track A logic from Phase 3)
        - Re-run verification commands
        - Write updated:
          - fix-list.md (FIXED / ESCALATE / STILL_BROKEN)
          - verify-result.md (structured table)
          - review-report.md (updated verdict)

    Orchestrator reads ONLY verdict from review-report.md + pass/fail from verify-result.md.

if iteration == 3 AND still failing:
    STOP and report to user
    Keep worktree intact for manual intervention
    Print: "Fix loop exhausted after 3 iterations. Worktree preserved at .claude/worktrees/<feature-name>"
```

---

## Phase 6: Merge & E2E Testing

Only reached if Phase 3+4+5 all pass.

### 6a: Merge Worktree

```bash
# From main repo
git merge ship/<feature-name>
# Clean up worktree
git worktree remove .claude/worktrees/<feature-name>
```

### 6b+6c: E2E Testing (Subagent)

Launch an **E2E subagent** (Sonnet model, main repo):

```
Run integration tests for each affected platform from the spec:
- python: cd /Users/wubaizong/接案/naru_agent && pytest tests/integration/ -v --tb=short -m integration
- js: cd /Users/wubaizong/接案/naru_agent/js && npm run test:integration

Note: Integration tests require external services (ChromaDB, mem0, etc.).
If external services are unavailable, mark as SKIPPED (not FAILED) and note in e2e-result.md.

If E2E fails (not SKIPPED), fix in main repo and retry (max 2 iterations).

Write .claude/specs/<feature-name>/e2e-result.md:
| Platform | Result | Tests Run | Tests Passed | Fix Iterations | Notes |
If FAILED after retries, include first failure description (max 10 lines).
```

Orchestrator: read ONLY `e2e-result.md`.

---

## Phase 7: Report

Write `.claude/specs/<feature-name>/ship-report.md`:

```markdown
# Ship Report: <feature-name>

## Result: SUCCESS | PARTIAL | FAILED

## AC Status
- [x] AC1: <name> — PASS (unit + e2e verified)
- [x] AC2: <name> — PASS (unit verified)
- [ ] AC3: <name> — FAILED (reason)

## Test Results
| Suite | Result | Details |
|-------|--------|---------|
| Python unit | PASS | 42 passed, 0 failed |
| JS lint+build | PASS | no type errors |
| JS unit | PASS | 18 passed, 0 failed |
| Python integration | SKIPPED | ChromaDB not available in env |

## Review Verdicts
- Spec Review: PASS
- Code Quality: PASS

## Fix Loop Iterations: N

## Changed Files
- `path/to/file.py` — description
- `js/src/path/to/file.ts` — description

## Optional Deps Added
- python: `[extras_name]` in pyproject.toml — yes/no
- js: new peer/optional dep — yes/no

## Deployment
- Required: no (library — publish to npm/pypi when ready)
```

### Deployment PAUSE Gate

This project is a library (no server deploy). If spec metadata has `deploy_required: true` (e.g., for publishing to npm/pypi):
1. Print the ship report
2. Ask: "Publish to npm/pypi? Confirm version bump?"
3. Only publish after explicit user confirmation

---

## PAUSE Gates Summary

| Trigger | Detection | Action |
|---------|-----------|--------|
| DB Schema Change | spec `db_migration: true` | Ask user to confirm |
| Test Data Deletion | Subagent outputs `[PAUSE:DATA_DELETE]` | Ask user to confirm |
| Deployment/Publish | spec `deploy_required: true` | Ask user at Phase 7 |
| Permission Error | Subagent auth failure | Ask user |
| Fix Loop Exhausted | 3 unit iterations or 2 E2E iterations | STOP, preserve worktree, report |

---

## Model Assignment

| Role | Phase | Model |
|------|-------|-------|
| Orchestrator (this command) | all | Inherits user's session model |
| Implementation subagent | 2 | Sonnet |
| Spec Reviewer | 3 | Sonnet |
| /simplify (Code Quality) | 3 | Built-in skill (launches 3 internal agents) |
| Verification subagent | 4 | Sonnet |
| Fix-Review-Verify subagent | 5 | Sonnet |
| E2E subagent | 6 | Sonnet |

---

## CRITICAL BOUNDARIES

- **Never skip TDD** — every AC must have a failing test before production code
- **Never bypass PAUSE gates** — always wait for user confirmation
- **Never deploy/publish without confirmation** — even if spec says `deploy_required: true`
- **Never exceed fix loop limits** — 3 for unit, 2 for E2E, then STOP
- **Never add heavy deps to core** — all optional features stay in pyproject.toml extras
- **Keep worktree on failure** — user may want to inspect or continue manually
