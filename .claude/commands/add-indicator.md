# Add Indicator

Add: $ARGUMENTS

Indicators live in the pluggable provider layer (`engine/indicators/`, DECISIONS.md #12).
Adding one means extending the interface and implementing it in **both** backends so a
backend switch never breaks a strategy.

## Step 0 — Check for duplicates FIRST

Read `workspace/docs/indicators/INDEX.md` before writing any code.

- The **Indicator Layer** table lists all 13 indicators already in the provider layer.
- The **Inline-Only** table lists indicators that exist only inside a strategy.
- If the indicator you want is in either table, **do not add it again** — use the existing one.

## Step 1 — Declare on the interface

Add an abstract method to `IndicatorProvider` in `engine/indicators/base.py`:

```python
@abstractmethod
def indicator_name(self, candles: np.ndarray, period: int = 14, sequential: bool = False) -> Single:
    """What it does."""
    raise NotImplementedError
```

Use the named column constants (`CLOSE`, `HIGH`, `LOW`, `OPEN`, `VOLUME`) — never hardcode indices.

## Step 2 — Add convenience function

Add to `base.py` (delegates to `get_indicators()`) and export from `engine/indicators/__init__.py`
(`__all__` + the import block).

## Step 3 — Implement in `adapters/talib_adapter.py`

Using TA-Lib where available.
- `sequential=False` → latest value as `float` (tuple of floats for multi-line indicators).
- `sequential=True`  → full numpy series (tuple of arrays).

## Step 4 — Implement in `adapters/pandas_ta_adapter.py`

Using pandas-ta (build the OHLCV frame via `_frame(candles)`). Keep the return shape
identical to the TA-Lib adapter.

## Step 5 — Docstring

Add a docstring: what it does, params, return type.

## Step 6 — Update documentation

1. Create `workspace/docs/indicators/<name>.md` — follow the format of existing indicator docs.
2. Add a row to `workspace/docs/indicators/INDEX.md` — both the layer table and the "Used By" column.
3. Update `workspace/docs/state/CURRENT_STATE.md` — indicators list.

Indicators are engine-internal — do not add to `workspace/docs/core/API_CONTRACTS.md`.
