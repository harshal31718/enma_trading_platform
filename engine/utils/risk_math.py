import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Union

def calculate_portfolio_var(
    position_notionals: Dict[str, float], 
    price_histories: Dict[str, Union[np.ndarray, List[float]]], 
    confidence_level: float = 0.95
) -> Tuple[float, float]:
    """
    Calculates historical Value at Risk (VaR) and CVaR for a portfolio.
    position_notionals: dict mapping symbol -> signed notional size (+ for long, - for short)
    price_histories: dict mapping symbol -> numpy array or list of historical closing prices
    """
    if not price_histories or not position_notionals:
        return 0.0, 0.0

    returns = {}
    # Filter out empty or NaN histories
    clean_histories = {}
    for symbol, prices in price_histories.items():
        if prices is None or len(prices) == 0:
            continue
        p = np.array(prices, dtype=float)
        p = p[~np.isnan(p)]
        if len(p) < 2:
            continue
        clean_histories[symbol] = p

    if not clean_histories:
        return 0.0, 0.0

    min_len = min(len(p) for p in clean_histories.values())
    if min_len < 2:
        return 0.0, 0.0

    for symbol, p in clean_histories.items():
        aligned_p = p[-min_len:]
        returns[symbol] = np.diff(np.log(aligned_p))

    assets = list(returns.keys())
    run_len = min(len(returns[a]) for a in assets)
    if run_len < 1:
        return 0.0, 0.0
        
    r_matrix = np.column_stack([returns[a][-run_len:] for a in assets])
    
    # Ensure all asset symbols are represented in position_notionals
    sizes = np.array([position_notionals.get(a, 0.0) for a in assets])
    total_notional = np.sum(np.abs(sizes))
    if total_notional == 0:
        return 0.0, 0.0
    
    weights = sizes / total_notional
    port_returns = np.dot(r_matrix, weights)
    
    alpha = 1.0 - confidence_level
    var_pct = np.percentile(port_returns, alpha * 100)
    var_pct = min(0.0, var_pct)
    var_amount = abs(var_pct * total_notional)
    
    tail_losses = port_returns[port_returns <= var_pct]
    if len(tail_losses) > 0:
        cvar_amount = abs(np.mean(tail_losses) * total_notional)
    else:
        cvar_amount = var_amount
        
    return float(var_amount), float(cvar_amount)


def calculate_correlation_matrix(
    price_histories: Dict[str, Union[np.ndarray, List[float]]]
) -> Dict[str, Dict[str, float]]:
    """
    Returns correlation matrix as a nested dictionary.
    """
    if not price_histories:
        return {}
    
    df_data = {}
    for symbol, prices in price_histories.items():
        if prices is None or len(prices) == 0:
            continue
        p = np.array(prices, dtype=float)
        clean_prices = p[~np.isnan(p)]
        if len(clean_prices) < 2:
            continue
        df_data[symbol] = np.diff(np.log(clean_prices))
        
    if not df_data:
        return {}
        
    min_len = min(len(arr) for arr in df_data.values())
    if min_len < 2:
        return {}
        
    aligned_data = {k: v[-min_len:] for k, v in df_data.items()}
    
    df = pd.DataFrame(aligned_data)
    corr_df = df.corr(method='pearson').fillna(0.0)
    
    for col in corr_df.columns:
        corr_df.loc[col, col] = 1.0
        
    return corr_df.to_dict()
