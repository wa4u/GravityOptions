import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Deque, Dict, List, Optional, Tuple
from src.utils.time_utils import get_now_ist


@dataclass
class StrikeFlowSnap:
    ce_oi: int
    ce_vol: int
    ce_ltp: float
    pe_oi: int
    pe_vol: int
    pe_ltp: float


@dataclass
class FlowIntervalBucket:
    timestamp: float
    net_tide_cr: float
    call_tide_cr: float
    put_tide_cr: float
    hedge_pressure_cr: float


@dataclass
class FlowMetrics:
    symbol: str
    snapshots_count: int = 0
    call_tide_cr: float = 0.0         # Cumulative signed Call premium (₹ Cr)
    put_tide_cr: float = 0.0          # Cumulative signed Put premium (₹ Cr)
    net_tide_cr: float = 0.0          # call_tide_cr - put_tide_cr
    recent_net_tide_cr: float = 0.0   # Rolling 15-minute Net Premium Tide (₹ Cr)
    hedge_pressure_cr: float = 0.0    # HIRO-style estimated writer hedge flow (₹ Cr)
    atm_ce_oi_delta: int = 0          # Snapshot-derived ATM Call OI delta
    atm_pe_oi_delta: int = 0          # Snapshot-derived ATM Put OI delta
    total_ce_oi_delta: int = 0        # Snapshot-derived total Call OI delta
    total_pe_oi_delta: int = 0        # Snapshot-derived total Put OI delta
    unusual_calls: List[float] = field(default_factory=list)
    unusual_puts: List[float] = field(default_factory=list)
    flow_bias: str = "NEUTRAL"        # "BULLISH", "BEARISH", or "NEUTRAL"


class IntradayFlowTracker:
    """
    Snapshot-diff Options Flow, Premium Tide, HIRO Hedge Pressure, and Unusual Activity tracker.
    Inspired by OptionHub's flow/derivePrints, premiumTide, hedgePressure, and unusual engines.
    Solves the Angel One static oi_change=0 limitation by diffing successive chain snapshots.
    """

    def __init__(self, min_interval_secs: float = 20.0, recent_window_secs: float = 900.0):
        self.min_interval_secs = min_interval_secs
        self.recent_window_secs = recent_window_secs
        self._session_date: Optional[date] = None
        self._last_snap_ts: Dict[str, float] = {}
        self._last_spot: Dict[str, float] = {}
        self._prev_strikes: Dict[str, Dict[float, StrikeFlowSnap]] = {}
        self._first_strikes: Dict[str, Dict[float, StrikeFlowSnap]] = {}
        self._buckets: Dict[str, Deque[FlowIntervalBucket]] = {}
        self._cum_tide: Dict[str, Tuple[float, float, float]] = {}  # (call_cr, put_cr, hedge_cr)
        self._latest_metrics: Dict[str, FlowMetrics] = {}

    def _reset_if_new_day(self, today: date):
        if self._session_date != today:
            self._session_date = today
            self._last_snap_ts.clear()
            self._last_spot.clear()
            self._prev_strikes.clear()
            self._first_strikes.clear()
            self._buckets.clear()
            self._cum_tide.clear()
            self._latest_metrics.clear()

    @staticmethod
    def _approx_delta(strike: float, spot: float, is_call: bool) -> float:
        """Fast monotonic delta proxy in [0.05, 0.95] when full Black-76 delta isn't attached."""
        if spot <= 0:
            return 0.5
        moneyness = (spot - strike) / spot
        # ~3% move spans 0.10 to 0.90 delta for short-dated NSE options
        raw = 0.5 + (moneyness / 0.04) * 0.4
        call_d = max(0.05, min(0.95, raw))
        return call_d if is_call else (call_d - 1.0)

    def update_snapshot(
        self,
        symbol: str,
        spot_price: float,
        strikes_data: list,
        atm_strike: float,
        now_ts: Optional[float] = None,
        today: Optional[date] = None
    ) -> FlowMetrics:
        """
        Ingest an option chain snapshot and return updated FlowMetrics.
        If called faster than min_interval_secs, returns the latest cached FlowMetrics.
        """
        sym = symbol.upper().strip()
        ts = now_ts if now_ts is not None else time.time()
        cur_date = today if today is not None else get_now_ist().date()
        self._reset_if_new_day(cur_date)

        # Rate-guard: avoid diffing identical cached snapshots every 5s
        last_ts = self._last_snap_ts.get(sym, 0.0)
        if last_ts > 0 and (ts - last_ts) < self.min_interval_secs:
            return self._latest_metrics.get(sym, FlowMetrics(symbol=sym))

        curr_map: Dict[float, StrikeFlowSnap] = {}
        unusual_calls: List[float] = []
        unusual_puts: List[float] = []

        for row in strikes_data:
            s = float(row.strike)
            curr_map[s] = StrikeFlowSnap(
                ce_oi=int(row.ce_oi),
                ce_vol=int(row.ce_volume),
                ce_ltp=float(row.ce_ltp),
                pe_oi=int(row.pe_oi),
                pe_vol=int(row.pe_volume),
                pe_ltp=float(row.pe_ltp),
            )
            # Unusual Activity check: Vol/OI >= 1.25 with meaningful volume
            if row.ce_volume >= 5000 and row.ce_oi > 0 and (row.ce_volume / row.ce_oi) >= 1.25:
                unusual_calls.append(s)
            if row.pe_volume >= 5000 and row.pe_oi > 0 and (row.pe_volume / row.pe_oi) >= 1.25:
                unusual_puts.append(s)

        if sym not in self._prev_strikes:
            # First snapshot of the session: initialize baseline
            self._prev_strikes[sym] = curr_map
            self._first_strikes[sym] = curr_map
            self._last_snap_ts[sym] = ts
            self._last_spot[sym] = spot_price
            self._buckets[sym] = deque(maxlen=240)
            self._cum_tide[sym] = (0.0, 0.0, 0.0)
            metrics = FlowMetrics(
                symbol=sym,
                snapshots_count=1,
                unusual_calls=unusual_calls,
                unusual_puts=unusual_puts,
            )
            self._latest_metrics[sym] = metrics
            return metrics

        prev_map = self._prev_strikes[sym]
        first_map = self._first_strikes[sym]
        prev_spot = self._last_spot.get(sym, spot_price)
        spot_up = spot_price > prev_spot
        spot_dn = spot_price < prev_spot

        interval_call_tide = 0.0
        interval_put_tide = 0.0
        interval_hedge = 0.0
        tot_ce_delta = 0
        tot_pe_delta = 0
        atm_ce_delta = 0
        atm_pe_delta = 0

        for s, cur in curr_map.items():
            # Session-relative OI change from first snapshot
            if s in first_map:
                f_snap = first_map[s]
                ce_sess_doi = cur.ce_oi - f_snap.ce_oi
                pe_sess_doi = cur.pe_oi - f_snap.pe_oi
                tot_ce_delta += ce_sess_doi
                tot_pe_delta += pe_sess_doi
                if s == atm_strike:
                    atm_ce_delta = ce_sess_doi
                    atm_pe_delta = pe_sess_doi

            prev = prev_map.get(s)
            if not prev:
                continue

            # Call interval print
            d_ce_vol = max(0, cur.ce_vol - prev.ce_vol)
            if d_ce_vol > 0 and cur.ce_ltp > 0:
                prem_cr = (d_ce_vol * cur.ce_ltp) / 1e7
                if cur.ce_ltp > prev.ce_ltp:
                    ce_side = 1.0
                elif cur.ce_ltp < prev.ce_ltp:
                    ce_side = -1.0
                else:
                    ce_side = 1.0 if spot_up else (-1.0 if spot_dn else 0.0)
                interval_call_tide += ce_side * prem_cr

            # Put interval print
            d_pe_vol = max(0, cur.pe_vol - prev.pe_vol)
            if d_pe_vol > 0 and cur.pe_ltp > 0:
                prem_cr = (d_pe_vol * cur.pe_ltp) / 1e7
                if cur.pe_ltp > prev.pe_ltp:
                    pe_side = 1.0
                elif cur.pe_ltp < prev.pe_ltp:
                    pe_side = -1.0
                else:
                    pe_side = 1.0 if spot_dn else (-1.0 if spot_up else 0.0)
                interval_put_tide += pe_side * prem_cr

            # HIRO-style writer hedge pressure from interval OI delta
            d_ce_oi = cur.ce_oi - prev.ce_oi
            d_pe_oi = cur.pe_oi - prev.pe_oi
            if d_ce_oi != 0:
                ce_delta = abs(self._approx_delta(s, spot_price, is_call=True))
                # Call writing (+d_ce_oi) -> writers short call -> must sell futures on rallies (-);
                # Call covering (-d_ce_oi) -> writers buy back (+)
                interval_hedge += (-d_ce_oi * ce_delta * spot_price) / 1e7
            if d_pe_oi != 0:
                pe_delta = abs(self._approx_delta(s, spot_price, is_call=False))
                # Put writing (+d_pe_oi) -> writers short put -> supportive delta (+)
                interval_hedge += (d_pe_oi * pe_delta * spot_price) / 1e7

        cum_call, cum_put, cum_hedge = self._cum_tide[sym]
        cum_call += interval_call_tide
        cum_put += interval_put_tide
        cum_hedge += interval_hedge
        self._cum_tide[sym] = (cum_call, cum_put, cum_hedge)

        buckets = self._buckets[sym]
        buckets.append(FlowIntervalBucket(
            timestamp=ts,
            net_tide_cr=interval_call_tide - interval_put_tide,
            call_tide_cr=interval_call_tide,
            put_tide_cr=interval_put_tide,
            hedge_pressure_cr=interval_hedge,
        ))

        cutoff = ts - self.recent_window_secs
        recent_net_tide = sum(b.net_tide_cr for b in buckets if b.timestamp >= cutoff)
        net_tide = cum_call - cum_put

        # Determine flow bias from recent tide (preferred) or cumulative tide
        ref_tide = recent_net_tide if abs(recent_net_tide) > 0.05 else net_tide
        if ref_tide >= 0.25:
            flow_bias = "BULLISH"
        elif ref_tide <= -0.25:
            flow_bias = "BEARISH"
        else:
            flow_bias = "NEUTRAL"

        self._prev_strikes[sym] = curr_map
        self._last_snap_ts[sym] = ts
        self._last_spot[sym] = spot_price

        prev_count = self._latest_metrics[sym].snapshots_count if sym in self._latest_metrics else 1
        metrics = FlowMetrics(
            symbol=sym,
            snapshots_count=prev_count + 1,
            call_tide_cr=round(cum_call, 3),
            put_tide_cr=round(cum_put, 3),
            net_tide_cr=round(net_tide, 3),
            recent_net_tide_cr=round(recent_net_tide, 3),
            hedge_pressure_cr=round(cum_hedge, 3),
            atm_ce_oi_delta=atm_ce_delta,
            atm_pe_oi_delta=atm_pe_delta,
            total_ce_oi_delta=tot_ce_delta,
            total_pe_oi_delta=tot_pe_delta,
            unusual_calls=unusual_calls,
            unusual_puts=unusual_puts,
            flow_bias=flow_bias,
        )
        self._latest_metrics[sym] = metrics
        return metrics
