import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple, Any
from src.utils.logger import log

@dataclass
class StrikeOIData:
    strike: float
    ce_symbol: str
    ce_token: str
    ce_oi: int
    ce_ltp: float
    pe_symbol: str
    pe_token: str
    pe_oi: int
    pe_ltp: float

@dataclass
class OIAnalysisResult:
    symbol: str
    spot_price: float
    pcr: float
    total_call_oi: int
    total_put_oi: int
    call_wall: float          # Major Resistance: Strike with maximum Call OI
    call_wall_oi: int
    put_wall: float           # Major Support: Strike with maximum Put OI
    put_wall_oi: int
    max_pain: float           # Theoretical expiry gravitational strike
    sentiment: str            # "BULLISH", "BEARISH", or "NEUTRAL"
    strikes_data: List[StrikeOIData] = field(default_factory=list)
    is_valid: bool = False
    timestamp: float = 0.0

class OIAnalyzer:
    """
    Analyzes Option Chain dynamics, Open Interest (OI), Put-Call Ratio (PCR),
    Max Pain, and institutional Support/Resistance Walls for Indian derivatives.
    """
    def __init__(self, feed, instrument_mgr, cache_ttl: float = 60.0):
        self.feed = feed
        self.instrument_mgr = instrument_mgr
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, OIAnalysisResult] = {}

    def analyze_symbol(
        self,
        symbol: str,
        spot_price: float,
        num_strikes: int = 5,
        force: bool = False
    ) -> OIAnalysisResult:
        """
        Fetches live option chain market data for ATM ± num_strikes strikes,
        calculates PCR, Call Wall, Put Wall, and Max Pain.
        """
        sym_upper = symbol.upper().strip()
        now_ts = time.time()

        # Check cache
        if not force and sym_upper in self._cache:
            cached = self._cache[sym_upper]
            if now_ts - cached.timestamp < self.cache_ttl:
                return cached

        default_result = OIAnalysisResult(
            symbol=sym_upper,
            spot_price=spot_price,
            pcr=1.0,
            total_call_oi=0,
            total_put_oi=0,
            call_wall=0.0,
            call_wall_oi=0,
            put_wall=0.0,
            put_wall_oi=0,
            max_pain=spot_price,
            sentiment="NEUTRAL",
            is_valid=False,
            timestamp=now_ts
        )

        if not self.instrument_mgr or not self.feed:
            return default_result

        # 1. Resolve contract symbols & tokens for ATM ± num_strikes
        chain_info = self.instrument_mgr.get_option_chain_contracts(sym_upper, spot_price, num_strikes=num_strikes)
        tokens_by_exch = chain_info.get("tokens_by_exchange", {})
        contracts = chain_info.get("contracts", {})
        strikes = chain_info.get("strikes", [])

        if not tokens_by_exch or not any(tokens_by_exch.values()):
            return default_result

        # 2. Query batch market data from feed in FULL mode
        market_data = self.feed.get_market_data("FULL", tokens_by_exch)
        fetched_items = market_data.get("fetched", []) if isinstance(market_data, dict) else []

        if not fetched_items:
            return default_result

        # 3. Map tokens to OI and LTP
        token_stats: Dict[str, Dict[str, float]] = {}
        for item in fetched_items:
            tok = str(item.get("symbolToken", item.get("token", "")))
            if tok:
                token_stats[tok] = {
                    "oi": int(item.get("openInterest", item.get("opnInterest", 0)) or 0),
                    "ltp": float(item.get("ltp", 0.0) or 0.0)
                }

        strikes_data: List[StrikeOIData] = []
        total_call_oi = 0
        total_put_oi = 0
        max_call_oi = -1
        max_put_oi = -1
        call_wall = 0.0
        put_wall = 0.0

        for s in strikes:
            ce_item = contracts.get(s, {}).get("CE", {})
            pe_item = contracts.get(s, {}).get("PE", {})

            ce_tok = str(ce_item.get("token", ""))
            pe_tok = str(pe_item.get("token", ""))

            ce_stat = token_stats.get(ce_tok, {"oi": 0, "ltp": 0.0})
            pe_stat = token_stats.get(pe_tok, {"oi": 0, "ltp": 0.0})

            ce_oi = ce_stat["oi"]
            pe_oi = pe_stat["oi"]

            total_call_oi += ce_oi
            total_put_oi += pe_oi

            if ce_oi > max_call_oi:
                max_call_oi = ce_oi
                call_wall = s

            if pe_oi > max_put_oi:
                max_put_oi = pe_oi
                put_wall = s

            strikes_data.append(StrikeOIData(
                strike=s,
                ce_symbol=ce_item.get("symbol", ""),
                ce_token=ce_tok,
                ce_oi=ce_oi,
                ce_ltp=ce_stat["ltp"],
                pe_symbol=pe_item.get("symbol", ""),
                pe_token=pe_tok,
                pe_oi=pe_oi,
                pe_ltp=pe_stat["ltp"]
            ))

        # Check if we got meaningful OI data
        if total_call_oi <= 0 and total_put_oi <= 0:
            return default_result

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

        # 4. Calculate Max Pain
        # Loss(S) = sum(max(0, S - K) * Call_OI(K)) + sum(max(0, K - S) * Put_OI(K))
        min_loss = float("inf")
        max_pain_strike = spot_price

        for s_candidate in strikes:
            total_loss = 0.0
            for row in strikes_data:
                # Calls ITM when candidate strike > call strike
                if s_candidate > row.strike:
                    total_loss += (s_candidate - row.strike) * row.ce_oi
                # Puts ITM when candidate strike < put strike
                if s_candidate < row.strike:
                    total_loss += (row.strike - s_candidate) * row.pe_oi

            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = s_candidate

        # 5. Determine Sentiment
        if pcr >= 1.05:
            sentiment = "BULLISH"
        elif pcr <= 0.85:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        res = OIAnalysisResult(
            symbol=sym_upper,
            spot_price=spot_price,
            pcr=pcr,
            total_call_oi=total_call_oi,
            total_put_oi=total_put_oi,
            call_wall=call_wall,
            call_wall_oi=max_call_oi,
            put_wall=put_wall,
            put_wall_oi=max_put_oi,
            max_pain=max_pain_strike,
            sentiment=sentiment,
            strikes_data=strikes_data,
            is_valid=True,
            timestamp=now_ts
        )

        self._cache[sym_upper] = res
        return res

    def validate_signal(
        self,
        direction: str,
        spot_price: float,
        oi_result: OIAnalysisResult,
        min_pcr_call: float = 0.90,
        max_pcr_put: float = 1.15,
        min_wall_dist: float = 25.0
    ) -> Tuple[bool, str]:
        """
        Validates breakout signals against Open Interest and PCR filters.
        Prevents buying calls into heavy call resistance or puts into put support.
        """
        if not oi_result or not oi_result.is_valid:
            # Fallback when OI data is temporarily unavailable or out of session
            return True, "OI data unavailable; bypassed validation"

        pcr = oi_result.pcr

        if direction == "BUY_CALL":
            # 1. PCR Check
            if pcr < min_pcr_call:
                return False, f"Bearish PCR trap ({pcr:.2f} < {min_pcr_call:.2f}): Heavy Call Writing dominates"

            # 2. Call Wall Resistance Check
            if spot_price < oi_result.call_wall:
                distance = oi_result.call_wall - spot_price
                if distance < min_wall_dist:
                    return False, f"Near Call Wall resistance ₹{oi_result.call_wall:,.0f} ({distance:.1f} pts away)"

            return True, f"OI Confirmed: PCR {pcr:.2f} | Put Wall ₹{oi_result.put_wall:,.0f} | Call Wall ₹{oi_result.call_wall:,.0f}"

        elif direction == "BUY_PUT":
            # 1. PCR Check
            if pcr > max_pcr_put:
                return False, f"Bullish PCR trap ({pcr:.2f} > {max_pcr_put:.2f}): Heavy Put Writing dominates"

            # 2. Put Wall Support Check
            if spot_price > oi_result.put_wall:
                distance = spot_price - oi_result.put_wall
                if distance < min_wall_dist:
                    return False, f"Near Put Wall support ₹{oi_result.put_wall:,.0f} ({distance:.1f} pts away)"

            return True, f"OI Confirmed: PCR {pcr:.2f} | Put Wall ₹{oi_result.put_wall:,.0f} | Call Wall ₹{oi_result.call_wall:,.0f}"

        return True, "OK"
