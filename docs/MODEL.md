# The "own model": rationale, design choices, and limitations

This document explains the policy-rate model that overlays the market-implied
path on the Central Bank Paths page — why it is built the way it is, what was
considered and rejected, and where it will mislead you if you over-trust it.
It is the same file rendered in the app's "Model rationale" tab
(`docs/MODEL.md` in the repo).

## What the model is

A two-layer rule, iterated across the meeting calendar:

1. **Taylor-gap core**

   ```
   r* = neutral + a·(core inflation − target) + b·(NAIRU − unemployment)
   expected move per meeting = inertia · (r* − current rate) + momentum tilt
   ```

   `r*` is where the rule says policy "should" be; the bank is assumed to
   close a fraction (`inertia`) of the gap at each meeting rather than jump.

2. **Momentum overlay** — a small, bounded tilt (±14bp max):
   - 3-month annualised core inflation vs. year-over-year: re-acceleration is
     hawkish, deceleration dovish (captures turning points the YoY number lags).
   - Chicago Fed NFCI (US only): tight financial conditions argue for less
     tightening, easy conditions for more.

The expected move is squashed into P(hike)/P(hold)/P(cut) with a logistic
(temperature ≈ 12bp — small enough to be decisive near a full step, smooth
near zero), then discretised to 25bp steps to build a path comparable
meeting-for-meeting with the market's.

`a`, `b`, `inertia`, and the neutral rate are **sidebar inputs, not
estimates**. They encode *your* view of the reaction function. The defaults
(a = b = 0.5, inertia = 0.25) are the classic Taylor (1993) weights and a
conventional gradualism setting — starting points, not truth.

## Why this design over the alternatives

**Why rule-based, not a trained classifier?**
A multinomial logit or gradient-boosted classifier on historical meeting
decisions is the natural "serious" version — but it needs a carefully built
training panel of *vintage* macro data (what the committee saw at the time,
not today's revised series; FRED's ALFRED archive exists for this), it has
very few genuinely independent observations per bank (8 meetings/year, one
regime at a time), and it would overfit the recent cycle badly. The
rule-based core works day one with zero training data, its failure modes are
visible (you can read the gaps), and every parameter has an economic
interpretation. The classifier is the right *second* step once a vintage
panel and backtesting exist — `policy_model.model_path()` keeps a stable
interface precisely so a fitted model can replace it without touching the
page.

**Why a Taylor rule as the core?**
It is the canonical policy benchmark: simple, forty years of literature,
referenced by central banks themselves in their own communication. Its
parameters are few and interpretable, which matters because the app exposes
them as sliders — a slider on an opaque model coefficient would be
meaningless.

**Why the inertia parameter?**
Central banks empirically smooth: they close policy gaps over several
meetings rather than jumping to r* (interest-rate smoothing is one of the
most robust findings in the reaction-function literature). Without inertia
the model would demand absurd 200bp single-meeting moves whenever gaps are
large.

**Why a logistic squash to probabilities?**
It is smooth, monotone, and its temperature has bp units you can reason
about. The alternative — hard thresholds — produces signals that flip
discontinuously on a 1bp change in an input.

**Why the bounded momentum tilt?**
Pure gap rules are slow at turning points (YoY inflation lags). The 3m-vs-YoY
term reacts a quarter earlier. It is clipped (±8bp inflation, ±6bp NFCI) so a
noisy month can *tilt* a close call but never overrule the core.

**Alternatives considered and rejected (for now):**
- *Shadow-rate / term-structure models* (Wu-Xia, Krippner): powerful at the
  zero bound but heavy, latent-factor machinery — impossible to expose as
  understandable sliders, overkill for a divergence monitor.
- *NLP on statements/minutes*: genuinely informative (hawkish/dovish tone),
  but no reliable free feed, and adds an opaque layer exactly where
  transparency is the point.
- *Market-only measures* (surveys, dealer forecasts): using another market
  measure as the "model" gives you no independent view — the divergence
  signal would be circular.
- *Full macro models (DSGE)*: not remotely worth the complexity here.

## Limitations — read before acting on a signal

1. **r\* and NAIRU are unobservable.** The neutral rate slider is a guess;
   estimates differ by a full percentage point. A 50bp error in neutral is a
   50bp bias in every divergence. Treat the *level* of divergence with
   suspicion; changes in divergence are more trustworthy than levels.
2. **One rule for four very different banks.** The ECB sets policy for twenty
   economies with one rate; the BoJ spent a decade in yield-curve control;
   the rule knows none of this institutional context.
3. **Macro data quality is uneven.** US series are first-rate (core PCE,
   UNRATE, NFCI). Euro-area/UK/Japan currently use best-effort FRED codes
   (headline CPI, OECD unemployment) — noisier, revised, and missing the
   "core" distinction. Fed signals deserve the most trust; treat the others
   as indicative until their series are upgraded.
4. **The model sees no meeting-specific information.** Forward guidance,
   dot plots, speeches, QT/QE — all invisible to it. The market prices these;
   the model cannot. Part of any divergence is simply information the model
   does not have, *not* mispricing.
5. **The market side is itself a proxy.** Government-curve forwards carry
   term premium and safe-haven richness (documented on the Data sources tab),
   so a few bp of permanent "divergence" is measurement, not signal — one
   reason the outright threshold is 10bp, not zero.
6. **Signals are not backtested.** The 10bp/25bp conviction thresholds are
   sensible conventions, not fitted values. Persist daily snapshots and
   backtest before risking capital on them.
7. **Momentum is a heuristic.** The clip levels and scalings are judgment
   calls, not estimates.

## How to extend it

- **Classifier swap**: build a panel of historical meetings with vintage
  macro (ALFRED), label {cut, hold, hike}, fit a multinomial logit or
  gradient boosting, and implement the same `model_path()` signature.
- **Better non-US macro**: replace the EA/UK/JP series with core-inflation
  and national-source unemployment codes; add per-bank NAIRU estimates.
- **Snapshot & backtest**: persist each day's market path, model path and
  divergence (the S3 cache is the natural home) and evaluate signal hit-rates
  before trusting conviction levels.

**Nothing here is investment advice.** The divergence is a prompt to
investigate *why* the model and the market disagree — most days, the market
knows something the rule does not.
