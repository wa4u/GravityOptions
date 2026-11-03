# 🎯 GravityOptions - Automated Options Buying System

Automated algorithmic options buying trading system tailored for Indian Indices (**Nifty 50, Bank Nifty, Sensex, FinNifty**) and high-momentum **Stock Options**, featuring a realistic paper trading simulator, strict risk & anti-theta management, and granular Telegram notifications.

---

## 🚀 Key Features

1. **Exchange & Instrument Support**:
   - **Indices**: NIFTY, BANKNIFTY, SENSEX, and FINNIFTY (individually toggleable in config).
   - **Index Rule**: Strict **Intraday** auto-square off at 15:15 IST (zero overnight gap/theta risk).
   - **Stocks**: Top 25 liquid F&O stocks with **Conditional Carry-Forward (BTST / Swing)**:
     - Held overnight only if in healthy profit (>15%), >7 days to expiry, and closing strongly near day's highs. Otherwise, auto-exited at 15:15 IST.

2. **Native Black-Scholes Greeks Engine**:
   - Computes **Delta ($\Delta$), Theta ($\Theta$), Gamma ($\Gamma$), Vega, and IV** natively in Python.
   - Saves monthly fees on expensive data vendors by calculating Greeks directly from spot and option prices.

3. **High-Fidelity Paper Broker**:
   - Models realistic fill slippages (default 0.5 points).
   - Simulates all Indian statutory taxes & charges:
     - **STT**: 0.1% on Option Sell turnover
     - **Brokerage**: Flat ₹20/order
     - **Exchange Turnover**: 0.05%
     - **GST**: 18% on (Brokerage + Exchange)
     - **Stamp Duty**: 0.003% on Buy side
   - Outputs true net P&L after all charges.

4. **Multi-Stage Risk Management**:
   - **Daily Circuit Breaker**: Hard cap on maximum daily loss; halts trading and liquidates positions if breached.
   - **Dynamic Position Sizing**: Supports both **Fixed Lots** and **Risk Percentage** modes.
   - **Trailing Stop-Loss**: Automatically moves SL to Breakeven (+1%) at +15% profit, then trails progressively.
   - **Anti-Theta Stagnation Rule**: Exits trades that fail to move within 20 minutes to prevent time decay burn.

5. **Configurable Telegram Alerts**:
   - Real-time alerts for: Signals, Order Entries, Trailing SL moves, Exits with full P&L cards, Carry-forward decisions, Daily EOD summary, and Heartbeats.
   - Each alert type can be individually toggled ON/OFF in `config/telegram_config.yaml`.

6. **Interactive Performance Dashboard & Reporting (`reports/dashboard.html`)**:
   - Dedicated interactive analytics dashboard with period filtering:
     - **Daily (Today)**
     - **Weekly (Last 7 Days)**
     - **Monthly (Last 30 Days)**
     - **All-Time**
   - KPI metrics: Net P&L (₹), Win Rate (%), Profit Factor, Total Taxes & Charges paid (STT, GST, Brokerage), Avg Win vs Avg Loss.
   - Interactive charts: **Cumulative Net Equity Curve** and **PnL by Underlying Symbol** (Chart.js).
   - Complete searchable trade history log table with entry/exit prices, charges, duration, and exit reason.


---

## 📁 Project Structure

```
d:\GravityOptions\
│
├── config/
│   ├── config.yaml              # Main system, index toggles, risk rules, and Angel One API creds
│   └── telegram_config.yaml     # Telegram bot token, chat ID, and notification filters
│
├── src/
│   ├── utils/
│   │   ├── greeks.py            # Black-Scholes Delta, Gamma, Theta, Vega, IV formulas
│   │   ├── logger.py            # Formatted console logger
│   │   └── time_utils.py        # IST trading session & expiry date calculators
│   │
│   ├── data/
│   │   ├── base_feed.py         # Abstract market feed interface
│   │   ├── angel_feed.py        # Angel One SmartAPI connector with auto-TOTP login
│   │   ├── mock_replay_feed.py  # Offline simulation feed for testing anytime
│   │   └── instrument_manager.py # ATM/ITM strike step calculator & contract formatter
│   │
│   ├── screener/
│   │   ├── index_screener.py    # 15m ORB + VWAP Slope + EMA Trend indicator
│   │   └── stock_screener.py    # RVOL surge (>1.8x) + ATR expansion screener
│   │
│   ├── execution/
│   │   └── paper_broker.py      # Indian exchange paper simulator with taxes & slippage
│   │
│   ├── risk/
│   │   └── risk_manager.py      # Circuit breaker, trailing SL, time stops & carry rules
│   │
│   ├── alerts/
│   │   └── telegram_notifier.py # Rich HTML Telegram cards with granular toggles
│   │
│   └── engine.py                # Central orchestration engine
│
├── test_simulation.py           # Verification test suite (offline)
├── run_paper_trading.py         # Live paper trading CLI execution runner
└── requirements.txt
```

---

## ⚙️ Configuration Guide

### 1. Main Settings (`config/config.yaml`)
- **Index Toggles**: Enable or disable any index anytime:
  ```yaml
  indices:
    NIFTY:
      enabled: true
      lot_size: 25
      fixed_lots: 1
    BANKNIFTY:
      enabled: true
      lot_size: 15
      fixed_lots: 1
    SENSEX:
      enabled: true
      lot_size: 10
      fixed_lots: 1
    FINNIFTY:
      enabled: false  # Turn on/off whenever desired
  ```
- **Angel One Credentials** (for live real-time feeds):
  ```yaml
  credentials:
    angelone:
      client_id: "YOUR_CLIENT_ID"
      pin_or_password: "YOUR_MPIN"
      api_key: "YOUR_API_KEY"
      totp_secret: "YOUR_TOTP_KEY"  # Secret key from 2FA setup for headless auto-login
  ```

### 2. Telegram Notifications (`config/telegram_config.yaml`)
- Setup your bot with `@BotFather` and retrieve your `chat_id` from `@userinfobot`:
  ```yaml
  telegram:
    enabled: true
    bot_token: "123456789:ABCdef..."
    chat_id: "123456789"
    notifications:
      signal_detected: true
      order_entry: true
      trailing_sl_updated: true
      order_exit: true
      risk_circuit_breaker: true
      stock_carry_decision: true
      daily_summary: true
      system_heartbeat: false
  ```

---

## 🧪 Testing & Verification

Run the built-in offline test suite anytime:
```bash
python test_simulation.py
```

## 🏁 Starting Paper Trading

To launch the paper trading bot:
```bash
python run_paper_trading.py
```

## 📊 Viewing the Performance Dashboard


To generate and view the interactive Daily / Weekly / Monthly performance report:
```bash
# Generate the report:
python generate_report.py

# Or generate and automatically open in your default browser:
python generate_report.py --open
```

You can also seed 30 days of realistic sample trades anytime to test the dashboard UI:
```bash
python seed_demo_trades.py
```

