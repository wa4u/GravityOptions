from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from src.data.base_feed import Candle
from src.utils.logger import log

@dataclass
class IndexSignal:
    symbol: str
    direction: str       # "BUY_CALL" or "BUY_PUT"
    option_type: str     # "CE" or "PE"
    spot_price: float
    trigger_reason: str
    target_strike: float
    delta_estimate: float

class IndexScreener:
    """
    Screens Indian Indices (NIFTY, BANKNIFTY, SENSEX, FINNIFTY)
    using 15-min Opening Range Breakout (ORB) + VWAP Slope + EMA Trend.
    """
    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, atr_period: int = 14):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period

    def calculate_indicators(self, candles: List[Candle]) -> pd.DataFrame:
        if len(candles) < 5:
            return pd.DataFrame()

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

        # Exponential Moving Averages
        df["ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()

        # Intraday VWAP: Calculate strictly on today's session (or latest day in dataset)
        df["date_only"] = df["timestamp"].apply(lambda x: x.date() if hasattr(x, "date") else x)
        latest_date = df["date_only"].iloc[-1]
        today_mask = df["date_only"] == latest_date

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        df["vwap"] = typical_price # Default baseline

        today_indices = df[today_mask].index
        today_vol = df.loc[today_indices, "volume"]
        today_tp = typical_price.loc[today_indices]

        if today_vol.sum() > 0:
            cum_vol = today_vol.cumsum()
            cum_pv = (today_tp * today_vol).cumsum()
            df.loc[today_indices, "vwap"] = cum_pv / cum_vol.replace(0, np.nan)
        else:
            # Fallback for cash index with 0 reported volume: expanding typical price mean
            df.loc[today_indices, "vwap"] = today_tp.expanding().mean()

        df["vwap"] = df["vwap"].ffill().bfill()

        # Average True Range (ATR)
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - df["close"].shift(1)).abs()
        low_prev_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(min(self.atr_period, len(df))).mean()

        return df

    def evaluate_orb_setup(
        self,
        symbol: str,
        candles: List[Candle],
        strike_step: int = 50,
        strike_mode: str = "deep_itm",
        itm_depth: int = 2
    ) -> Optional[IndexSignal]:
        """
        Check for 15-minute Opening Range Breakout strictly using TODAY's opening range
        with VWAP and EMA confirmation. Evaluates strictly on COMPLETED (closed) 5m bars.
        """
        df = self.calculate_indicators(candles)
        if df.empty or len(df) < 5:
            return None

        # Filter strictly for today's session
        from src.utils.time_utils import get_now_ist
        now = get_now_ist()
        today_date = now.date()
        latest_date = df["date_only"].iloc[-1]
        
        # Guard: Ensure candle data contains today's actual trading session
        if latest_date != today_date:
            log.warning(f"Index candles for {symbol} do not contain today's date ({today_date}). Latest is {latest_date}. Skipping.")
            return None

        today_df = df[df["date_only"] == today_date].copy()

        # Must have completed the 15-minute opening range (3 x 5m bars) plus at least 1 active bar
        if len(today_df) < 4:
            return None

        # Morning Opening Range: First 3 bars of 5m (09:15 - 09:30 IST)
        orb_bars = today_df.iloc[0:3]
        orb_high = orb_bars["high"].max()
        orb_low = orb_bars["low"].min()

        # Strict Closed Bar Check:
        # Determine whether the latest row in today_df is a completed bar or still forming
        last_candle_ts = today_df.iloc[-1]["timestamp"]
        if hasattr(last_candle_ts, "tzinfo") and last_candle_ts.tzinfo is not None:
            age_secs = (now - last_candle_ts).total_seconds()
        else:
            age_secs = (now.replace(tzinfo=None) - last_candle_ts).total_seconds()

        # If the latest 5m candle has been open for less than 285s (4m 45s), it is still forming!
        # In that case, evaluate strictly on the last completed bar (today_df.iloc[-2])
        if age_secs < 285 and len(today_df) >= 5:
            eval_row = today_df.iloc[-2]
            prev_row = today_df.iloc[-3]
        else:
            eval_row = today_df.iloc[-1]
            prev_row = today_df.iloc[-2]

        current_close = eval_row["close"]
        current_open = eval_row["open"]
        prev_close = prev_row["close"]
        vwap = eval_row["vwap"]
        ema_f = eval_row["ema_fast"]
        ema_s = eval_row["ema_slow"]

        # Small 0.05% buffer (~12 pts Nifty / ~28 pts Bank Nifty) to eliminate false wick sweeps
        buffer = 0.0005

        # Base ATM strike rounded to nearest step
        atm_strike = round(round(current_close / strike_step) * strike_step, 1)

        # Bullish Breakout: Decisive closed green candle above today's ORB High, above VWAP, EMA Bullish
        if (current_close > (orb_high * (1.0 + buffer)) and prev_close <= orb_high and 
            current_close > current_open and current_close > vwap and ema_f > ema_s):
            
            # Strike Selection: Deep ITM (ITM 2, Delta ~0.75) vs ATM (Delta ~0.50)
            if strike_mode.lower() == "deep_itm":
                target_strike = atm_strike - (itm_depth * strike_step)
                delta_est = 0.75
                depth_label = f"Deep ITM ({itm_depth} strikes)"
            else:
                target_strike = atm_strike
                delta_est = 0.55
                depth_label = "ATM"

            reason = f"Bullish Breakout: Closed Bar > ORB High ₹{orb_high:.1f} | Close > VWAP ₹{vwap:.1f} | EMA Bullish ({depth_label})"
            return IndexSignal(
                symbol=symbol,
                direction="BUY_CALL",
                option_type="CE",
                spot_price=current_close,
                trigger_reason=reason,
                target_strike=target_strike,
                delta_estimate=delta_est
            )

        # Bearish Breakdown: Decisive closed red candle below today's ORB Low, below VWAP, EMA Bearish
        elif (current_close < (orb_low * (1.0 - buffer)) and prev_close >= orb_low and 
              current_close < current_open and current_close < vwap and ema_f < ema_s):
            
            # Strike Selection: Deep ITM (ITM 2, Delta ~ -0.75) vs ATM (Delta ~ -0.50)
            if strike_mode.lower() == "deep_itm":
                target_strike = atm_strike + (itm_depth * strike_step)
                delta_est = -0.75
                depth_label = f"Deep ITM ({itm_depth} strikes)"
            else:
                target_strike = atm_strike
                delta_est = -0.55
                depth_label = "ATM"

            reason = f"Bearish Breakdown: Closed Bar < ORB Low ₹{orb_low:.1f} | Close < VWAP ₹{vwap:.1f} | EMA Bearish ({depth_label})"
            return IndexSignal(
                symbol=symbol,
                direction="BUY_PUT",
                option_type="PE",
                spot_price=current_close,
                trigger_reason=reason,
                target_strike=target_strike,
                delta_estimate=delta_est
            )

        return None
