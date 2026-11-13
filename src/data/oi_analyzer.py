import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple, Any
from src.utils.logger import log
from src.utils.greeks import calculate_greeks

LOT_SIZES: Dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "SENSEX": 10,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
}

@dataclass
class StrikeOIData:
    strike: float
    ce_symbol: str
    ce_token: str
    ce_oi: int
    ce_oi_change: int
    ce_volume: int
    ce_ltp: float
    ce_net_change: float
    ce_buildup: str           # "LONG_BUILDUP", "SHORT_COVERING", "SHORT_BUILDUP", "LONG_UNWINDING"
    pe_symbol: str
    pe_token: str
    pe_oi: int
    pe_oi_change: int
    pe_volume: int
    pe_ltp: float
    pe_net_change: float
    pe_buildup: str
    ce_gamma: float = 0.0
    pe_gamma: float = 0.0
    call_gex: float = 0.0     # ₹ Cr per 1% move
    put_gex: float = 0.0      # ₹ Cr per 1% move
    net_gex: float = 0.0      # ₹ Cr per 1% move

def classify_buildup(price_change: float, oi_change: int) -> str:
    """Classifies derivative state into the 4 institutional money-flow quadrants."""
    if price_change > 0 and oi_change > 0:
        return "LONG_BUILDUP"
    elif price_change > 0 and oi_change < 0:
        return "SHORT_COVERING"
    elif price_change < 0 and oi_change > 0:
        return "SHORT_BUILDUP"
    elif price_change < 0 and oi_change < 0:
        return "LONG_UNWINDING"
    return "NEUTRAL"

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
    # Institutional Order Flow & Build-Up extensions (MrChartist methodology)
    net_oi_flow: str = "NEUTRAL"          # "LONG_BUILDUP", "SHORT_BUILDUP", "SHORT_COVERING", "LONG_UNWINDING"
    atm_strike: float = 0.0
    atm_call_buildup: str = "NEUTRAL"
    atm_put_buildup: str = "NEUTRAL"
    atm_call_oi_change: int = 0
    atm_put_oi_change: int = 0
    total_call_oi_change: int = 0
    total_put_oi_change: int = 0
    conviction_score: int = 50            # 0 - 100 Institutional Conviction
    conviction_summary: str = ""
    # Dealer Gamma Exposure (GEX) extensions (Option Hub / SpotGamma methodology)
    total_call_gex: float = 0.0           # ₹ Cr per 1% move
    total_put_gex: float = 0.0            # ₹ Cr per 1% move
    total_net_gex: float = 0.0            # ₹ Cr per 1% move
    gamma_regime: str = "NEUTRAL"         # "POSITIVE_GAMMA" (volatility dampener/chop) or "NEGATIVE_GAMMA" (breakout accelerator)
    gamma_flip_level: Optional[float] = None # Price level where net GEX crosses 0

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

    def calculate_gex_profile(
        self,
        symbol: str,
        spot_price: float,
        strikes_data: List[StrikeOIData],
        lot_size: Optional[int] = None,
        time_to_expiry_years: float = 3.0 / 365.0,
        default_iv: float = 0.15
    ) -> Tuple[float, float, float, str, Optional[float]]:
        """
        Calculates Dealer Gamma Exposure (GEX) across option chain strikes.
        Returns: (total_call_gex, total_put_gex, total_net_gex, gamma_regime, gamma_flip_level)
        Units: ₹ Crore per 1% move in spot price (Option Hub convention).
        """
        if not strikes_data or spot_price <= 0:
            return 0.0, 0.0, 0.0, "NEUTRAL", None

        ls = lot_size or LOT_SIZES.get(symbol.upper(), 25)
        scale = (spot_price * spot_price * 0.01) / 1e7 # Spot^2 * 1% / 10^7 = ₹ Crore

        tot_call_gex = 0.0
        tot_put_gex = 0.0

        for row in strikes_data:
            k = row.strike
            # Black-Scholes Greeks
            ce_g = calculate_greeks(spot_price, k, time_to_expiry_years, default_iv, option_type="CE")
            pe_g = calculate_greeks(spot_price, k, time_to_expiry_years, default_iv, option_type="PE")

            row.ce_gamma = ce_g.get("gamma", 0.0)
            row.pe_gamma = pe_g.get("gamma", 0.0)

            # Call GEX: Dealer Long Call -> positive gamma
            row.call_gex = 1.0 * row.ce_gamma * row.ce_oi * ls * scale
            # Put GEX: Dealer Short Put -> negative gamma
            row.put_gex = -1.0 * row.pe_gamma * row.pe_oi * ls * scale
            row.net_gex = row.call_gex + row.put_gex

            tot_call_gex += row.call_gex
            tot_put_gex += row.put_gex

        tot_net_gex = tot_call_gex + tot_put_gex

        # Determine Gamma Regime
        threshold = max(2.0, (spot_price / 10000.0) * 2.0)
        if tot_net_gex > threshold:
            regime = "POSITIVE_GAMMA"
        elif tot_net_gex < -threshold:
            regime = "NEGATIVE_GAMMA"
        else:
            regime = "NEUTRAL"

        # Find Zero-Gamma Flip level
        flip_level = None
        sorted_rows = sorted(strikes_data, key=lambda r: r.strike)
        for i, r in enumerate(sorted_rows):
            if abs(r.net_gex) < 1e-3:
                flip_level = r.strike
                break
            if i < len(sorted_rows) - 1:
                r_next = sorted_rows[i + 1]
                if (r.net_gex < 0 and r_next.net_gex > 0) or (r.net_gex > 0 and r_next.net_gex < 0):
                    denom = r_next.net_gex - r.net_gex
                    if abs(denom) > 1e-6:
                        flip_level = r.strike + ((0.0 - r.net_gex) / denom) * (r_next.strike - r.strike)
                        break

        return round(tot_call_gex, 2), round(tot_put_gex, 2), round(tot_net_gex, 2), regime, (round(flip_level, 1) if flip_level else None)

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

        if not self.feed:
            return default_result

        # Check if feed supports native unified Option Chain (e.g. DhanHQ)
        if hasattr(self.feed, "get_option_chain") and getattr(self.feed, "is_connected", False):
            dhan_oc = self.feed.get_option_chain(sym_upper)
            oc_dict = dhan_oc.get("oc", {}) if isinstance(dhan_oc, dict) else {}
            if oc_dict:
                return self._parse_dhan_option_chain(sym_upper, spot_price, oc_dict, num_strikes)

        if not self.instrument_mgr:
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

        # 3. Map tokens to OI, volume, and price changes
        token_stats: Dict[str, Dict[str, Any]] = {}
        for item in fetched_items:
            tok = str(item.get("symbolToken", item.get("token", "")))
            if tok:
                token_stats[tok] = {
                    "oi": int(item.get("openInterest", item.get("opnInterest", 0)) or 0),
                    "oi_change": int(item.get("opnInterestChange", item.get("changeInOpenInterest", 0)) or 0),
                    "volume": int(item.get("tradeVolume", item.get("volume", 0)) or 0),
                    "ltp": float(item.get("ltp", 0.0) or 0.0),
                    "net_change": float(item.get("netChange", item.get("pChange", 0.0)) or 0.0)
                }

        strikes_data: List[StrikeOIData] = []
        total_call_oi = 0
        total_put_oi = 0
        total_call_oi_change = 0
        total_put_oi_change = 0
        max_call_oi = -1
        max_put_oi = -1
        call_wall = 0.0
        put_wall = 0.0

        for s in strikes:
            ce_item = contracts.get(s, {}).get("CE", {})
            pe_item = contracts.get(s, {}).get("PE", {})

            ce_tok = str(ce_item.get("token", ""))
            pe_tok = str(pe_item.get("token", ""))

            ce_stat = token_stats.get(ce_tok, {"oi": 0, "oi_change": 0, "volume": 0, "ltp": 0.0, "net_change": 0.0})
            pe_stat = token_stats.get(pe_tok, {"oi": 0, "oi_change": 0, "volume": 0, "ltp": 0.0, "net_change": 0.0})

            ce_oi = ce_stat["oi"]
            pe_oi = pe_stat["oi"]
            ce_chg = ce_stat["oi_change"]
            pe_chg = pe_stat["oi_change"]

            total_call_oi += ce_oi
            total_put_oi += pe_oi
            total_call_oi_change += ce_chg
            total_put_oi_change += pe_chg

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
                ce_oi_change=ce_stat["oi_change"],
                ce_volume=ce_stat["volume"],
                ce_ltp=ce_stat["ltp"],
                ce_net_change=ce_stat["net_change"],
                ce_buildup=classify_buildup(ce_stat["net_change"], ce_stat["oi_change"]),
                pe_symbol=pe_item.get("symbol", ""),
                pe_token=pe_tok,
                pe_oi=pe_oi,
                pe_oi_change=pe_stat["oi_change"],
                pe_volume=pe_stat["volume"],
                pe_ltp=pe_stat["ltp"],
                pe_net_change=pe_stat["net_change"],
                pe_buildup=classify_buildup(pe_stat["net_change"], pe_stat["oi_change"])
            ))

        # Check if we got meaningful OI data
        if total_call_oi <= 0 and total_put_oi <= 0:
            return default_result

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

        # 4. Calculate Max Pain
        min_loss = float("inf")
        max_pain_strike = spot_price

        for s_candidate in strikes:
            total_loss = 0.0
            for row in strikes_data:
                if s_candidate > row.strike:
                    total_loss += (s_candidate - row.strike) * row.ce_oi
                if s_candidate < row.strike:
                    total_loss += (row.strike - s_candidate) * row.pe_oi

            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = s_candidate

        # 5. Determine Sentiment & Institutional Order Flow
        if pcr >= 1.05:
            sentiment = "BULLISH"
        elif pcr <= 0.85:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        # ATM Strike detection
        atm_strike = min(strikes, key=lambda s: abs(s - spot_price)) if strikes else spot_price
        atm_row = next((r for r in strikes_data if r.strike == atm_strike), None)
        atm_call_buildup = atm_row.ce_buildup if atm_row else "NEUTRAL"
        atm_put_buildup = atm_row.pe_buildup if atm_row else "NEUTRAL"
        atm_call_oi_change = atm_row.ce_oi_change if atm_row else 0
        atm_put_oi_change = atm_row.pe_oi_change if atm_row else 0

        # Overall Net Order Flow (Bulls vs Bears)
        net_writer_flow = total_put_oi_change - total_call_oi_change
        if net_writer_flow > 50000:
            net_oi_flow = "LONG_BUILDUP"
        elif net_writer_flow < -50000:
            net_oi_flow = "SHORT_BUILDUP"
        elif total_call_oi_change < -20000 and total_put_oi_change <= 0:
            net_oi_flow = "SHORT_COVERING"
        elif total_put_oi_change < -20000 and total_call_oi_change <= 0:
            net_oi_flow = "LONG_UNWINDING"
        else:
            net_oi_flow = "NEUTRAL"

        # GEX Calculation
        tot_call_gex, tot_put_gex, tot_net_gex, gamma_regime, flip_level = self.calculate_gex_profile(
            sym_upper, spot_price, strikes_data
        )

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
            timestamp=now_ts,
            net_oi_flow=net_oi_flow,
            atm_strike=atm_strike,
            atm_call_buildup=atm_call_buildup,
            atm_put_buildup=atm_put_buildup,
            atm_call_oi_change=atm_call_oi_change,
            atm_put_oi_change=atm_put_oi_change,
            total_call_oi_change=total_call_oi_change,
            total_put_oi_change=total_put_oi_change,
            total_call_gex=tot_call_gex,
            total_put_gex=tot_put_gex,
            total_net_gex=tot_net_gex,
            gamma_regime=gamma_regime,
            gamma_flip_level=flip_level
        )

        self._cache[sym_upper] = res
        return res

    def _parse_dhan_option_chain(
        self,
        symbol: str,
        spot_price: float,
        oc_dict: Dict[str, Any],
        num_strikes: int = 5
    ) -> OIAnalysisResult:
        """Parses native DhanHQ Option Chain dictionary into OIAnalysisResult."""
        now_ts = time.time()
        parsed_strikes = []
        for k_str, data in oc_dict.items():
            try:
                s_val = float(k_str)
                parsed_strikes.append((s_val, data))
            except (ValueError, TypeError):
                continue

        if not parsed_strikes:
            return OIAnalysisResult(symbol=symbol, spot_price=spot_price, pcr=1.0, total_call_oi=0, total_put_oi=0,
                                    call_wall=0.0, call_wall_oi=0, put_wall=0.0, put_wall_oi=0, max_pain=spot_price,
                                    sentiment="NEUTRAL", is_valid=False, timestamp=now_ts)

        parsed_strikes.sort(key=lambda x: x[0])
        # Find ATM strike
        atm_strike = min([s for s, _ in parsed_strikes], key=lambda s: abs(s - spot_price))
        atm_idx = next(i for i, (s, _) in enumerate(parsed_strikes) if s == atm_strike)

        start_idx = max(0, atm_idx - num_strikes)
        end_idx = min(len(parsed_strikes), atm_idx + num_strikes + 1)
        selected = parsed_strikes[start_idx:end_idx]

        strikes_data: List[StrikeOIData] = []
        total_call_oi = 0
        total_put_oi = 0
        total_call_oi_change = 0
        total_put_oi_change = 0
        max_call_oi = -1
        max_put_oi = -1
        call_wall = 0.0
        put_wall = 0.0

        for s, row in selected:
            ce = row.get("ce", {}) or {}
            pe = row.get("pe", {}) or {}

            ce_oi = int(ce.get("oi", 0) or 0)
            pe_oi = int(pe.get("oi", 0) or 0)
            ce_chg = int(ce.get("change_in_oi", ce.get("oi_change", 0)) or 0)
            pe_chg = int(pe.get("change_in_oi", pe.get("oi_change", 0)) or 0)
            ce_vol = int(ce.get("volume", 0) or 0)
            pe_vol = int(pe.get("volume", 0) or 0)
            ce_ltp = float(ce.get("last_price", 0.0) or 0.0)
            pe_ltp = float(pe.get("last_price", 0.0) or 0.0)
            ce_p_chg = float(ce.get("net_change", ce.get("change", 0.0)) or 0.0)
            pe_p_chg = float(pe.get("net_change", pe.get("change", 0.0)) or 0.0)

            total_call_oi += ce_oi
            total_put_oi += pe_oi
            total_call_oi_change += ce_chg
            total_put_oi_change += pe_chg

            if ce_oi > max_call_oi:
                max_call_oi = ce_oi
                call_wall = s
            if pe_oi > max_put_oi:
                max_put_oi = pe_oi
                put_wall = s

            strikes_data.append(StrikeOIData(
                strike=s,
                ce_symbol=f"{symbol}_{int(s)}_CE",
                ce_token=str(ce.get("security_id", "")),
                ce_oi=ce_oi,
                ce_oi_change=ce_chg,
                ce_volume=ce_vol,
                ce_ltp=ce_ltp,
                ce_net_change=ce_p_chg,
                ce_buildup=classify_buildup(ce_p_chg, ce_chg),
                pe_symbol=f"{symbol}_{int(s)}_PE",
                pe_token=str(pe.get("security_id", "")),
                pe_oi=pe_oi,
                pe_oi_change=pe_chg,
                pe_volume=pe_vol,
                pe_ltp=pe_ltp,
                pe_net_change=pe_p_chg,
                pe_buildup=classify_buildup(pe_p_chg, pe_chg)
            ))

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

        min_loss = float("inf")
        max_pain_strike = spot_price
        for s_cand, _ in selected:
            tot_loss = sum(max(0, s_cand - r.strike) * r.ce_oi + max(0, r.strike - s_cand) * r.pe_oi for r in strikes_data)
            if tot_loss < min_loss:
                min_loss = tot_loss
                max_pain_strike = s_cand

        sentiment = "BULLISH" if pcr >= 1.05 else ("BEARISH" if pcr <= 0.85 else "NEUTRAL")

        atm_row = next((r for r in strikes_data if r.strike == atm_strike), None)
        atm_call_buildup = atm_row.ce_buildup if atm_row else "NEUTRAL"
        atm_put_buildup = atm_row.pe_buildup if atm_row else "NEUTRAL"
        atm_call_oi_change = atm_row.ce_oi_change if atm_row else 0
        atm_put_oi_change = atm_row.pe_oi_change if atm_row else 0

        net_writer_flow = total_put_oi_change - total_call_oi_change
        if net_writer_flow > 50000:
            net_oi_flow = "LONG_BUILDUP"
        elif net_writer_flow < -50000:
            net_oi_flow = "SHORT_BUILDUP"
        elif total_call_oi_change < -20000 and total_put_oi_change <= 0:
            net_oi_flow = "SHORT_COVERING"
        elif total_put_oi_change < -20000 and total_call_oi_change <= 0:
            net_oi_flow = "LONG_UNWINDING"
        else:
            net_oi_flow = "NEUTRAL"

        # GEX Calculation
        tot_call_gex, tot_put_gex, tot_net_gex, gamma_regime, flip_level = self.calculate_gex_profile(
            symbol, spot_price, strikes_data
        )

        res = OIAnalysisResult(
            symbol=symbol,
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
            timestamp=now_ts,
            net_oi_flow=net_oi_flow,
            atm_strike=atm_strike,
            atm_call_buildup=atm_call_buildup,
            atm_put_buildup=atm_put_buildup,
            atm_call_oi_change=atm_call_oi_change,
            atm_put_oi_change=atm_put_oi_change,
            total_call_oi_change=total_call_oi_change,
            total_put_oi_change=total_put_oi_change,
            total_call_gex=tot_call_gex,
            total_put_gex=tot_put_gex,
            total_net_gex=tot_net_gex,
            gamma_regime=gamma_regime,
            gamma_flip_level=flip_level
        )
        self._cache[symbol] = res
        return res

    def validate_signal(
        self,
        direction: str,
        spot_price: float,
        oi_result: OIAnalysisResult,
        min_pcr_call: float = 0.90,
        max_pcr_put: float = 1.15,
        min_wall_dist: float = 25.0,
        min_conviction_score: int = 55,
        participant_tracker: Optional[Any] = None
    ) -> Tuple[bool, str]:
        """
        Validates breakout signals using the Multi-Pillar Institutional Conviction Model (Option Hub):
        1. Put-Call Ratio (PCR) Institutional Sentiment (0 - 25 pts)
        2. ATM Strike Option Writer Dynamics (0 - 30 pts)
        3. Strike Build-Up Quadrant (0 - 25 pts)
        4. Wall Resistance / Support Clearance (0 - 20 pts)
        5. Dealer Gamma Exposure (GEX) Regime (-10 to +15 pts)
        6. Macro Institutional Participant Bias (NSE FII Tracker) (-10 to +15 pts)
        Total Score: 0 to 100. Requires >= min_conviction_score to open trade.
        """
        if not oi_result or not oi_result.is_valid:
            # Fallback when OI data is temporarily unavailable or out of session
            return True, "OI data unavailable; bypassed validation"

        pcr = oi_result.pcr
        score = 0
        reasons = []

        is_call = direction.upper() in ["BUY_CALL", "CE", "CALL"]

        if is_call:
            # Pillar 1: PCR Sentiment (Max 25 pts)
            if pcr >= 1.20:
                score += 25
                reasons.append(f"Heavy Put Writing Base (PCR {pcr:.2f})")
            elif pcr >= 1.00:
                score += 20
                reasons.append(f"Bullish PCR ({pcr:.2f})")
            elif pcr >= min_pcr_call:
                score += 12
                reasons.append(f"Mild Bullish PCR ({pcr:.2f})")
            else:
                score += 0
                reasons.append(f"Bearish PCR Trap ({pcr:.2f} < {min_pcr_call:.2f})")

            # Pillar 2: ATM Strike Writer Dynamics (Max 30 pts)
            writer_pts = 0
            if oi_result.atm_call_oi_change < 0:
                writer_pts += 15
                reasons.append(f"Call Writers Retreating ({oi_result.atm_call_oi_change:+,d})")
            elif oi_result.atm_call_oi_change == 0:
                writer_pts += 8
            else:
                reasons.append(f"Call Writers Defending ATM ({oi_result.atm_call_oi_change:+,d})")

            if oi_result.atm_put_oi_change > 0:
                writer_pts += 15
                reasons.append(f"Put Writers Loading Support ({oi_result.atm_put_oi_change:+,d})")
            elif oi_result.atm_put_oi_change == 0:
                writer_pts += 8
            else:
                reasons.append(f"Put Writers Liquidating ({oi_result.atm_put_oi_change:+,d})")
            score += min(30, writer_pts)

            # Pillar 3: Build-Up Quadrant (Max 25 pts)
            atm_b = oi_result.atm_call_buildup
            if atm_b == "LONG_BUILDUP" or oi_result.net_oi_flow == "LONG_BUILDUP":
                score += 25
                reasons.append("Institutional Long Build-Up")
            elif atm_b == "SHORT_COVERING" or oi_result.net_oi_flow == "SHORT_COVERING":
                score += 15
                reasons.append("Short Covering Squeeze")
            elif atm_b == "LONG_UNWINDING":
                score += 5
                reasons.append("Long Unwinding Warning")
            else:
                score += 5
                reasons.append(f"Build-Up: {atm_b}")

            # Pillar 4: Wall Clearance (Max 20 pts)
            if spot_price >= oi_result.call_wall:
                score += 20
                reasons.append(f"Breached Call Wall (₹{oi_result.call_wall:,.0f})")
            else:
                dist = oi_result.call_wall - spot_price
                if dist >= min_wall_dist * 2:
                    score += 20
                    reasons.append(f"High Resistance Clearance ({dist:.0f} pts)")
                elif dist >= min_wall_dist:
                    score += 10
                    reasons.append(f"Moderate Resistance Clearance ({dist:.0f} pts)")
                else:
                    score += 0
                    reasons.append(f"Near Call Wall Resistance ({dist:.0f} pts < {min_wall_dist:.0f})")

        else: # BUY_PUT
            # Pillar 1: PCR Sentiment (Max 25 pts)
            if pcr <= 0.75:
                score += 25
                reasons.append(f"Heavy Call Writing Ceiling (PCR {pcr:.2f})")
            elif pcr <= 0.90:
                score += 20
                reasons.append(f"Bearish PCR ({pcr:.2f})")
            elif pcr <= max_pcr_put:
                score += 12
                reasons.append(f"Mild Bearish PCR ({pcr:.2f})")
            else:
                score += 0
                reasons.append(f"Bullish PCR Trap ({pcr:.2f} > {max_pcr_put:.2f})")

            # Pillar 2: ATM Strike Writer Dynamics (Max 30 pts)
            writer_pts = 0
            if oi_result.atm_put_oi_change < 0:
                writer_pts += 15
                reasons.append(f"Put Writers Retreating ({oi_result.atm_put_oi_change:+,d})")
            elif oi_result.atm_put_oi_change == 0:
                writer_pts += 8
            else:
                reasons.append(f"Put Writers Defending Floor ({oi_result.atm_put_oi_change:+,d})")

            if oi_result.atm_call_oi_change > 0:
                writer_pts += 15
                reasons.append(f"Call Writers Loading Ceiling ({oi_result.atm_call_oi_change:+,d})")
            elif oi_result.atm_call_oi_change == 0:
                writer_pts += 8
            else:
                reasons.append(f"Call Writers Liquidating ({oi_result.atm_call_oi_change:+,d})")
            score += min(30, writer_pts)

            # Pillar 3: Build-Up Quadrant (Max 25 pts)
            atm_b = oi_result.atm_put_buildup
            if atm_b == "SHORT_BUILDUP" or oi_result.net_oi_flow == "SHORT_BUILDUP":
                score += 25
                reasons.append("Institutional Short Build-Up")
            elif atm_b == "LONG_UNWINDING" or oi_result.net_oi_flow == "LONG_UNWINDING":
                score += 15
                reasons.append("Long Unwinding Cascade")
            elif atm_b == "SHORT_COVERING":
                score += 5
                reasons.append("Short Covering Warning")
            else:
                score += 5
                reasons.append(f"Build-Up: {atm_b}")

            # Pillar 4: Wall Clearance (Max 20 pts)
            if spot_price <= oi_result.put_wall:
                score += 20
                reasons.append(f"Broken Put Wall Support (₹{oi_result.put_wall:,.0f})")
            else:
                dist = spot_price - oi_result.put_wall
                if dist >= min_wall_dist * 2:
                    score += 20
                    reasons.append(f"High Support Clearance ({dist:.0f} pts)")
                elif dist >= min_wall_dist:
                    score += 10
                    reasons.append(f"Moderate Support Clearance ({dist:.0f} pts)")
                else:
                    score += 0
                    reasons.append(f"Near Put Wall Support ({dist:.0f} pts < {min_wall_dist:.0f})")

        # Pillar 5: Dealer Gamma Exposure (GEX) & Volatility Regime (Option Hub model)
        if oi_result.gamma_regime == "NEGATIVE_GAMMA":
            score += 15
            reasons.append(f"Negative Gamma Accelerator (Net GEX {oi_result.total_net_gex:+.1f} Cr)")
        elif oi_result.gamma_regime == "POSITIVE_GAMMA":
            score -= 10
            reasons.append(f"Positive Gamma Pinning Chop Warning (Net GEX {oi_result.total_net_gex:+.1f} Cr)")

        if oi_result.gamma_flip_level:
            if is_call and spot_price > oi_result.gamma_flip_level:
                score += 5
                reasons.append(f"Above Gamma Flip (₹{oi_result.gamma_flip_level:,.0f})")
            elif not is_call and spot_price < oi_result.gamma_flip_level:
                score += 5
                reasons.append(f"Below Gamma Flip (₹{oi_result.gamma_flip_level:,.0f})")

        # Pillar 6: Macro Institutional Participant Bias (NSE FII Tracker)
        if participant_tracker:
            pt_mod, pt_reason = participant_tracker.get_bias_score_modifier(direction)
            score += pt_mod
            if pt_reason:
                reasons.append(f"Macro Flow: {pt_reason} ({pt_mod:+,d} pts)")

        score = max(0, min(100, score))
        summary_text = " | ".join(reasons)

        oi_result.conviction_score = score
        oi_result.conviction_summary = summary_text

        if score < min_conviction_score:
            return False, f"Low Conviction ({score}/100 < {min_conviction_score}): {summary_text}"

        return True, f"Institutional Conviction Confirmed ({score}/100): {summary_text}"

    def find_best_strike_by_volume(
        self,
        symbol: str,
        spot_price: float,
        direction: str,
        num_strikes: int = 4
    ) -> Optional[Dict[str, Any]]:
        """
        Inspects the option chain near ATM (± num_strikes) and selects the
        #1 most active, liquid strike with proven institutional Long Build-Up or Short Covering.
        Inspired by Mr. Chartist's SUPREMEIND 3600 CE trade selection.
        """
        analysis = self.analyze_symbol(symbol, spot_price, num_strikes=num_strikes)
        if not analysis or not analysis.is_valid or not analysis.strikes_data:
            return None

        candidates = []
        is_call = direction.upper() in ["BUY_CALL", "CE", "CALL"]

        for row in analysis.strikes_data:
            if is_call:
                vol = row.ce_volume
                oi_chg = row.ce_oi_change
                buildup = row.ce_buildup
                sym = row.ce_symbol
                tok = row.ce_token
                ltp = row.ce_ltp
            else:
                vol = row.pe_volume
                oi_chg = row.pe_oi_change
                buildup = row.pe_buildup
                sym = row.pe_symbol
                tok = row.pe_token
                ltp = row.pe_ltp

            if vol > 0 or row.strike:
                # Score candidate: bonus for LONG_BUILDUP (+50%) or SHORT_COVERING (+30%)
                score = float(vol)
                if buildup == "LONG_BUILDUP":
                    score = score * 1.5 + 100.0
                elif buildup == "SHORT_COVERING":
                    score = score * 1.3 + 50.0
                elif buildup == "SHORT_BUILDUP":
                    score = score * 0.5  # Penalize institutional writing resistance

                candidates.append({
                    "strike": row.strike,
                    "symbol": sym,
                    "token": tok,
                    "ltp": ltp,
                    "volume": vol,
                    "oi_change": oi_chg,
                    "buildup": buildup,
                    "score": score
                })

        if candidates:
            # Sort by score (volume + buildup confirmation)
            candidates.sort(key=lambda x: x["score"], reverse=True)
            best = candidates[0]
            log.info(
                f"🎯 [Smart Strike Selection] {symbol} {direction}: Selected strike ₹{best['strike']:,.0f} "
                f"({best['buildup']}, Vol: {best['volume']:,}, LTP: ₹{best['ltp']:.2f})"
            )
            return best

        return None
