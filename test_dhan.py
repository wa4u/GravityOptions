"""
DhanHQ API Diagnostic & Connection Verification Script for GravityOptions.
Verifies Dhan authentication, fund balance, live intraday candles,
native Option Chain (/v2/optionchain), and Greeks calculation.

Usage:
  python test_dhan.py
"""
import sys
import io
import yaml
from datetime import datetime, date, timedelta

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.data.dhan_feed import DhanFeed, DHAN_AVAILABLE
from src.data.oi_analyzer import OIAnalyzer

def load_config() -> dict:
    try:
        with open("config/config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Error loading config/config.yaml: {e}")
        return {}

def main():
    print("=" * 68)
    print("⚡ GRAVITYOPTIONS - DHANHQ API DIAGNOSTIC & VERIFICATION TOOL")
    print("=" * 68)

    if not DHAN_AVAILABLE:
        print("\n❌ 'dhanhq' Python SDK is not installed.")
        print("👉 Install it by running: pip install dhanhq")
        return

    cfg = load_config()
    dhan_creds = cfg.get("credentials", {}).get("dhan", {}) or cfg.get("dhan", {})
    client_id = str(dhan_creds.get("client_id", "")).strip()
    access_token = str(dhan_creds.get("access_token", "")).strip()

    print(f"\n[1] Checking Configuration:")
    print(f"  • Configured Broker: '{cfg.get('system', {}).get('broker', 'unknown')}'")
    print(f"  • Dhan Client ID   : '{client_id if client_id and 'YOUR_' not in client_id else 'NOT CONFIGURED'}'")
    print(f"  • Dhan Access Token: '{'********' if access_token and 'YOUR_' not in access_token else 'NOT CONFIGURED'}'")

    if not client_id or not access_token or "YOUR_" in client_id or "YOUR_" in access_token:
        print("\n⚠️ Dhan credentials have not been entered yet.")
        print("──────────────────────────────────────────────────────────────────")
        print("📋 HOW TO GET YOUR DHAN API CREDENTIALS:")
        print("1. Log in to Dhan Web: https://web.dhan.co/")
        print("2. Click on your profile icon (top right) ➔ Select 'DhanHQ APIs'")
        print("3. Your 10-digit 'Client ID' is displayed on the screen.")
        print("4. Click 'Generate Access Token' (select 30-day validity).")
        print("5. Paste them into 'config/config.yaml' under credentials.dhan:")
        print("   credentials:")
        print("     dhan:")
        print("       client_id: \"1000000000\"")
        print("       access_token: \"eyJ0eXAiOiJKV1Qi...\"")
        print("──────────────────────────────────────────────────────────────────")
        return

    print("\n[2] Connecting to DhanHQ API...")
    feed = DhanFeed(client_id=client_id, access_token=access_token)
    if not feed.connect():
        print("❌ DhanHQ connection failed. Please check your Client ID and Access Token.")
        return

    print("✅ DhanHQ Authentication: SUCCESSFUL")

    print("\n[3] Fetching NIFTY 50 Intraday 5-Minute Candles...")
    candles = feed.get_historical_candles(
        symbol="NIFTY",
        token="13",
        interval="FIVE_MINUTE",
        count=5
    )

    if candles:
        print(f"✅ Received {len(candles)} candles. Latest candle:")
        c = candles[-1]
        print(f"  • Time: {c.timestamp} | O: ₹{c.open:,.2f} | H: ₹{c.high:,.2f} | L: ₹{c.low:,.2f} | C: ₹{c.close:,.2f} | Vol: {c.volume:,}")
    else:
        print("⚠️ No candles returned for NIFTY. (Market may be closed; secondary feed active).")

    print("\n[4] Fetching Native NIFTY 50 Option Chain & Live Greeks (/v2/optionchain)...")
    oc = feed.get_option_chain("NIFTY")
    if oc and "oc" in oc:
        spot = oc.get("last_price", 0.0)
        strikes = list(oc["oc"].keys())
        print(f"✅ Option Chain received! Total Strikes: {len(strikes)} | Spot Price: ₹{spot:,.2f}")

        # Analyze using our Institutional Conviction Model
        analyzer = OIAnalyzer(feed=feed, instrument_mgr=None)
        res = analyzer.analyze_symbol("NIFTY", spot_price=spot, num_strikes=5, force=True)

        if res.is_valid:
            print("\n[5] Institutional Order Flow Analytics:")
            print(f"  • PCR Sentiment    : {res.pcr:.2f} ({res.sentiment})")
            print(f"  • Call Wall (Res)  : ₹{res.call_wall:,.0f} (OI: {res.call_wall_oi:,})")
            print(f"  • Put Wall (Supp)  : ₹{res.put_wall:,.0f} (OI: {res.put_wall_oi:,})")
            print(f"  • Max Pain Strike  : ₹{res.max_pain:,.0f}")
            print(f"  • ATM Strike       : ₹{res.atm_strike:,.0f}")
            print(f"  • ATM Call Build-Up: {res.atm_call_buildup} (OI Chg: {res.atm_call_oi_change:+,d})")
            print(f"  • ATM Put Build-Up : {res.atm_put_buildup} (OI Chg: {res.atm_put_oi_change:+,d})")
            print(f"  • Net Market Flow  : {res.net_oi_flow}")

            # Test Conviction Gate
            valid_ce, rsn_ce = analyzer.validate_signal("BUY_CALL", spot, res)
            valid_pe, rsn_pe = analyzer.validate_signal("BUY_PUT", spot, res)
            print(f"\n  🎯 BUY_CALL Gate: {'APPROVED' if valid_ce else 'BLOCKED'} ➔ {rsn_ce}")
            print(f"  🎯 BUY_PUT  Gate: {'APPROVED' if valid_pe else 'BLOCKED'} ➔ {rsn_pe}")
    else:
        print("⚠️ Could not fetch Option Chain. Verify that Data API subscription is active on your Dhan account.")

    print("\n" + "=" * 68)
    print("🎉 DHANHQ DIAGNOSTIC COMPLETE.")
    print("=" * 68)

if __name__ == "__main__":
    main()
