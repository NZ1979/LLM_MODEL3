# ENGINE_B_MICROCAP_RESULTS.md — Engine B microcap experiment, measured

Results computed under the pre-registered `docs/ENGINE_B_MICROCAP_SPEC.md`. The
spec (with its 2026-08-12 pre-run addenda) and the full implementation were
committed with **NO result under them** (`9c52f8b`, and the spec first at
`11deba6`) — the A-2 discipline. These numbers were then produced by
`scripts/run_engine_b_microcap.py` on Godzilla and are recorded here after the
fact; the runner writes nothing to disk, so no result ever shared a commit with
the spec.

- Date: 2026-08-12 (America/Denver), Godzilla.
- Frozen harness at time of measurement: `9c52f8b`.
- Panel: `data/raw/sharadar/*.parquet` (Sharadar Direct, survivorship-free).
  Identity key `permaticker`. Build/leak-audit span 1998–2020 (run first, audited
  clean); hold-out 2021-01-01 → present, **touched once**, only after the build
  was clean.
- New code: `models/engine_b_universe_micro.py` (parameterised screen, frozen
  `screen()` untouched), `validation/costs_microcap.py` (tiered half-spread +
  √-impact, AUM-aware), `models/engine_b_portfolio.py` (buffered quarterly
  long-only book), `scripts/run_engine_b_microcap.py`, and
  `tests/test_engine_b_microcap_synthetic.py`.

## Headline

**The microcap tail carries a larger gross cross-sectional signal than the liquid
small/mid band — but it is NOT capturable net of realistic microcap frictions.**
On both the 1998–2020 build and the once-touched 2021+ hold-out, the microcap
book's net tradeable Sharpe is **below** the liquid baseline's, at both 1× and 2×
cost — the opposite of the pre-registered ≥ +0.20 margin required to adopt.
Per the a-priori decision rule, **Engine B stays on the liquid small/mid
universe; the microcap experiment is recorded as an informative negative.** This
is the base-rate outcome the spec anticipated ("the gross edge is bigger but the
realistic cost model + capacity claw back much of it… a collapse net of costs is
the base-rate outcome and an acceptable, informative result").

## Decision-rule adjudication (a priori, both spans)

Rule: adopt microcaps iff, on BOTH spans, net-of-realistic-cost tradeable Sharpe
(@ $0.5–2M AUM) exceeds the liquid baseline by **≥ +0.20 annualised**, that margin
**survives 2× cost**, and IC > 0 with (near-)monotone decile Sharpe. A higher
gross IC alone does **not** qualify.

| span | micro net Sharpe (1× / 2×) | liquid net Sharpe (1×) | margin (1× / 2×) | qualifies? |
|---|---|---|---|---|
| build 1998–2020 | 0.41 / 0.34 | 0.52 | **−0.11 / −0.18** | NO |
| hold-out 2021–2026 | 0.08 / 0.00 | 0.62 | **−0.54 / −0.62** | NO |

Both the liquid and micro books use the **identical** buffered construction +
realistic cost model, so the comparison isolates the universe change (the frozen
naive-D10 Sharpe 0.54 is a reference point only). **FAILS on both spans.** →
Engine B remains on the liquid $300M–$15B band.

## Per-band detail

### Build 1998–2020 (net of realistic cost, out-of-sample)

| band | median elig/mo | gross IC | NW-t | Spearman(dec,ret / Sharpe) | net Sharpe @$0.5–2M 1× | turn/reb | maxDD | leak z |
|---|---|---|---|---|---|---|---|---|
| micro (primary) | 433 | +0.0564 | +6.71 | 0.89 / 0.90 | 0.41 | 0.81 | −67% | +22.2 |
| liquid (comparison) | 1,262 | +0.0254 | +2.93 | 0.87 / 0.92 | 0.52 | 0.35 | −62% | +11.7 |
| nano | 21 | +0.0648 | +4.10 | 0.37 / 0.24 | ≈ −0.05 (3 names, 10% inv.) | 0.12 | −48% | +4.1 |
| full_tail | 459 | +0.0595 | +7.08 | 0.85 / 0.90 | 0.30 | 0.81 | −70% | +22.9 |

### Hold-out 2021–2026 (touched once)

| band | median elig/mo | gross IC | NW-t | Spearman(dec,ret / Sharpe) | net Sharpe @$0.5–2M 1× | turn/reb | maxDD | leak z |
|---|---|---|---|---|---|---|---|---|
| micro (primary) | 320 | +0.1093 | +5.66 | 0.90 / 0.90 | 0.08 | 0.81 | −30% | +15.5 |
| liquid (comparison) | 1,565 | +0.0496 | +3.81 | 0.95 / 0.96 | 0.62 | 0.32 | −24% | +16.2 |
| nano | 41 | +0.1037 | +5.93 | 0.81 / 0.73 | ≈ −0.40 (5 names, 18% inv.) | 0.25 | −35% | +4.8 |
| full_tail | 359 | +0.1242 | +6.98 | 0.96 / 0.96 | −0.11 to −0.26 | 0.85 | −47% | +14.8 |

Passive benchmarks (gross, in-backtest): build — equal-weight micro universe
Sharpe 0.29 / SPY 0.51; hold-out — equal-weight micro universe **−0.55** (CAGR
−16.5%, maxDD −73%) / SPY 1.03. The 2021–2026 microcap universe itself was a
disaster; the micro *book* (Sharpe 0.08) beat its universe by a wide margin — the
selection signal works — but that skill inside a sinking, high-cost universe only
reached flat, while the liquid book returned Sharpe 0.62.

## Why the tail signal does not survive

1. **Turnover.** Micro book trades ~0.81 of the book per rebalance vs ~0.32–0.35
   liquid — microcap D10 membership churns ~2.3× faster and the D10-in/<D8-out
   buffer helps less.
2. **Spread + impact.** 50 bps half-spread (micro) / 150 (nano) vs 10 (liquid),
   plus √-impact that rises with AUM (participation 0.00→0.19 as AUM $0.1M→$5M).
3. **Universe drawdown.** The microcap universe's own deep drawdowns (−67% build,
   and −73% for the EW universe in the hold-out) swamp the thin net edge.

Net edge = gross edge − cost×frequency; microcaps have the widest spreads and, here,
the highest turnover and worst universe returns, so the larger gross IC is more
than consumed.

## Leak audit — why these numbers are trusted

- **Harness reproduces the frozen baseline exactly.** Run on the liquid band, the
  new machinery returns byte-identical IC/leak numbers to the frozen baseline
  (`bb3b8e9`): build IC +0.0254 / t +2.93 / +11.7 SD / D10−D1 +0.83%; hold-out IC
  +0.0496 / t +3.81 / +16.2 SD / D10−D1 +1.28%. The parameterised screen leaves
  `models/engine_b_universe.screen()` byte-for-byte untouched (asserted in
  `tests/test_engine_b_microcap_synthetic.py`, and 0/1,241 eligibility rows differ
  on a real `_build`).
- **Cheat control + permutation null clean on every band, both spans** (cheat IC
  +1.000 / perfect staircase; null mean ≈ 0; real IC +4.1 to +22.9 SD above null).
- **`full_tail` 2021+ tripwire (IC +0.1242 > 0.12) adjudicated as regime, not
  leak.** Evidence: (a) the harness's own cheat/null controls are clean on that
  exact panel; (b) the liquid band on the same run is byte-identical to the frozen
  baseline; (c) the lift is the uniform 2021+ regime effect that also raised the
  *liquid* IC (build +0.0254 → hold-out +0.0496), documented as regime in the
  baseline results; (d) decisively, `full_tail`'s NET book is **negative** — a
  real look-ahead would inflate the tradeable book, not sink it. A high gross IC
  with a losing net book is a real-but-uncapturable signal crushed by cost, not a
  peek. Not banked as an edge regardless.

## Not acted on (would require a fresh pre-registration)

The micro-band sensitivity grid shows **looser floors** ($100k liquidity / $2
price) with higher net Sharpe (build 0.75, hold-out 0.33 @ $1M/1×) than the
primary ($250k/$5: 0.41 / 0.08), because they admit ~2× more names and diversify
better. **Switching the primary band to that cell to manufacture a pass is exactly
the retune-to-rescue the spec forbids** — it leans into the sub-$5 microstructure
the primary excluded a priori and is a post-hoc single-AUM/1× pick. Even taken at
face value it does not clear +0.20 over liquid on both spans (hold-out 0.33 vs
liquid 0.62). If pursued at all, it needs a fresh, separately dated
pre-registration justifying the change on grounds independent of this result, with
its own out-of-sample slice.

## Recommendation

Do **not** deploy a microcap sleeve. For the ~$100k satellite, the honest options
are (a) run Engine B on the **liquid small/mid universe** (the frozen baseline
band), which nets Sharpe ~0.5–0.6 under this construction on both spans, or (b)
buy a factor/trend ETF — the benchmark any custom build must beat. Microcaps do
not justify the custom build at these frictions, and this understates live
microcap difficulty (halts, sudden delistings, fraud, borrow, gappy fills, worse
data), all of which push the negative further. **This closes the microcap
experiment.**

Note for the next step: the liquid-book Sharpe here (0.5–0.6, net) is the honest
number to carry into P5, but in 2021–2026 it still trailed SPY buy-and-hold
(Sharpe 1.03). The live-decision benchmark — beating a real small-cap-value /
momentum / managed-futures ETF net of cost and effort — is the P5/paper bar and is
chosen at paper time, not here.

## Reproduce

Frozen harness `9c52f8b`, on Godzilla `.venv`:

    python scripts/run_engine_b_microcap.py --span build
    python scripts/run_engine_b_microcap.py --span holdout --confirm-holdout

Synthetic correctness/leak audit (no real panel):
`python tests/test_engine_b_microcap_synthetic.py`.

## Changelog

- 2026-08-12 — Build and hold-out measured under the pre-registered spec with the
  frozen implementation (`9c52f8b`). Harness proven leak-free (synthetic suite +
  cheat control + permutation null + exact reproduction of the frozen liquid
  baseline on both spans). Microcap net tradeable Sharpe is below the liquid
  baseline on BOTH spans at 1× and 2× cost; the decision rule FAILS; Engine B
  stays on the liquid small/mid universe. Hold-out spent (touched once). Recorded
  as an informative negative. `full_tail` 2021+ IC tripwire adjudicated as regime,
  not leak.
