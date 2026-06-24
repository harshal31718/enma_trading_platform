import sys
from pathlib import Path
# Resolve the engine directory and add to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest
from utils.risk_math import calculate_portfolio_var, calculate_correlation_matrix

def test_calculate_portfolio_var_empty() -> None:
    # Empty inputs should return 0.0, 0.0
    var, cvar = calculate_portfolio_var({}, {})
    assert var == 0.0
    assert cvar == 0.0

    var, cvar = calculate_portfolio_var({"BTCUSDT": 1000.0}, {})
    assert var == 0.0
    assert cvar == 0.0

    var, cvar = calculate_portfolio_var({}, {"BTCUSDT": [100.0, 101.0, 102.0]})
    assert var == 0.0
    assert cvar == 0.0

def test_calculate_portfolio_var_single_price() -> None:
    # Less than 2 prices should return 0.0, 0.0
    var, cvar = calculate_portfolio_var(
        {"BTCUSDT": 1000.0},
        {"BTCUSDT": [100.0]}
    )
    assert var == 0.0
    assert cvar == 0.0

def test_calculate_portfolio_var_nan_handling() -> None:
    # NaNs should be filtered out
    var, cvar = calculate_portfolio_var(
        {"BTCUSDT": 1000.0},
        {"BTCUSDT": [100.0, np.nan, 101.0, 102.0, np.nan, 103.0]}
    )
    assert var >= 0.0
    assert cvar >= 0.0

def test_calculate_portfolio_var_normal() -> None:
    prices_btc = [100.0, 99.0, 97.02, 94.1094]
    
    position_notionals = {"BTCUSDT": 10000.0}
    price_histories = {"BTCUSDT": prices_btc}
    
    var_amount, cvar_amount = calculate_portfolio_var(
        position_notionals,
        price_histories,
        confidence_level=0.95
    )
    
    assert var_amount > 0.0
    assert cvar_amount >= var_amount
    assert var_amount <= 10000.0

def test_calculate_correlation_matrix_empty() -> None:
    assert calculate_correlation_matrix({}) == {}
    assert calculate_correlation_matrix({"BTCUSDT": [100.0]}) == {}
    assert calculate_correlation_matrix({"BTCUSDT": []}) == {}

def test_calculate_correlation_matrix_normal() -> None:
    prices_btc = [100.0, 101.0, 102.0, 103.0]
    prices_eth = [10.0, 10.1, 10.2, 10.3]
    
    price_histories = {
        "BTCUSDT": prices_btc,
        "ETHUSDT": prices_eth
    }
    
    matrix = calculate_correlation_matrix(price_histories)
    assert "BTCUSDT" in matrix
    assert "ETHUSDT" in matrix
    
    assert matrix["BTCUSDT"]["BTCUSDT"] == 1.0
    assert matrix["ETHUSDT"]["ETHUSDT"] == 1.0
    
    assert abs(matrix["BTCUSDT"]["ETHUSDT"] - 1.0) < 0.01
    assert abs(matrix["ETHUSDT"]["BTCUSDT"] - 1.0) < 0.01

def test_calculate_correlation_matrix_negative() -> None:
    # BTC returns are increasing: log returns ~ [0.0099, 0.0196, 0.0287]
    prices_btc = [100.0, 101.0, 103.0, 106.0]
    # ETH returns are decreasing: log returns ~ [-0.0100, -0.0204, -0.0314]
    prices_eth = [10.0, 9.9, 9.7, 9.4]
    
    price_histories = {
        "BTCUSDT": prices_btc,
        "ETHUSDT": prices_eth
    }
    
    matrix = calculate_correlation_matrix(price_histories)
    assert matrix["BTCUSDT"]["ETHUSDT"] < 0.0
    assert matrix["ETHUSDT"]["BTCUSDT"] < 0.0
