"""
Test Suite for Institutional Order Flow & Conviction Engine (MrChartist model).
Validates 4-quadrant build-up classification and multi-pillar conviction scoring.
"""
import sys
import io

# Ensure UTF-8 output on Windows consoles
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.oi_analyzer import OIAnalyzer, OIAnalysisResult, StrikeOIData, classify_buildup

def test_buildup_classification():
    print("Testing 4-Quadrant Build-Up Classification...")
    assert classify_buildup(10.5, 50000) == "LONG_BUILDUP"
    assert classify_buildup(15.0, -25000) == "SHORT_COVERING"
    assert classify_buildup(-12.0, 40000) == "SHORT_BUILDUP"
    assert classify_buildup(-8.5, -30000) == "LONG_UNWINDING"
    assert classify_buildup(0.0, 0) == "NEUTRAL"
    print("✅ Build-up classification passed!")

def test_conviction_scoring_bullish_approved():
    print("\nTesting Scenario 1: High Conviction Bullish Breakout (Approved)...")
    analyzer = OIAnalyzer(feed=None, instrument_mgr=None)

    # Bullish scenario: Spot 24,720, Call Wall 24,900, Put Wall 24,500, PCR 1.25
    # ATM Call writers retreating (-150,000 OI), Put writers loading (+250,000 OI)
    oi_res = OIAnalysisResult(
        symbol="NIFTY",
        spot_price=24720.0,
        pcr=1.25,
        total_call_oi=5000000,
        total_put_oi=6250000,
        call_wall=24900.0,
        call_wall_oi=1200000,
        put_wall=24500.0,
        put_wall_oi=1500000,
        max_pain=24650.0,
        sentiment="BULLISH",
        is_valid=True,
        net_oi_flow="LONG_BUILDUP",
        atm_strike=24700.0,
        atm_call_buildup="LONG_BUILDUP",
        atm_put_buildup="SHORT_BUILDUP",
        atm_call_oi_change=-150000,
        atm_put_oi_change=250000
    )

    valid, reason = analyzer.validate_signal(
        direction="BUY_CALL",
        spot_price=24720.0,
        oi_result=oi_res,
        min_pcr_call=0.90,
        max_pcr_put=1.15,
        min_wall_dist=25.0,
        min_conviction_score=55
    )

    print(f"Result: valid={valid}")
    print(f"Reason: {reason}")
    print(f"Conviction Score: {oi_res.conviction_score}/100")
    assert valid is True
    assert oi_res.conviction_score >= 75
    print("✅ Scenario 1 (Bullish High Conviction) passed!")

def test_conviction_scoring_bullish_trap_blocked():
    print("\nTesting Scenario 2: Bullish False Breakout / Call Resistance Trap (Blocked)...")
    analyzer = OIAnalyzer(feed=None, instrument_mgr=None)

    # Trap scenario: Spot 24,690, Call Wall 24,700 (only 10 pts away!), PCR 0.82 (Bearish PCR)
    # ATM Call writers actively reinforcing resistance (+400,000 OI)
    oi_res = OIAnalysisResult(
        symbol="NIFTY",
        spot_price=24690.0,
        pcr=0.82,
        total_call_oi=6500000,
        total_put_oi=5330000,
        call_wall=24700.0,
        call_wall_oi=2000000,
        put_wall=24400.0,
        put_wall_oi=1100000,
        max_pain=24600.0,
        sentiment="BEARISH",
        is_valid=True,
        net_oi_flow="SHORT_BUILDUP",
        atm_strike=24700.0,
        atm_call_buildup="SHORT_BUILDUP",
        atm_put_buildup="LONG_UNWINDING",
        atm_call_oi_change=400000,
        atm_put_oi_change=-120000
    )

    valid, reason = analyzer.validate_signal(
        direction="BUY_CALL",
        spot_price=24690.0,
        oi_result=oi_res,
        min_pcr_call=0.90,
        max_pcr_put=1.15,
        min_wall_dist=25.0,
        min_conviction_score=55
    )

    print(f"Result: valid={valid}")
    print(f"Reason: {reason}")
    print(f"Conviction Score: {oi_res.conviction_score}/100")
    assert valid is False
    assert oi_res.conviction_score < 55
    print("✅ Scenario 2 (Bullish Trap Blocked) passed!")

def test_conviction_scoring_bearish_approved():
    print("\nTesting Scenario 3: High Conviction Bearish Breakdown (Approved)...")
    analyzer = OIAnalyzer(feed=None, instrument_mgr=None)

    # Bearish scenario: Spot 24,350, broken Put Wall 24,400, PCR 0.70
    # Put writers liquidating (-300,000 OI), Call writers loading (+500,000 OI)
    oi_res = OIAnalysisResult(
        symbol="NIFTY",
        spot_price=24350.0,
        pcr=0.70,
        total_call_oi=7000000,
        total_put_oi=4900000,
        call_wall=24800.0,
        call_wall_oi=1800000,
        put_wall=24400.0,
        put_wall_oi=1200000,
        max_pain=24500.0,
        sentiment="BEARISH",
        is_valid=True,
        net_oi_flow="SHORT_BUILDUP",
        atm_strike=24400.0,
        atm_call_buildup="SHORT_BUILDUP",
        atm_put_buildup="SHORT_BUILDUP",
        atm_call_oi_change=500000,
        atm_put_oi_change=-300000
    )

    valid, reason = analyzer.validate_signal(
        direction="BUY_PUT",
        spot_price=24350.0,
        oi_result=oi_res,
        min_pcr_call=0.90,
        max_pcr_put=1.15,
        min_wall_dist=25.0,
        min_conviction_score=55
    )

    print(f"Result: valid={valid}")
    print(f"Reason: {reason}")
    print(f"Conviction Score: {oi_res.conviction_score}/100")
    assert valid is True
    assert oi_res.conviction_score >= 75
    print("✅ Scenario 3 (Bearish High Conviction) passed!")

if __name__ == "__main__":
    test_buildup_classification()
    test_conviction_scoring_bullish_approved()
    test_conviction_scoring_bullish_trap_blocked()
    test_conviction_scoring_bearish_approved()
    print("\n🎉 ALL INSTITUTIONAL ORDER FLOW TESTS PASSED SUCCESSFULLY!")
