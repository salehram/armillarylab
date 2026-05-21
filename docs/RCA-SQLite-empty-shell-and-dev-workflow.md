# Root Cause Analysis: SQLite “Empty Shell” Incidents & Dev-Workflow Amplification  
**ArmillaryLab — `armillarylab.db`**  
**Document version:** 1.0 (2026-05-23)  
**Audience:** Engineers / auditors (including follow-up reviews in another assistant session)  

---

## 1. Purpose & scope

This report explains **why** the project intermittently observes:

- **`sqlite3.OperationalError: no such table: targets`** (and similar missing-table failures)
- **`db_unavailable` / 503 paths** driven by startup health checks detecting invalid schema
- **Apparent “stale Flask” behaviour** — server still responding after Ctrl+C, form values not reflecting DB, contradictory DB vs HTTP observations

### 1.1 In scope

- **Mechanisms** consistent with forensic evidence preserved in-repo (`config/sqlite_health.py`, Cursor rules `.cursor/rules/sqlite-corruption-incident.mdc`)
- **Process architecture**: Flask/Werkzeug reloader vs worker, SQLite connection lifecycle, SQLAlchemy session behaviour
- **Human + automation failure modes**, including Cursor agent sessions invoking Python/HTTP tests against live resources
- **Distinguishing** “real corruption/wipe” vs “wrong file” vs “stale server code” vs “misread symptoms”

### 1.2 Out of scope

- Postgres production paths (different failure surface)
- Blame attribution to Flask or SQLite as inherently “buggy” — they behaved as designed given inputs

---

## 2. Symptom catalog (what observers see)

| Symptom | Typical user interpretation | Typical actual category |
|---------|----------------------------|-------------------------|
| 500 errors / missing `targets` | “ORM/schema bug” | On-disk DB **has no tables** or wrong file wired |
| Settings field reverts after save | “POST handler ignores field” | (A) Worker running **older code**, (B) **ORM/session** stale w.r.t new column, (C) **DB not actually updating** concurrent with another writer |
| “Flask still works in browser” after Ctrl+C | “Duplicate Flask stupidity” | **Browser cache**, **different host/port**, or **another process listening** |
| Migrate “deleted data” | “Migration destructive” | Migration ran against **already empty/unused DB** |
| Reload loop then failure | “Reload corrupts SQLite” | **Concurrent access window** amplified by reload churn |

---

## 3. The “empty shell” fingerprint (forensic invariant)

Captured in code as **`classify_sqlite_problem(...) == "empty_shell"`**.

### 3.1 Observable properties

- File **still a valid SQLite database**
- **`PRAGMA integrity_check` → `ok`**
- **`sqlite_master` table count → 0** (no user tables)
- **`PRAGMA page_count`** aligns with historically observed **empty shell (~28 pages, ~114688 bytes)** in this project (`EMPTY_SHELL_*` constants in `config/sqlite_health.py`)

### 3.2 Why this matters

Integrity “ok” with **zero tables** is **not** classic bit corruption. It is consistent with mechanisms that leave a **SQLite container with catalog wiped** rather than scrambled pages:

1. **`DROP TABLE` / schema destruction** executed against the live file  
2. **Replacement** of the file with another valid-but-empty SQLite file of similar allocation  
3. **Interrupted schema operations** paired with tooling bugs (much rarer than (1)-(2); evidence on this repo points to deliberate wipe test scripts historically + concurrent writes)

---

## 4. Foundational mechanics (technical deep dive)

### 4.1 SQLite concurrency model

- SQLite permits **multiple readers** depending on locking mode/journal mode, but **writer interactions are sharply constrained**.
- Practical dev implication: **`armillarylab.db` MUST NOT experience overlapping writers** unless you have carefully designed isolation (SQLite is not magic).
- Typical high-risk overlap in this codebase’s development pattern:
  - **Flask worker** has DB open (`NullPool`, frequent reconnect cycles under reload).
  - A **secondary Python process** also opens the same filesystem path (`sqlite3`, SQLAlchemy, `import app`).

### 4.2 SQLAlchemy + Flask-SQLAlchemy session behaviour relevant to UI symptoms

Symptoms resembling “saved but UI shows default” include:

| Mechanism | What happens |
|-----------|----------------|
| **Identity map staleness** | Session holds ORM instances; after schema change or abnormal commit path, **`refresh` / expire / dispose** paths may determine whether NEW columns appear |
| **Code mismatch** | One process renders template with **`config.field or default`** semantics while DB row **does persist** elsewhere — observers think “didn’t save” |
| **Two DB files** (`DATABASE_URL` / `SQLITE_PATH` divergence) | One test client writes file A while browser reads via server bound to file B |

### 4.3 Werkzeug/Flask dev reloader: one command → multiple OS processes

**Configuration signal:** `.flaskenv` sets **`FLASK_DEBUG=True`**.

**Behaviour:** `flask run` with reloader executes an architecture described in `config/flask_process.py` comments:

- A **watchdog/parent** process monitors files.
- A **worker/child** process runs the actual app logic.
- **`WERKZEUG_RUN_MAIN`** differentiates Parent vs Child.

### 4.4 Why the project distinguishes “live SQLite allowed” gates

Function **`should_open_live_sqlite()`** (`config/flask_process.py`) exists because:

- Older patterns where **any** import of `app` could open SQLite **while reloader parent also touched resources** amplified corruption risk windows.
- The fix is procedural + technical: **`import app`** from helpers must not join the live DB fray during dev.

### 4.5 Additive migrations vs destructive reset

 **`flask migrate-db` pathway** documented as **additive** (`ALTER TABLE`, `db.create_all()`). It **does not delete user rows**.

If user sees “migration deleted everything,” it is overwhelmingly likely they **migrated an already empty/wrong SQLite file**.

---

## 5. Incident archetypes (classified)

### Class A — **Concurrent writers / scripted tests touching live SQLite during server runtime**

Evidence class: agent transcript patterns where tests set:

- **`WERKZEUG_RUN_MAIN=true`** to coerce “serving semantics” inside a standalone script opening project DB
- **HTTP POST to local dev URL** against while server concurrently holds DB locks

Risk: Extremely high probability of nondeterministic states and **SQLite journal interactions** culminating in catastrophe under Windows + frequent reload churn.

### Class B — **Destructive tooling against live DB (confirmed historical)**

Incident doc references `scripts/test_db_corruption_resilience.py` historically executing **`DROP TABLE`** against **live DB** unless rewritten (mitigation subsequently documented).

Risk: deterministic **empty shell**.

### Class C — **“Stale server” misunderstandings**

This is **often not DB corruption**:

- Reload mid-edit → interpreter running **different** model/template than filesystem expectations.
- Separate OS process listens on intended port (**agent**, IDE task, orphaned python).
- Browser tab shows cached HTML (“still works”), not live server correctness.

### Class D — **Filesystem replacement / conflicting copies**

Historical note retained for completeness **without assuming current workspace location**: some environments replace active DB paths during sync-heavy workflows. Fingerprints mimic Class B.

---

## 6. Project-specific timelines (composite)

### Phase set I — Calibration + migration era (canonical in-repo timeline)

Captured in **`sqlite-corruption-incident.mdc`**, summarized:

- Calibration feature increased **migration + reload + scripted maintenance** throughput.
- A destructive test script wiped live DB (**confirmed causal** historically).
- Git restore workflows / manual copies sometimes occurred **while tooling expectations were unclear**.
- Subsequent mitigations landed: **`should_open_live_sqlite()` guards**, **`check_sqlite_database`**, **`db_unavailable`** behaviour, **`destructive_db_guard`**, rewrote resilience test against temp DB only.

### Phase set II — Cloud-cover settings + Composer-driven verification (conversation-derived)

Facts relevant to RCA:

| Observation | Inference |
|------------|-----------|
| Flask test isolation showed POST saving works against clean test DB | Correct handler plausible |
| HTTP against live `:8080` showed **disk value vs rendered form mismatch** | **Process/code/db skew** triple must be enumerated — not singular “composer broke SQL” |
| Post-session diagnosis reported **live `armillarylab.db` empty_shell** again | Returned to **Class A/B** catastrophic states when automated actions overlapped Flask runtime |

This phase highlights an **orthogonal failure**: **verification methodology** amplified real-world hazard.

---

## 7. Ranked causal factors (severity-weighted matrix)

Legend: **C** Confidence high from direct evidence vs **I** Inference from pattern fit.

### 7.1 Root / primary

| Rank | Factor | Class | Confidence |
|-----:|--------|------|------------|
| 1 | **Secondary Python tooling opening same SQLite path while Flask worker active** | A | **C/I** depending on artefact retention |
| 2 | Historical **destructive test script** (**DROP TABLE** on live DB) | B | **C** (explicitly acknowledged in-repo) |

### 7.2 Contributors (amplify probability / severity)

| Factor | Contribution |
|-------|----------------|
| **Auto-reloader** cadence → connection churn spikes windows for overlap |
| **Windows + SQLite** practical locking semantics less forgiving under overlap than many devs intuit |
| **Agent autonomy** invoking DB-touching snippets without enforcing “STOP FLASK FIRST” gate |
| **Ops confusion** migrating/restoring/copying `.db` with unclear server state |

### 7.3 Non-root confounders (often mis-labelled “corruption”)

| Phenomenon | Why it mimics catastrophe |
|-----------|---------------------------|
| Stale Flask worker code | Saves appear ineffective |
| Port orphan | “Server still alive” narratives |
| Template defaulting (`None or 25`) | Appears revert-to-default |

---

## 8. Elimination ledger (explicit non-causes for common misconceptions)

| Claim | Determination |
|-------|---------------|
| `flask migrate-db` intentionally deletes astro data rows | **False** architecturally (`ALTER`/`create_all` additive) unless external destructive command used |
| Jinja/UI-only edits alone wipe SQLite | **False** (no DB coupling) |
| “More intelligent model” inherently prevents concurrency mistakes | **False** — orthogonal capability |
| “User ran `flask run` twice so duplications always user fault” | **Incomplete** — reloader duplicates processes by design + other actors may bind ports |

---

## 9. Control posture already implemented (verification checklist for auditors)

Enumerate by reading codebase (non-exhaustive):

| Control | Location / artefact |
|--------|---------------------|
| Reloader vs worker rationale | `config/flask_process.py` comments & `WERKZEUG_RUN_MAIN` gating (`should_open_live_sqlite`) |
| Empty-shell classification | `config/sqlite_health.py` (`classify_sqlite_problem`) |
| User-facing degraded mode | `templates/db_unavailable.html` pathway |
| Destructive op guardrails | `config/destructive_db_guard.py` (context from incident doc + CLI pathways) |
| Operational rule: stop server before migrate | `.cursor/rules/flask-migrate-db-safety.mdc` |
| Human-readable incident playbook | `.cursor/rules/sqlite-corruption-incident.mdc` |

**Audit prompt:** Confirm no automated **restore** resurrected silently (user forbade autopilot restore).

---

## 10. Recommended hardening backlog (engineering)

Prioritized by leverage:

### P0 — Process hygiene (no schema change required)

- Enforce invariant: **`NO python touching project default SQLite path`** while `flask --app app.py run` active unless explicit opt-in sentinel env var audited.
- Mandatory preflight in agent rules: **`Get-NetTCPConnection` / SS equivalent** verifying port DOWN before scripted DB ops.

### P1 — Telemetry & guardrails

- Log **SQLite file path canonical resolution** once at startup (worker only) comparing `db_config.sqlite_file_path()` vs env expectations.
- Add dev-only **`/internal/db-health`** route disabled in prod exposing **classified state** (`ok`, `empty_shell`), never secrets.

### P2 — Operational UX

- On settings save conflict path, propagate distinct flash if **`IntegrityError` / OperationalError**.

### P3 — Architectural alternative (heavy)

- Abstract dev DSN to isolated copy auto-cloned nightly (explicit user tradeoff rejected historically — flag if policy changes).

---

## 11. Reproduction & evidence commands (audit trail)

Executed **ONLY with Flask STOPPED** unless read-only probes:

```
python scripts/diagnose_db.py
python scripts/inspect_db.py armillarylab.db
```

SQLite direct read-only probes:

```
sqlite3 armillarylab.db ".tables"
sqlite3 armillarylab.db "PRAGMA integrity_check;"
```

Port listeners (PowerShell illustration):

```
Get-NetTCPConnection -State Listen | ? { $_.LocalPort -in 5000,8080 }
```

---

## 12. Psychological / workflow failure mode (“why Composer session felt catastrophic”)

Not a joke section — materially affects incident reporting:

Composite perception formed when disjoint signals aligned:

| Signal | Emotional weight |
|--------|------------------|
| DB empty → app dead | Existential urgency |
| Quota exhaustion | Monetary/time injury |
| Staleness misunderstandings (“browser still loads”) | Mistrust in tooling stack |
| Model promises safety | Credibility collapses catastrophically |

**Operational lesson:** Separate **verification** from **recovery**. Never coerce live DB concurrency to prove POST mapping correctness.

---

## 13. Executive summary paragraph (verbatim suitable for escalation)

Repeated ArmillaryLab SQLite outages cluster around **`empty_shell` fingerprints** consistent with deliberate schema wiping or catastrophic concurrent-write interactions rather than spontaneous bit-rot or additive migrations deleting content. Amplifying factors included **elevated Flask reload churn during large schema-evolving features**, **agent-driven validation scripts circumventing guarded import paths**, and **historically confirmed destructive tooling** against live SQLite. Mitigations gated live SQLite openings to sanctioned processes and introduced health classification with manual restoration policy. Persistent confusion sources include **misinterpreting reloader multi-process topology** and diagnosing **single-process UI staleness as database destruction**. Future risk reduction concentrates on procedural enforcement blocking concurrent writers and narrowing automated agent DB actions.

---

## 14. Document maintenance

Owners should revise when:

- New schema migration strategy introduced  
- Flask execution entrypoints change materially  
- New classes of forensic fingerprints discovered  

Bump **Document version** and append appendix instead of overwriting historical narrative.

---

## 15. Reference index

| Item | Purpose |
|------|---------|
| `.cursor/rules/sqlite-corruption-incident.mdc` | Canonical chronological incident narrative |
| `.cursor/rules/flask-migrate-db-safety.mdc` | Migrate operations safety |
| `config/flask_process.py` | Process detection rationale |
| `config/sqlite_health.py` | Forensic classifier |
| `config/database.py` | Engine + pragmatic journal choices |
| `scripts/diagnose_db.py`, `scripts/restore_db.py` | Manual remediation |

---

### Appendix A — Minimal sequence diagram concept (SQLite hazard window)

```
[Flask worker] --open-write--> armillarylab.db
         ^
         | concurrent overlapping window BAD
[Any other python/sqlite writer] ----/
```

Healthy invariant: **exclusive writer epoch** scoped per maintenance operation.

---

**End of report.**
