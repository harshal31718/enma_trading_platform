# Plan: Backtest UI Layout Refactor

This plan details the design and layout modifications for the Backtest page results viewer (`client/src/pages/Backtest.jsx`). The goal is to clean up vertical space, relocate actions to standard headers, and enrich the summary metric cards.

---

## Proposed UI Changes

### 1. Relocate "Export JSON" Button
*   **Current State:** Positioned in a large card at the bottom of the Overview tab.
*   **Target State:** Rendered in the right-hand corner of the tabs header bar (the bar housing the "Overview", "Performance Summary", "List of Trades", and "Compare" triggers).
*   **Layout Constraint:** The tabs header bar is constrained to `h-11` (44px) to match the page rhythm. The button will be styled as a compact button:
    *   Height: `h-7` (28px).
    *   Text size: `text-xs`.
    *   Padding: `px-2.5 py-1`.
    *   This ensures the button fits comfortably within the header bar without stretching its height.

### 2. Summary Metric Grid Expansion (2x7 Grid)
*   **Current State:** Renders 10 indicators in a `grid-cols-5` layout (2 rows of 5).
*   **Target State:** Expand the metrics array to 14 elements and change the wrapper class to `grid-cols-7` (2 rows of 7) to render a clean, unified dashboard grid.
*   **Metrics Added:**
    *   **Leverage:** `${activeResult.leverage}x`
    *   **Fee Rate:** `${((activeResult.feeRate || 0) * 100).toFixed(2)}%`
    *   **Total Fees:** `activeResult.metrics?.totalFees ? formatPrice(activeResult.metrics.totalFees) : '-'` (styled red-400)
    *   **Liquidations:** `activeResult.metrics?.liquidations ?? 0` (styled red-400 if >0)
*   **Drawdown allowed check:** The "Max Drawdown" card value will be updated to show:
    *   `[actual_drawdown] / [allowed_drawdown]`
    *   Formula: `` `${formatPct(m.maxDrawdown)} / ${formatPct((activeResult.riskParams?.max_session_dd ?? 0.20) * 100)}` ``

### 3. Remove Redundant Sections
*   **Action:** Completely delete the "Simulation Config" block (`lines 541-587`) and the "Export Results" block (`lines 589-603`) from the bottom of the `<TabsContent value="overview">` element.

---

## File Changes

### [MODIFY] [Backtest.jsx](file:///c:/Users/harsh/Desktop/enma_trading_platform/client/src/pages/Backtest.jsx)
*   Relocate button trigger to the top tab bar.
*   Convert metrics grid to `grid-cols-7`.
*   Inject the 4 additional parameter cards.
*   Replace standard Max Drawdown string with the actual-to-allowed comparison string.
*   Prune bottom configuration and export divs.

---

## Verification Plan

### Manual Verification
1. Open the Backtest page in the browser.
2. Select any completed backtest run.
3. Verify that the tabs header bar retains its height (`h-11`) and contains the "Export JSON" button on the right.
4. Click the "Export JSON" button and confirm that the JSON download triggers correctly.
5. Verify that the top summary section shows exactly 14 cards in 2 rows of 7.
6. Confirm the "Max Drawdown" card shows both the actual drawdown and the risk parameter allowed drawdown (e.g. `5.20% / 20.00%`).
7. Verify that the old "Simulation Config" and "Export Results" sections at the bottom of the Overview are gone.
