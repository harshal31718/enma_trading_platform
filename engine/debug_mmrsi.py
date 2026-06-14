"""
Temporary debug script: tests MicroMacroRSIDivergence signal generation.
Run inside engine container: python /app/debug_mmrsi.py
"""
import asyncio
import numpy as np
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/')
import indicators as ta


async def test():
    import asyncpg
    pool = await asyncpg.create_pool(
        dsn='postgresql://enma:enma_dev_password@timescaledb:5432/enma_candles',
        min_size=1, max_size=2
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time, open, close, high, low, volume FROM candles "
            "WHERE exchange='Binance Futures' AND symbol='BTCUSDT' AND timeframe='1h' "
            "ORDER BY time ASC LIMIT 4000"
        )
    await pool.close()

    if not rows:
        print('NO CANDLES FOUND')
        return

    candles_np = np.column_stack([
        [r[0].timestamp() * 1000 for r in rows],
        [r[1] for r in rows], [r[2] for r in rows],
        [r[3] for r in rows], [r[4] for r in rows], [r[5] for r in rows],
    ]).astype(np.float64)

    n = len(candles_np)
    print(f'Loaded {n} candles')

    macro_p, micro_p = 10, 2
    rsi_p = 14
    min_pb, max_pb, min_dd = 5, 100, 4.0
    cw = 30  # confluence_window
    smooth_len = 60

    bull_macro = []   # (t, c_abs) where macro bull divergence fired_now
    bull_micro = []   # (t, c_abs) most recent micro bull at each candle

    for t in range(210, n):
        cd = candles_np[:t + 1]
        cn = t + 1
        span = max_pb + 4 * macro_p + 10
        off = max(0, cn - span)
        win = cd[off:]

        rsi = ta.rsi(cd, period=rsi_p, sequential=True)

        # ── Macro bull ──────────────────────────────────────────────────
        ml = ta.pivot_low(win, macro_p, macro_p, source='low', sequential=True)
        cs = np.where(~np.isnan(ml))[0]
        if len(cs) >= 2:
            pr, cr = int(cs[-2]), int(cs[-1])
            pa, ca = off + pr, off + cr
            fn = (ca == cn - 1 - macro_p)
            if fn:
                pp, pc = ml[pr], ml[cr]
                rp, rc = rsi[pa], rsi[ca]
                dist = ca - pa
                cond = (
                    (pc < pp) and (rc > rp) and
                    (rc - rp >= min_dd) and
                    (min_pb <= dist <= max_pb) and
                    (rc < 50)
                )
                if cond:
                    bull_macro.append((t, ca))

        # ── Micro bull ──────────────────────────────────────────────────
        mm = ta.pivot_low(win, micro_p, micro_p, source='low', sequential=True)
        cs_m = np.where(~np.isnan(mm))[0]
        if len(cs_m) >= 2:
            pr_m, cr_m = int(cs_m[-2]), int(cs_m[-1])
            pa_m, ca_m = off + pr_m, off + cr_m
            pp_m, pc_m = mm[pr_m], mm[cr_m]
            rp_m, rc_m = rsi[pa_m], rsi[ca_m]
            dist_m = ca_m - pa_m
            cond_m = (
                (pc_m < pp_m) and (rc_m > rp_m) and
                (rc_m - rp_m >= min_dd) and
                (min_pb <= dist_m <= max_pb) and
                (rc_m < 50)
            )
            if cond_m:
                bull_micro.append((t, ca_m))

    print(f'Macro bull (fired_now): {len(bull_macro)}')
    print(f'  at t={[x[0] for x in bull_macro]}')
    print(f'Micro bull (any valid latest): {len(bull_micro)}')

    # Check confluence
    conf = 0
    for tm, cam in bull_macro:
        for tmi, cami in bull_micro:
            if tmi <= tm and abs(cam - cami) <= cw:
                conf += 1
                print(f'  CONFLUENT at t_macro={tm}: macro_c={cam}, micro_c={cami}, dist={abs(cam-cami)}')
                break
    print(f'\nConfluent bull signals: {conf}')

    # ── Without level filter: how many would we get? ──────────────────
    print('\n--- Without RSI level filter (<50) ---')
    bull_macro2 = []
    bull_micro2 = []
    for t in range(210, n):
        cd = candles_np[:t + 1]
        cn = t + 1
        span = max_pb + 4 * macro_p + 10
        off = max(0, cn - span)
        win = cd[off:]
        rsi = ta.rsi(cd, period=rsi_p, sequential=True)
        ml = ta.pivot_low(win, macro_p, macro_p, source='low', sequential=True)
        cs = np.where(~np.isnan(ml))[0]
        if len(cs) >= 2:
            pr, cr = int(cs[-2]), int(cs[-1])
            pa, ca = off + pr, off + cr
            fn = (ca == cn - 1 - macro_p)
            if fn:
                pp, pc = ml[pr], ml[cr]
                rp, rc = rsi[pa], rsi[ca]
                dist = ca - pa
                cond = (pc < pp) and (rc > rp) and (rc - rp >= min_dd) and (min_pb <= dist <= max_pb)
                if cond:
                    bull_macro2.append((t, ca))
        mm = ta.pivot_low(win, micro_p, micro_p, source='low', sequential=True)
        cs_m = np.where(~np.isnan(mm))[0]
        if len(cs_m) >= 2:
            pr_m, cr_m = int(cs_m[-2]), int(cs_m[-1])
            pa_m, ca_m = off + pr_m, off + cr_m
            pp_m, pc_m = mm[pr_m], mm[cr_m]
            rp_m, rc_m = rsi[pa_m], rsi[ca_m]
            dist_m = ca_m - pa_m
            cond_m = (pc_m < pp_m) and (rc_m > rp_m) and (rc_m - rp_m >= min_dd) and (min_pb <= dist_m <= max_pb)
            if cond_m:
                bull_micro2.append((t, ca_m))

    print(f'Macro bull: {len(bull_macro2)}, Micro bull: {len(bull_micro2)}')
    conf2 = 0
    for tm, cam in bull_macro2:
        for tmi, cami in bull_micro2:
            if tmi <= tm and abs(cam - cami) <= cw:
                conf2 += 1
                break
    print(f'Confluent bull (no level filter): {conf2}')

asyncio.run(test())
