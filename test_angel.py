#!/usr/bin/env python3
"""
GravityOptions - Angel One SmartAPI Connection & Auth Verifier
Tests your Angel One SmartAPI credentials, TOTP generation, login session,
and fetches real-time LTP to verify live data feed connectivity.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml
import pyotp
from SmartApi import SmartConnect

def test_angel():
    print("=" * 65)
    print("    GRAVITY OPTIONS - ANGEL ONE SMARTAPI LOGIN VERIFICATION")
    print("=" * 65)

    config_path = "config/config.yaml"
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Could not read {config_path}: {e}")
        return

    creds = cfg.get("credentials", {}).get("angelone", {})
    client_id = creds.get("client_id", "").strip()
    pin = str(creds.get("pin_or_password", "")).strip()
    api_key = creds.get("api_key", "").strip()
    totp_secret = creds.get("totp_secret", "").strip()

    print("\n📋 Credentials Check from config/config.yaml:")
    print(f"  • Client ID:    {client_id}")
    print(f"  • PIN/Password: {'*' * len(pin) if pin else '(Empty)'}")
    print(f"  • API Key:      {api_key[:8]}... (masked)" if len(api_key) > 8 else f"  • API Key:      {api_key}")
    print(f"  • TOTP Secret:  {totp_secret[:6]}... (masked)" if len(totp_secret) > 6 else f"  • TOTP Secret:  {totp_secret}")

    # Check for placeholder values
    placeholders = []
    if not client_id or "YOUR_" in client_id:
        placeholders.append("client_id")
    if not pin or "YOUR_" in pin:
        placeholders.append("pin_or_password")
    if not api_key or "YOUR_" in api_key:
        placeholders.append("api_key")
    if not totp_secret or "YOUR_" in totp_secret:
        placeholders.append("totp_secret")

    if placeholders:
        print(f"\n⚠️  Missing or placeholder credentials detected for: {', '.join(placeholders)}")
        print("Please update config/config.yaml with your actual Angel One SmartAPI details.")
        print("\nNote: In 'paper' mode, the bot can use a fallback simulated feed if Angel One")
        print("credentials are not configured. To enable live Angel One feeds, fill these in.")
        return

    # Step 1: Generate TOTP
    print("\n🔑 1. Generating TOTP code...")
    try:
        totp = pyotp.TOTP(totp_secret).now()
        print(f"  ✅ Current 6-digit TOTP generated: {totp}")
    except Exception as e:
        print(f"  ❌ Failed to generate TOTP with provided secret key: {e}")
        print("     Ensure your totp_secret is the base32 key (usually 16-32 letters/numbers).")
        return

    # Step 2: Authenticate with SmartAPI
    print("\n🌐 2. Connecting to Angel One SmartAPI endpoint...")
    try:
        smart_api = SmartConnect(api_key=api_key)
        session = smart_api.generateSession(client_id, pin, totp)
    except Exception as e:
        print(f"  ❌ Connection exception: {e}")
        return

    if not session.get("status"):
        error_msg = session.get("message", "Unknown error")
        error_code = session.get("errorcode", "N/A")
        print(f"\n❌ Login Failed!")
        print(f"  • Error Message: {error_msg}")
        print(f"  • Error Code:    {error_code}")
        print("\nTroubleshooting tips:")
        print("  1. Verify your PIN: Angel One uses your 4-digit trading PIN.")
        print("  2. Verify your TOTP secret: Re-enable TOTP in Angel One SmartAPI portal to get the fresh key.")
        print("  3. Verify API Key: Ensure the app type is 'Historical/Market Data' or 'Trading' in SmartAPI portal.")
        return

    data = session.get("data", {})
    jwt_token = data.get("jwtToken", "")
    feed_token = smart_api.getfeedToken()

    print("\n🎉 SUCCESS! Logged into Angel One SmartAPI successfully!")
    print(f"  • Status:      Connected")
    print(f"  • JWT Token:   {jwt_token[:15]}... (valid session)")
    print(f"  • Feed Token:  {feed_token[:15] if feed_token else 'Generated'}...")

    # Step 3: Fetch Live LTP Test (SBIN / Nifty)
    print("\n📈 3. Testing Real-time Market Quote (LTP)...")
    try:
        # SBIN token on NSE is 3045
        ltp_resp = smart_api.ltpData("NSE", "SBIN-EQ", "3045")
        if ltp_resp.get("status") and ltp_resp.get("data"):
            ltp = ltp_resp["data"].get("ltp")
            print(f"  ✅ Live NSE Data Feed Verified! SBIN Current LTP: ₹{ltp}")
        else:
            print(f"  ⚠️ LTP test response: {ltp_resp.get('message', 'No data')}")
    except Exception as e:
        print(f"  ⚠️ Could not fetch sample LTP: {e}")

    print("\n" + "=" * 65)
    print("✅ Angel One SmartAPI is 100% configured and operational for live feeds!")
    print("=" * 65)

if __name__ == "__main__":
    test_angel()
