"""
Unit Test Suite for Dealer Gamma Exposure (GEX) and NSE Participant Positioning.
Inspired by Mr. Chartist (Option Hub) methodology.
"""
import sys
import io

# Ensure UTF-8 output on Windows consoles
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.oi_analyzer import OIAnalyzer, OIAnalysisResult, StrikeOIData
from src.data.participant_tracker import ParticipantTracker

def test_participant_tracker():
    print("1. Testing NSE Participant Tracker...")
    sample_csv = '''""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Nov 12, 2026"",,,,,,,,,,,,,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts,Total Short Contracts
Client,172115,114170,3162126,376004,3402088,3246842,3254568,3635977,2132835,1276708,1176409,1186294,13392714,9743422
DII,54372,27224,344641,4302204,2661,107306,1600,1200,2741,40248,442624,32571,551969,4807423
FII,70744,120463,3576742,2551402,774429,1097979,982538,719084,330725,416801,446804,328820,6267420,5149111
Pro,84674,45218,1248901,424881,1730372,1102879,1669294,1078716,561234,449231,1001234,312345,4774060,3262394
Total,381905,381905,8332410,8332410,5909550,5555006,5909550,5555006,3027535,2183988,3027535,2183988,24986163,24986163'''

    tracker = ParticipantTracker(cache_file="data/test_participant_cache.json")
    parsed = tracker._parse_nse_csv(sample_csv, "2026-11-12")
    assert parsed is not None
    assert parsed["report_date"] == "2026-11-12"
    assert parsed["bias"] == "BEARISH"

    fii = parsed["participants"]["FII"]
    assert fii["fut_long_pct"] == 37.0
    assert fii["net_direction"] == -636723

    tracker.data = parsed

    # Test modifiers
    pe_mod, pe_reason = tracker.get_bias_score_modifier("BUY_PUT")
    assert pe_mod == 10
    print(f"  PE Alignment Modifier: {pe_mod:+} pts ({pe_reason})")

    ce_mod, ce_reason = tracker.get_bias_score_modifier("BUY_CALL")
    assert ce_mod == -10
    print(f"  CE Headwind Modifier: {ce_mod:+} pts ({ce_reason})")
    print("✅ Participant Tracker tests passed!")


def test_gex_profile_calculation():
    print("\n2. Testing Dealer Gamma Exposure (GEX) Calculation...")
    analyzer = OIAnalyzer(feed=None, instrument_mgr=None)

    # Synthetic strikes around spot = 25,000
    # Higher put OI at lower strikes creates negative gamma (dealer short puts)
    strikes_data = [
        StrikeOIData(strike=24800, ce_symbol="", ce_token="", ce_oi=20000, ce_oi_change=0, ce_volume=0, ce_ltp=0, ce_net_change=0, ce_buildup="",
                     pe_symbol="", pe_token="", pe_oi=180000, pe_oi_change=0, pe_volume=0, pe_ltp=0, pe_net_change=0, pe_buildup=""),
        StrikeOIData(strike=24900, ce_symbol="", ce_token="", ce_oi=30000, ce_oi_change=0, ce_volume=0, ce_ltp=0, ce_net_change=0, ce_buildup="",
                     pe_symbol="", pe_token="", pe_oi=140000, pe_oi_change=0, pe_volume=0, pe_ltp=0, pe_net_change=0, pe_buildup=""),
        StrikeOIData(strike=25000, ce_symbol="", ce_token="", ce_oi=80000, ce_oi_change=0, ce_volume=0, ce_ltp=0, ce_net_change=0, ce_buildup="",
                     pe_symbol="", pe_token="", pe_oi=80000, pe_oi_change=0, pe_volume=0, pe_ltp=0, pe_net_change=0, pe_buildup=""),
        StrikeOIData(strike=25100, ce_symbol="", ce_token="", ce_oi=120000, ce_oi_change=0, ce_volume=0, ce_ltp=0, ce_net_change=0, ce_buildup="",
                     pe_symbol="", pe_token="", pe_oi=30000, pe_oi_change=0, pe_volume=0, pe_ltp=0, pe_net_change=0, pe_buildup=""),
        StrikeOIData(strike=25200, ce_symbol="", ce_token="", ce_oi=160000, ce_oi_change=0, ce_volume=0, ce_ltp=0, ce_net_change=0, ce_buildup="",
                     pe_symbol="", pe_token="", pe_oi=10000, pe_oi_change=0, pe_volume=0, pe_ltp=0, pe_net_change=0, pe_buildup=""),
    ]

    spot = 24920.0
    tot_call_gex, tot_put_gex, tot_net_gex, regime, flip = analyzer.calculate_gex_profile(
        symbol="NIFTY",
        spot_price=spot,
        strikes_data=strikes_data,
        lot_size=25
    )

    print(f"  Spot: {spot}")
    print(f"  Call GEX: {tot_call_gex:+.2f} Cr | Put GEX: {tot_put_gex:+.2f} Cr | Net GEX: {tot_net_gex:+.2f} Cr")
    print(f"  Regime: {regime} | Gamma Flip Level: {flip}")

    assert tot_call_gex > 0
    assert tot_put_gex < 0
    assert flip is not None
    print("✅ GEX Profile calculation passed!")


def test_gex_and_fii_conviction_integration():
    print("\n3. Testing GEX & FII Integration in Conviction Engine...")
    analyzer = OIAnalyzer(feed=None, instrument_mgr=None)

    tracker = ParticipantTracker(cache_file="data/test_participant_cache.json")
    tracker.data = {
        "report_date": "2026-11-12",
        "bias": "BEARISH",
        "bias_reason": "FII Heavy Net Short",
        "participants": {
            "FII": {"fut_long_pct": 37.0, "net_direction": -636723}
        }
    }

    # Case A: Bearish Breakdown in Negative Gamma regime with FII Alignment
    bearish_oi = OIAnalysisResult(
        symbol="NIFTY",
        spot_price=24480.0,
        pcr=0.72,
        total_call_oi=500000,
        total_put_oi=360000,
        call_wall=24800.0,
        call_wall_oi=500000,
        put_wall=24450.0,
        put_wall_oi=400000,
        max_pain=24500.0,
        sentiment="BEARISH",
        is_valid=True,
        net_oi_flow="SHORT_BUILDUP",
        atm_strike=24500.0,
        atm_put_buildup="SHORT_BUILDUP",
        atm_put_oi_change=-50000,  # Put writers retreating
        atm_call_oi_change=+120000, # Call writers loading
        gamma_regime="NEGATIVE_GAMMA",
        total_net_gex=-145.5,
        gamma_flip_level=24550.0
    )

    valid, reason = analyzer.validate_signal(
        direction="BUY_PUT",
        spot_price=24440.0, # Below put wall & below gamma flip
        oi_result=bearish_oi,
        participant_tracker=tracker
    )

    print(f"  Scenario A (Bearish with Negative GEX & FII Alignment):")
    print(f"    Approved: {valid}")
    print(f"    Score: {bearish_oi.conviction_score}/100")
    print(f"    Reason: {reason}")
    assert valid is True
    assert bearish_oi.conviction_score >= 85
    assert "Negative Gamma Accelerator" in reason
    assert "FII Bearish Institutional Alignment" in reason

    # Case B: Bullish Breakout Attempt blocked by Positive Gamma Pinning & FII Short Headwinds
    bullish_choppy_oi = OIAnalysisResult(
        symbol="NIFTY",
        spot_price=24950.0,
        pcr=0.96,
        total_call_oi=400000,
        total_put_oi=384000,
        call_wall=25000.0,
        call_wall_oi=450000,
        put_wall=24800.0,
        put_wall_oi=300000,
        max_pain=24900.0,
        sentiment="NEUTRAL",
        is_valid=True,
        net_oi_flow="NEUTRAL",
        atm_strike=24950.0,
        atm_call_buildup="NEUTRAL",
        atm_put_buildup="NEUTRAL",
        atm_call_oi_change=+30000,
        atm_put_oi_change=+20000,
        gamma_regime="POSITIVE_GAMMA",
        total_net_gex=+210.0,
        gamma_flip_level=24850.0
    )

    valid_b, reason_b = analyzer.validate_signal(
        direction="BUY_CALL",
        spot_price=24960.0,
        oi_result=bullish_choppy_oi,
        participant_tracker=tracker
    )

    print(f"\n  Scenario B (Bullish Attempt trapped by Positive GEX & FII Headwinds):")
    print(f"    Approved: {valid_b}")
    print(f"    Score: {bullish_choppy_oi.conviction_score}/100")
    print(f"    Reason: {reason_b}")
    assert valid_b is False
    assert bullish_choppy_oi.conviction_score < 55
    assert "Positive Gamma Pinning Chop Warning" in reason_b
    assert "FII Heavy Short Headwinds" in reason_b
    print("✅ Integration tests passed!")

if __name__ == "__main__":
    test_participant_tracker()
    test_gex_profile_calculation()
    test_gex_and_fii_conviction_integration()
    print("\n🎉 ALL GEX & FII PARTICIPANT TESTS PASSED!")
