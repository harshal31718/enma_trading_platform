# Golden Check

Gate any change that touches the engine decision/data pipeline (backtest, indicators, risk model,
the Five-Model pipeline) with a byte-equivalence check against a saved baseline. This is the
CLAUDE.md **Rule C** ritual, wrapped — capture a baseline before the change, snapshot after, assert
the metrics are identical within tolerance.

Arguments: $ARGUMENTS — the label for this snapshot (e.g. `phase3`, `microscalper-ported`). Optional;
defaults to `check`.

> Runs the REAL backtest runner on a fixed, deterministic config (2024 BTCUSDT/1h, all 5 seeded
> strategies). Identical candles + identical params + no randomness ⇒ identical metrics. Requires
> TA-Lib + the engine databases, so it **must run inside the engine container** (Rule B).
>
> **Coverage caveat:** the scenario set lives in `engine/scripts/golden_master.py` and is
> currently single-symbol, funding-off, no exec-algo — it cannot see multi-symbol or exec-algo
> regressions (this blind spot hid QNT-1/QNT-2; see `workspace/plan/audit_2_quant-core.md` §2).
> Plan 9.1 adds multi-symbol/exec-algo scenarios; once landed, this gate covers them
> automatically. Until then, changes to those paths need their own behavioral test, not just a
> green golden master.

---

## 1. Capture the baseline (BEFORE touching any engine code)

Only needed once per refactor — skip if `engine/scripts/golden/baseline.json` already reflects
the pre-change state.

```
docker compose exec engine python -m scripts.golden_master run --label baseline
```

Confirm it printed per-strategy `trades=/netProfit=/winRate=` lines for all 5 strategies with no
`ERROR`.

## 2. Snapshot AFTER the change

```
docker compose exec engine python -m scripts.golden_master run --label $ARGUMENTS
```

## 3. Assert equality (exit 0 = identical, 1 = drift)

```
docker compose exec engine python -m scripts.golden_master compare --a baseline --b $ARGUMENTS
```

- **Exit 0 / `GOLDEN-MASTER OK`** → the change is metric-neutral. Proceed.
- **Exit 1 / `GOLDEN-MASTER DRIFT`** → it lists `strategy.metric: old != new`. The change altered
  behavior. **Stop.** Either it's an unintended regression (fix it) or a deliberate behavior change
  (it must not be gated against `baseline` — snapshot a new intentional baseline and document why in
  `DECISIONS.md`).

## Report

State the compare result verbatim (OK or the drift list). Never report a pipeline change "done"
without a green golden-master compare — that is the Rule-C bar. Per-strategy ports: run a compare
after **each** strategy, not just at the end.
