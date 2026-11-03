from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from src.data.base_feed import Candle
from src.utils.logger import log

@dataclass
class StockSignal:
    symbol: str
    direction: str          # "BUY_CALL" or "BUY_PUT"
    option_type: str        # "CE" or "PE"
    spot_price: float
    trigger_reason: str
    rvol: float
    atr_pct: float
    target_strike: float
    is_swing_candidate: bool

class StockScreener:
    """
    Screens Top F&O Stocks for High-Momentum Option Buying:
    - Relative Volume (RVOL >= min_rvol)
    - ATR expansion (ATR% >= min_atr_pct)
    - Breakout of morning consolidation
    - Identifies conditional carry-forward potential.
    """
    def __init__(self, min_rvol: float = 1.8, min_atr_pct: float = 1.2, rvol_lookback: int = 20):
        self.min_rvol = min_rvol
        self.min_atr_pct = min_atr_pct
        self.rvol_lookback = rvol_lookback

    def screen_stock(
        self,
        symbol: str,
        candles: List[Candle],
        strike_step: int = 20
    ) -> Optional[StockSignal]:
        if len(candles) < 25:
            return None

        df = pd.DataFrame([{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles])

        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # 1. Volume analysis & RVOL
        avg_vol = df["volume"].iloc[:-1].tail(self.rvol_lookback).mean()
        current_vol = df["volume"].iloc[-1]
        rvol = current_vol / avg_vol if avg_vol > 0 else 1.0

        if rvol < self.min_rvol:
            return None # Insufficient relative volume surge

        # 2. ATR % calculation
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.tail(14).mean()
        current_price = df["close"].iloc[-1]
        atr_pct = (atr / current_price) * 100.0

        if atr_pct < self.min_atr_pct:
            return None # Low volatility / narrow range

        # 3. Consolidation breakout
        lookback_window = min(15, len(df) - 1)
        recent_high = df["high"].iloc[-lookback_window:-1].max()
        recent_low = df["low"].iloc[-lookback_window:-1].min()

        prev_close = df["close"].iloc[-2]
        atm_strike = round(round(current_price / strike_step) * strike_step, 1)

        # Bullish Breakout
        if current_price > recent_high and prev_close <= recent_high:
            reason = f"Surge Breakout: RVOL {rvol:.1f}x | ATR {atr_pct:.1f}% | Broke Resistance ₹{recent_high:.2f}"
            return StockSignal(
                symbol=symbol,
                direction="BUY_CALL",
                option_type="CE",
                spot_price=current_price,
                trigger_reason=reason,
                rvol=round(rvol, 2),
                atr_pct=round(atr_pct, 2),
                target_strike=atm_strike,
                is_swing_candidate=True
            )

        # Bearish Breakdown
        elif current_price < recent_low and prev_close >= recent_low:
            reason = f"Surge Breakdown: RVOL {rvol:.1f}x | ATR {atr_pct:.1f}% | Broke Support ₹{recent_low:.2f}"
            return StockSignal(
                symbol=symbol,
                direction="BUY_PUT",
                option_type="PE",
                spot_price=current_price,
                trigger_reason=reason,
                rvol=round(rvol, 2),
                atr_pct=round(atr_pct, 2),
                target_strike=atm_strike,
                is_swing_candidate=False
            )

        return None
