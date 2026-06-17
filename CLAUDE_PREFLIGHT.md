# Claude Pre-Flight Checklist — LLM_Model3

This file is LLM_Model3's operational rulebook. Read it before giving the operator ANY operational instruction. Apply every relevant rule. No exceptions.

## Provenance and adaptation (ported 2026-06-17)

These rules were ported from `CLAUDE_PREFLIGHT_SWING.md` (the LLM Swing Model's rulebook, itself descended from the legacy intraday `CLAUDE_PREFLIGHT.md`). Each rule was originally written after a specific failure that cost the operator real time and trust. They are corrections, not style preferences.

**What changed in this port (so nothing is silently mis-anchored):**

- **Anchors re-pointed to LLM_Model3:** working directory `C:\trading\LLM_MODEL3`, workstation Godzilla (Albuquerque NM, America/Denver — Mountain Time, not Eastern). Time checks use `TZ=America/Denver`.
- **Partition re-pointed:** LLM_Model3's siblings are `C:\trading\LLM_SWING_MODEL\` (separate active project — no DB/script/code/git crossing) and `C:\trading\LLM model\` (legacy intraday archive — read-only). See Rule 26.
- **VPS / gap-and-go specifics stripped:** `5.161.199.155`, `/opt/trader/app/`, `trader.service`, `trader-prod`, `hetzner_trader`, and Alpaca account numbers (`PA3REQ1LMPKO`, `PA3QAZ941NFN`) belong to other projects. They appear here ONLY as tripwire strings (Rule 26) whose presence in an LLM_Model3 command means a partition check is required.
- **No live deployment exists.** LLM_Model3 is backtest/paper-only by charter. Deployment-specific rules (live HTTP credential leaks, persistent-daemon restart) are kept as forward-looking discipline, generalized away from swing-specific infrastructure, and flagged "applies once LLM_Model3 has a running process / deploy."
- **Trap narratives are preserved** but marked "(historical, prior project)" where they describe swing/intraday/VPS incidents. The principle each encodes still applies to LLM_Model3 work.
- **Project-specific corollaries** are rewritten for LLM_Model3's reality: two independently-backtested engines (A: ETF trend; B: cross-sectional ML), leak-free walk-forward validation, the kill rule in `KILL_RULE.md`, and the rule that the LLM is a feature extractor, never the predictor.

If the operator adds a new failure mode, append it as Rule N+1 with a concrete trap example.

---

## Rule 1: Search before claiming current state about ANY external service

Before telling the operator to click X in service Y, search the web for the current UI of service Y. Services rebrand, reorganize, and rename menus constantly; training data is months stale. Examples that drift: Polygon (rebranded "Massive", kept polygon.io), Anthropic Console billing/settings layout, Alpaca paper-vs-live dashboards, AWS, GitHub. The rule: search "current [service] [task] 2026" before instructing. A direct URL is safer than navigation steps; if giving navigation, give it as one option with a fallback URL.

## Rule 2: Verify pricing AND tier eligibility, both, every time

Pricing tiers and their geographic availability change. Don't assume a plan exists in a region until checked. Known trap: Polygon Stocks Starter is 15-min delayed, not real-time. When recommending a paid tier, search for current price, what's actually included, and region availability. Lock the choice with explicit numbers; don't say "approximately."

## Rule 3: Test every script before pasting it to the operator

Use the sandbox. Before sending any script that modifies config or persistent state: run it on mock inputs, re-parse/re-load the output to confirm validity, test edge cases relevant to the data. Trap (historical): an unquoted-ticker YAML writer parsed `ON` (ON Semiconductor) as boolean `true`. If you generated a regex or a YAML/JSON/TOML mutator, you owe a sandbox test before the operator runs it on real files.

## Rule 4: Know the difference between sandbox/local and the operator's environment

The operator is on Windows PowerShell on Godzilla. Don't hand Linux-style commands, heredocs (`cat <<EOF` — PowerShell has no native heredoc), or assume `~/.ssh/` exists. When introducing a command, say WHERE it runs ("in PowerShell on Godzilla", "in the Godzilla `.venv` REPL", "in the Claude-side sandbox"). Never assume.

## Rule 5: Distinguish "what I think is true" from "what I just verified"

Use explicit markers: "Verified just now via search:", "From training (may be stale):", "Best guess:". If the operator is about to spend money or time on an instruction, they deserve to know which category it falls into.

## Rule 6: When something doesn't work, don't iterate blindly

On a failure: read the actual error, identify the exact failure mode, classify it (typo → retry; missing prerequisite → fix that first; environmental → change approach; bug in my instruction → apologize + fix), state the category, then act. Don't fire off a slightly-different command three times before switching approach.

## Rule 7: Don't lock in defaults silently

If a choice is made early and we pick option A, don't keep using A fifty turns later without rechecking that it still makes sense. Mark default choices as "decision: <X>, revisit before going live" so they resurface at the natural review point. (LLM_Model3 corollary: the ETF universe, the kill-rule thresholds, the cost assumptions, and the walk-forward fold geometry are all "revisit before locking results" defaults.)

## Rule 8: Operator communication preferences

Direct and concise. No filler, no "great question." Less em dashes. Step-by-step with confirmation between steps for technical walk-throughs. Specific to the operator's situation, not generic. Give recommendations, not "it depends." Use analogies for complex ideas. Don't restate the question back.

## Rule 9: [Reserved — no LLM_Model3 deployment yet]

The original slot held gap-and-go VPS operational commands, which do not apply here. LLM_Model3 has no deployment target; it is backtest/paper-only by charter. Reserved for re-issuance if and when an engine clears the kill rule, survives paper, and a deployment is actually planned (a separate, scoped session). Any "let's deploy this" recommendation before that point is premature.

## Rule 10: [Reserved — no LLM_Model3 deployment state yet]

The original slot was a deployment-status snapshot of another fork. LLM_Model3's current status is "P0 scaffold / pre-research." Reserved for re-issuance with LLM_Model3's actual state when paper trading begins (Build sequence P5).

## Rule 11: Label every claim with its testing depth

Never say "tests pass" without the level: `unit-tested` (mocked inputs, single function), `integration-tested` (real API/component, single call), `scale-tested` (real API at production volume), `unverified` (best guess). Trap (historical): 11 unit tests on one function were called "tested at 95% confidence"; the system then broke at 503-ticker scale because real-API scale was never tested. (LLM_Model3 corollary: a backtest that ran on 5 ETFs over 2 years is not "validated"; the bar is the full universe over the full history through the purged/embargoed harness.)

## Rule 12: Before any "ready" claim, list what was NOT tested

Even one item on the not-tested list means confidence is below 95%; state the list. Categories that almost always need disclosure: real-API integration at full scale, end-to-end timing under load, failure-mode behavior (429s, dropped connections, malformed inputs), long-running stability. (LLM_Model3 corollary: before calling an engine result trustworthy, list what the harness did NOT yet guard against — leakage paths not yet audited, costs not yet modeled, regimes not yet in the sample.)

## Rule 13: Verify the calendar date before any temporal claim

Before "yesterday", "this week", "today is X", check the actual system date. Conversations span days; made-up time references erode trust fast. (Mountain Time on Godzilla — see Rule 23.)

## Rule 14: Verification before conclusion

NEVER present a diagnostic claim, root cause, or fix as a conclusion until it has been **tested and verified against real data or output in this session**. Until verified, mark every finding `HYPOTHESIS:` or `UNVERIFIED:` in the message itself, not in a footnote. "The bug is X" / "this fixes Y" requires a runnable reproducer demonstrating the failure AND a re-run demonstrating the fix, both with captured output. End-to-end claims require end-to-end execution, not module-level inference. If verification is impractical (no creds, no data), say so and downgrade to `UNVERIFIED:` — do not silently restate as a conclusion later.

**LLM_Model3 corollary — the leakage version:** "this backtest shows an edge" is a conclusion that requires the leak-free harness to have produced it out-of-sample, net of costs. A too-good in-sample number is `UNVERIFIED:` until the purged/embargoed walk-forward reproduces it. If a trend backtest looks too good, the harness is leaking until proven otherwise (charter §5.3).

## Rule 15: Shell / script authoring

For any script longer than ~10 lines or with multi-line strings: write it to a file with Write/Edit first, then execute the file. Do not construct it inline as a heredoc pasted from PowerShell. Validate before running (`python -m py_compile <file>`; `bash -n <file>`). Sandbox-test against documented API response shapes before it leaves your hands. Avoid multi-line `print(f"..." f"...")` continuations in operator-pasted scripts — terminal paste mangles them.

## Rule 16: Always state where a command/script is to be run

Every command block must declare its execution context explicitly, before the code, no naked code blocks. LLM_Model3 contexts:

- **"In a normal PowerShell window on Godzilla:"** — local PowerShell, Windows paths, git on the local repo, `python`, `pip`, `Get-Content`.
- **"In the Godzilla `.venv` Python REPL (PowerShell with venv activated):"** — after `.\.venv\Scripts\Activate.ps1`.
- **"In the Claude-side sandbox (not the operator):"** — code I run myself.
- **"In a file editor:"** — content for a file, not a command.

If switching contexts within one response, label EACH block. Test before sending: "If the operator reads only this message, will they know which window to type into?" If not, add the label. (Reserved for a future deploy context if LLM_Model3 ever gets one.)

## Rule 17: The operator cannot create PDF files on their machine

Never ask the operator to produce/export/save a `.pdf`. Use formats they can create: `.docx`, `.md`, `.txt`, `.png`/`.jpg`. Default to `.docx` when in doubt. (This constrains what I ask the operator to save; I can still generate PDFs myself via the pdf skill when a deliverable calls for one.)

## Rule 18: Error handling — fail loud, never fake

Priority order: (1) works on real data; (2) falls back visibly with a banner/log warning/annotated status; (3) fails with a clear error (exception, non-zero exit, "FAILED" log line); (4) silently degrades to look "fine" — NEVER. Every `except` ends with a logged error naming context (which symbol, which API, which iteration). Every "skipped N" counter is paired with a list of what/why. Every fallback path logs a `DEGRADED:` line. Summaries show denominators and example failures, never just success counts.

**LLM_Model3 corollary:** a backtest that silently drops symbols with missing data, fills NaNs with zeros, or forward-fills prices across gaps is faking. Surface the coverage ("backtest used 478/500 names; 22 dropped for insufficient history: ...") rather than hiding it behind a clean-looking equity curve. Silent data repair is a leakage and an honesty failure at once.

## Rule 19: Stop on incomplete input — never compile a deliverable from partial data

When input is corrupted, partial, or fails an integrity check (blank OCR pages, truncated file, partial fetch, dropped fields), STOP, run and state an integrity check ("Input integrity: complete" / "incomplete — N gaps in A, B, C"), and wait for the operator's choice. Do not paper over gaps with hedge phrases ("verify in live docs", "assumes shape similar to...") inside a delivered artifact. The bar for a saved reference file is *every claim is solid*. A hedge in chat is fine; a hedge in a saved file is contamination.

**LLM_Model3 corollary:** if the data lake for a backtest window is incomplete (a vendor gap, a missing delisting, a fundamentals field that didn't load), stop and surface it. Do not run the engine on a silently-shortened panel and report the Sharpe as if the sample were whole.

## Rule 20: Audit output for placeholders and unstated assumptions

Before sending any command/script, scan for: literal placeholders (`<paste-your-key>`, `REPLACE_ME`), unstated input assumptions (HOW/WHERE did they save it?), path assumptions, tool-availability assumptions (is `python` on PATH?), state assumptions (service running, env var exported, prior step done). Resolve them with concrete values (ask first if needed) or call them out explicitly above the code block. A bare placeholder inside a quoted string is invisible and will be run as a literal.

**Tripwire corollary (Rule 26):** the strings `5.161.199.155`, `/opt/trader/app/`, `PA3REQ1LMPKO`, `PA3QAZ941NFN`, `trader.service` belong to other projects. Their appearance in any LLM_Model3 command means a partition check before sending.

## Rule 21: Never request command output that would expose credentials

Before asking the operator to paste any command output, ask: "Could this contain a secret?" If yes, redesign to extract only non-secret info. Never request raw output of `cat`/`tail`/`head`/`grep`-without-redaction on credential files, `env`/`printenv`/`Get-ChildItem env:`, process listings with creds in args, or logs that may carry creds in URLs/headers. Safe substitutes: length-only (`awk '{print length($2)}'`), existence-only (`grep -c`), last-4-chars fingerprint, hash prefix. When one file holds multiple credentials (Polygon + Anthropic keys in `.env`), adding one must never require exposing the others to verify.

## Rule 22: Audit logging behavior for credential leaks

`httpx` (and the `anthropic` SDK on top of it) logs full request URLs at INFO by default. Polygon passes its API key as a URL query param (`?apiKey=...`). Any code path making outbound Polygon REST calls MUST suppress URL logging:

```python
for noisy in ("httpx", "httpcore", "aiohttp", "anthropic", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
```

Add this once to the logging setup and don't remove it. Audit each HTTP client's default logging when it's first added. Prefer header-based auth over URL-based when the vendor offers it. (Applies the moment LLM_Model3 makes its first live Polygon call in P1 — trap was a real credential leak into logs on a sibling project, May 2026.)

## Rule 23: Verify actual system date/time before any time-anchored claim

Before any "today", "this week", "market open/closed", "we have N hours", or deadline, run `date && TZ=America/Denver date` and reason from the fresh values. State the verified time inline so the claim is auditable. Godzilla is Mountain Time (America/Denver), NOT Eastern — but US equity market hours are 09:30–16:00 **Eastern** on weekdays excluding holidays, so convert: market close 16:00 ET = 14:00 MT (15:00 MT during the ET-DST / MT-DST overlap, which is most of the year; verify the offset rather than assuming). Session env headers drift over long sessions; recheck.

## Rule 24: The Cowork bash mount can serve stale snapshots of Windows-side files

The file tools (Read/Write/Edit) and the bash mount at `/sessions/<id>/mnt/LLM_MODEL3/` can disagree about content for paths under `C:\trading\LLM_MODEL3\`. The mount can be hours stale even after a successful Edit, and can truncate files past ~byte 14000. NEVER claim "verified on disk" from a Read spot-check — Read and Edit share one in-process view, so a clean Read after a clean Edit proves only the buffer is self-consistent, not that the Windows disk received the write. NEVER run `git add`/`commit`/`push` from the bash sandbox against Windows-side files. `sync` does not refresh the mount. Authoritative disk verification runs from PowerShell on Godzilla:

```powershell
# In a normal PowerShell window on Godzilla, from C:\trading\LLM_MODEL3:
(Get-Item <file>).Length
(Get-Content <file> | Measure-Object -Line).Lines
Get-Content <file> -Tail 5
```

Compare against the Edit-tool's expected values. If a sandbox `py_compile`/`pytest` reports a parse error past ~byte 14000 of a recently-written file, suspect mount truncation, not a real bug — confirm via Read of the same lines, trust Read, defer to PowerShell. Include `Remove-Item .git\index.lock -ErrorAction SilentlyContinue` in any PowerShell commit block, since the sandbox can leave a 0-byte lock that Windows git can't clear.

## Rule 25: Verify session anchors at the start of every new chat or task

Three anchors drift between sessions; going stale on any poisons every downstream instruction. Confirm and state all three inline in the first substantive response:

1. **Date/time** — `date && TZ=America/Denver date`, quote the Mountain time (Rule 23).
2. **Working directory `C:\trading\LLM_MODEL3`** — NOT `C:\trading\LLM_SWING_MODEL\` (separate active project) and NOT `C:\trading\LLM model\` (legacy read-only archive). If the operator appears to be elsewhere, surface the mismatch first.
3. **Workstation Godzilla** (Albuquerque NM). A sandbox hostname is not proof of the workstation; if you can't verify on the box, tag it `ASSUMED`.

Opening line should look like: "Verified: Wed 2026-06-17 17:21 MDT; working in `C:\trading\LLM_MODEL3`; workstation Godzilla."

## Rule 26: Hard partition between LLM_Model3 and its siblings

LLM_Model3 is operationally separate from two sibling locations on Godzilla. From any session anchored in `C:\trading\LLM_MODEL3\`:

- **`C:\trading\LLM_SWING_MODEL\` (separate active project):** do NOT share its DB, execute its scripts, import its code, or commit/push/pull/fetch against its repo. Do NOT use its operational state (decisions, orders, backtest outputs) as context or "baseline" for LLM_Model3 work. Reading its docs for reference is allowed (and was the basis for porting this very file); lifting CODE forward means copying into LLM_Model3 and adapting, never importing in place.
- **`C:\trading\LLM model\` (legacy intraday archive):** read-only. No writes, no git, no script execution against it. Inspect for historical reference only; lift forward by copying.

**Symmetric:** from a sibling session, do not reach into LLM_Model3.

**Tripwire strings** inside an LLM_Model3 session — their appearance in a command, path, or recommendation requires a partition check before sending: `5.161.199.155`, `/opt/trader/app/`, `hetzner_trader`, `PA3REQ1LMPKO`, `PA3QAZ941NFN`, `trader.service`, `trader-prod`, and `C:\trading\LLM_SWING_MODEL\` or `C:\trading\LLM model\` in any write context. If a request implies touching a sibling ("backfill from the swing DB", "reuse the gap-and-go account"), STOP and name the partition violation. If cross-project data is genuinely needed, that's a separate scoped task, requested deliberately, never pulled in as ambient context.

## Rule 27: Verify durability before declaring a session complete

"Compiles + tests pass" is not "done." Pass-on-disk is not pushed-to-origin. Before any session summary or handoff, run from PowerShell on Godzilla (NOT bash — Rule 24):

1. `git status` — every modified/untracked project-artifact file is a blocker until acknowledged.
2. `git add <files>` + `git commit -m "<descriptive message>"` — message names what shipped (not "wip").
3. `git push` — to LLM_Model3's own remote. Confirm with `git remote -v` first; push by intent (the URL of LLM_Model3's remote), not a hardcoded local label. Never cross-push to a sibling's remote (Rule 26).
4. Re-run `git status` — must show "working tree clean" AND "up to date with '<remote>/<branch>'".

The summary must include a literal **`Committed and pushed: <SHA>`** line. The words "shipped/complete/ready/done/deployed/ARMED" must not appear until all four pass; until the push lands, the accurate framing is "code on disk, tests passing, NOT YET committed." Trap (historical): a sibling session shipped ~950 lines across new modules + tests, ran `py_compile` and `pytest` (231 passed) repeatedly, wrapped as "ARMED" — and did ZERO git operations; next morning opened with 9 modified + 16 untracked files. If the operator wants something left uncommitted, record it: "**Per operator request, NOT committed:** `<files>` — `<reason>`."

## Rule 28: Truth and accuracy over helpfulness

Committed to truth and accuracy above being helpful. A confident wrong answer is worse than "I'm not certain." Seven obligations, every response: (1) flag uncertainty up front, never state a guess as fact; (2) never invent sources/titles/authors/URLs — say "I don't have a verified source"; (3) flag any statistic you're not fully sure of, say "approximately", recommend primary-source check; (4) note when a topic may have changed since the knowledge cutoff; (5) never attribute a quote unless certain; (6) never invent function names, library methods, or API syntax — verify against real source/response shape (probe before you build); (7) don't fill logic gaps with assumptions — ask a clarifying question, it's cheaper than a confident wrong answer.

**LLM_Model3 stakes:** model outputs here become the substrate for backtests, factor construction, and (eventually) sizing. A fabricated API field name or an unflagged guess propagates into a result with a dollar interpretation. Verify against the running system — read the column, run the query, hit the endpoint — rather than answering from memory.

## Rule 29: [Adapted — journaling discipline, applies once LLM_Model3 keeps session journals]

The original tightened a swing-specific journal-durability workflow (filling `Committed and pushed:` lines atomically in the docs commit, never as placeholders). LLM_Model3 does not yet keep per-session journals. The transferable principle: **never commit a record with placeholder durability lines** (`_(fill)_`, `TBD`, empty SHA). If/when LLM_Model3 adopts session journals, sequence the wrap as gate → work commit → fill the journal with the real numbers + work SHA → docs commit, and read the committed record back to confirm it shows real values, not fill-text, before saying "done."

## Rule 30: Always search for current information — never default to "I don't know" when tools can answer

When a question touches current events, regulatory state, market data, analyst targets, public-figure positions, or any external fact a search could verify, USE web search/fetch FIRST, then answer. Training cutoff is a property of baked-in knowledge, not of runtime capability. Search proactively (don't wait for "can you check?"), exhaustively (multiple parallel searches across facets for non-trivial topics), surface contradictions with the operator's premise at the top with citations, and cite primary sources as links. "I searched and found nothing useful" is valid; "my cutoff is X" alone is not. Combine with Rule 28: search-derived facts still get uncertainty flags; results themselves can be days behind.

## Rule 31: Verify before generating any operational artifact — explicit, not vibes

Before producing any artifact that executes against real state (a DB query, file edit, PowerShell command, API snippet, code change, or a verification command for the operator), explicitly read the source of truth for every external symbol it references — column names, function signatures, table schemas, CLI flags, API contracts, file paths — and open the response with a `Verification reads:` preamble listing what was checked. An empty or vague preamble means the artifact was guessed and is not safe to ship. Mark each factual claim `VERIFIED [<file>:<line>]:`, `INFERRED [<basis>]:`, or `ASSUMED:`. "This is the standard pattern" is NOT verification — convention generalizes, this codebase does not; read the actual file. Trap (historical): a freshness query guessed five column names (`published_at`, `filed_at`, ...); none matched the migrations; the first query failed and poisoned the transaction for the next six. Reading the migration took seconds. Never make a whole-set claim from a filtered slice (read the full artifact), and never volunteer an unverified aside.

## Rule 32: When a command's output is needed, STOP — emit one command block and nothing after it

If the response contains a command/script/gate the operator must RUN and whose OUTPUT determines the next step, that block is the LAST thing in the response. After it: no "next we'll...", no further steps, no design questions, no postamble. End the turn and WAIT. One run-and-report gate per turn; never stack a second command that depends on the first's result; never pre-write the following steps "to save a round trip." Independent commands with no inter-dependency may share one block, but the turn still ends there. Don't assume success — a green result you imagined is not a green result. "Waiting" is the correctly-finished state. (When in doubt whether a command is a gate, treat it as one and stop.)

## Rule 33: "Committed and pushed" is not "deployed" — restart and verify a long-running process before declaring a runtime change complete

A persistent process loads its code once, at start, and runs that in-memory copy until it exits. `git commit`/`push` changes source on disk; it does NOT restart a running process. So a session can have green tests, a clean `git status`, and a truthful `Committed and pushed: <SHA>` line and STILL have made zero difference to what a live process is doing. This is the durability level beyond Rule 27: **pushed-to-origin ≠ running in the persistent process.**

LLM_Model3 has no persistent runtime today (backtest/paper-only), so this rule is forward-looking. It applies the moment LLM_Model3 starts any long-running process — a scheduled rebalance daemon, a live data ingester, a model server. At that point: any session that changes the code such a process runs is NOT complete until (1) the process is restarted onto the new code, and (2) it is verified emitting the new behavior (e.g., output tagged with the new version, timestamps advancing in real time while the old tag is frozen). Record a wrap line: **`Process restarted + verified on <version>`** or **`No runtime code change — restart N/A.`** Trap (historical): a sibling session bumped a prompt version v2→v4 across ~14 pushed commits with green tests, but the persistent daemon kept running v2 in memory all night; manual one-shot runs (fresh processes) produced a few v4 rows that masked it, while the live path read zero new-version rows and silently built an empty result. A real, verified push was mistaken for a live deploy.

---

## How to use this file

If you (a future session) see this file, you've read it — now apply all relevant rules. If the operator reports an instruction failed, check whether a rule was violated first, and apologize concretely (which rule, what specific oversight), not abstractly. The unifying principle across Rules 1/14/28/30/31: there is almost always a verification step available; the failure is not reaching for it; making the reach visible in the response is the structural fix.
