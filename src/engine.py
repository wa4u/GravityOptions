import yaml
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import time

from src.utils.logger import log
from src.utils.greeks import calculate_greeks, implied_volatility, black_scholes_price
from src.utils.time_utils import (
    get_now_ist, is_market_open, is_intraday_exit_time, time_to_expiry_in_years
)
from src.data.base_feed import BaseDataFeed, Candle
from src.data.angel_feed import AngelOneFeed
from src.data.mock_replay_feed import MockReplayFeed
from src.data.instrument_manager import InstrumentManager
from src.screener.index_screener import IndexScreener, IndexSignal
from src.screener.stock_screener import StockScreener, StockSignal
from src.data.oi_analyzer import OIAnalyzer, OIAnalysisResult
from src.data.participant_tracker import ParticipantTracker
from src.risk.risk_manager import RiskManager
from src.execution.paper_broker import PaperBroker, Position
from src.alerts.telegram_notifier import TelegramNotifier
from src.reporting.report_generator import ReportGenerator


class TradingEngine:
    """
    Central orchestration engine for GravityOptions:
    - Coordinates feeds, screeners, paper execution, risk filters, and alerts.
    """
    def __init__(self, config_file: str = "config/config.yaml", telegram_file: str = "config/telegram_config.yaml"):
        self.config = self.load_yaml(config_file)
        self.telegram_notifier = TelegramNotifier(telegram_file)
        
        # Core components
        self.instrument_mgr = InstrumentManager(auto_download_master=True)
        self.risk_mgr = RiskManager(self.config)
        
        sim_cfg = self.config.get("paper_simulation", {})
        init_capital = self.config.get("position_sizing", {}).get("virtual_capital", 100000.0)
        self.broker = PaperBroker(
            initial_capital=init_capital,
            brokerage_per_order=sim_cfg.get("brokerage_per_order_inr", 20.0),
            stt_rate=sim_cfg.get("stt_pct_on_sell", 0.10) / 100.0,
            exchange_turnover_rate=sim_cfg.get("exchange_turnover_pct", 0.05) / 100.0,
            gst_rate=sim_cfg.get("gst_pct", 18.0) / 100.0,
            stamp_duty_rate=sim_cfg.get("stamp_duty_pct_on_buy", 0.003) / 100.0,
            slippage_points=sim_cfg.get("slippage_points", 0.5)
        )

        self.index_screener = IndexScreener()
        stk_cfg = self.config.get("stocks", {})
        self.stock_screener = StockScreener(
            min_rvol=stk_cfg.get("min_rvol", 1.8),
            min_atr_pct=stk_cfg.get("min_atr_pct", 1.2)
        )

        self.feed: BaseDataFeed = self._init_data_feed()
        if hasattr(self.feed, "instrument_mgr"):
            self.feed.instrument_mgr = self.instrument_mgr

        oi_cache_ttl = self.config.get("oi_analysis", {}).get("cache_seconds", 60.0)
        self.oi_analyzer = OIAnalyzer(self.feed, self.instrument_mgr, cache_ttl=oi_cache_ttl)

        self.participant_tracker = ParticipantTracker()
        self.participant_data: Optional[Dict[str, Any]] = None
        try:
            self.participant_data = self.participant_tracker.get_latest_positioning()
            if self.participant_data:
                bias = self.participant_data.get("bias", "NEUTRAL")
                reason = self.participant_data.get("bias_reason", "")
                log.info(f"🏛️ [Participant Positioning] Macro Bias: {bias} | {reason}")
        except Exception as e:
            log.warning(f"Could not load participant positioning: {e}")

        self.running = False
        self.eod_summary_sent = False
        self.last_heartbeat_time = 0.0
        self.last_stock_scan_time = 0.0
        self.circuit_breaker_triggered = False
        self.cooldowns: Dict[str, datetime] = {}
        self.candle_interval = self.config.get("system", {}).get("candle_interval", "5m")
        self.cooldown_mins = self.config.get("system", {}).get("trade_cooldown_mins", 15)

    def load_yaml(self, path: str) -> Dict:
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _init_data_feed(self) -> BaseDataFeed:
        broker_choice = self.config.get("system", {}).get("broker", "angelone").lower()

        # 1. DhanHQ Broker Feed
        if broker_choice in ["dhan", "dhanhq"]:
            try:
                from src.data.dhan_feed import DhanFeed
                dhan_creds = self.config.get("credentials", {}).get("dhan", {}) or self.config.get("dhan", {})
                client_id = str(dhan_creds.get("client_id", "")).strip()
                access_token = str(dhan_creds.get("access_token", "")).strip()
                if client_id and "YOUR_" not in client_id and access_token:
                    feed = DhanFeed(client_id=client_id, access_token=access_token)
                    if feed.connect():
                        self.telegram_notifier.notify_login_success(client_id=client_id, broker="DhanHQ")
                        return feed
                    else:
                        self.telegram_notifier.notify_login_failed(client_id=client_id, broker="DhanHQ", reason="DhanHQ token or client ID invalid")
                log.warning("DhanHQ connection failed. Falling back to Mock Replay Feed.")
            except Exception as e:
                log.error(f"Failed to load DhanFeed: {e}")

        # 2. Angel One Broker Feed
        creds = self.config.get("credentials", {}).get("angelone", {})
        if broker_choice == "angelone" and creds.get("client_id") and "YOUR_" not in creds.get("client_id"):
            client_id = creds.get("client_id", "")
            feed = AngelOneFeed(
                api_key=creds.get("api_key", ""),
                client_id=client_id,
                password=creds.get("pin_or_password", ""),
                totp_secret=creds.get("totp_secret", "")
            )
            if feed.connect():
                self.telegram_notifier.notify_login_success(client_id=client_id, broker="Angel One")
                return feed
            else:
                self.telegram_notifier.notify_login_failed(client_id=client_id, broker="Angel One", reason="SmartAPI authentication rejected or TOTP invalid")
            log.warning("Angel One connection failed. Falling back to Mock Replay Feed.")

        # Default fallback: mock replay feed
        mock_feed = MockReplayFeed()
        mock_feed.connect()
        return mock_feed

    def update_open_positions(self):
        """Update active positions, check stops, targets, trailing SL, and anti-theta timeouts."""
        now = get_now_ist()
        active_contracts = list(self.broker.positions.keys())

        for contract in active_contracts:
            pos = self.broker.positions.get(contract)
            if not pos:
                continue

            # Fetch real option market price from Angel One using matching exchange segment
            exch = getattr(pos, "exchange", "BFO" if pos.symbol.upper() == "SENSEX" else "NFO")
            current_price = self.feed.get_ltp(contract, exchange=exch)
            if current_price <= 0:
                current_price = self.feed.get_ltp(contract)
            
            # CRITICAL: If LTP is temporarily unavailable (rate-limit / exchange glitch),
            # RETAIN last known valid price. NEVER use fallback theoretical pricing during monitoring,
            # which causes false instant stop-loss exits!
            if current_price <= 0:
                current_price = pos.current_price
            
            pos.current_price = current_price
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # 1. Check Stop Loss
            if current_price <= pos.stop_loss:
                record = self.broker.sell_option(contract, current_price, reason="Stop-Loss Hit")
                if record:
                    self.cooldowns[pos.symbol] = now + timedelta(minutes=self.cooldown_mins)
                    log.info(f"⏳ Cooldown activated: No new trades on {pos.symbol} for {self.cooldown_mins} minutes.")
                    self.telegram_notifier.notify_order_exit(record.__dict__)
                    self._export_live_web_report()
                continue

            # 2. Check Target Profit
            if current_price >= pos.target:
                record = self.broker.sell_option(contract, current_price, reason="Target Profit Reached")
                if record:
                    self.cooldowns[pos.symbol] = now + timedelta(minutes=self.cooldown_mins)
                    log.info(f"⏳ Cooldown activated: No new trades on {pos.symbol} for {self.cooldown_mins} minutes.")
                    self.telegram_notifier.notify_order_exit(record.__dict__)
                    self._export_live_web_report()
                continue

            # 3. Check Trailing Stop
            old_sl = pos.stop_loss
            new_sl = self.risk_mgr.evaluate_trailing_stop(pos, current_price)
            if new_sl:
                gain_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0
                self.telegram_notifier.notify_trailing_sl(contract, old_sl, new_sl, current_price, gain_pct, display_name=pos.display_name)

            # 4. Check Stagnation (Anti-Theta)
            if self.risk_mgr.check_stagnation(pos, now):
                record = self.broker.sell_option(contract, current_price, reason="Anti-Theta Stagnation Exit")
                if record:
                    self.cooldowns[pos.symbol] = now + timedelta(minutes=self.cooldown_mins)
                    log.info(f"⏳ Cooldown activated: No new trades on {pos.symbol} for {self.cooldown_mins} minutes.")
                    self.telegram_notifier.notify_order_exit(record.__dict__)
                    self._export_live_web_report()
                continue

    def handle_intraday_square_off(self):
        """At 15:15 IST, close all index positions and unqualified stock options."""
        now = get_now_ist()
        if not is_intraday_exit_time(now, self.config.get("system", {}).get("intraday_exit_time", "15:15")):
            return

        active_contracts = list(self.broker.positions.keys())
        for contract in active_contracts:
            pos = self.broker.positions.get(contract)
            if not pos:
                continue

            # Indices: ALWAYS square off intraday
            if pos.symbol in ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"]:
                record = self.broker.sell_option(contract, pos.current_price, reason="Intraday 15:15 Square-Off")
                if record:
                    self.telegram_notifier.notify_order_exit(record.__dict__)
                continue

            # Stocks: Check carry-forward qualification
            expiry_date = self.instrument_mgr.get_next_expiry(pos.symbol, now.date())
            days_to_expiry = (expiry_date - now.date()).days
            can_carry, reason = self.risk_mgr.can_carry_forward_stock(
                pos, days_to_expiry=days_to_expiry, daily_candle_closed_near_high=True
            )

            gain_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100.0
            self.telegram_notifier.notify_stock_carry_decision(pos.symbol, contract, can_carry, reason, gain_pct)

            if not can_carry:
                record = self.broker.sell_option(contract, pos.current_price, reason="Intraday Square-Off (Unqualified for Carry)")
                if record:
                    self.telegram_notifier.notify_order_exit(record.__dict__)
            else:
                pos.trading_mode = "SWING"
                log.info(f"🌙 Holding {contract} overnight (Qualified BTST/Swing trade).")

    def scan_indices(self):
        """Screen active indices for option buying triggers."""
        indices_cfg = self.config.get("indices", {})
        now = get_now_ist()
        for symbol, cfg in indices_cfg.items():
            if not cfg.get("enabled", False):
                continue

            if symbol in self.cooldowns and now < self.cooldowns[symbol]:
                continue

            can_trade, reason = self.risk_mgr.can_open_new_trade(self.broker, symbol=symbol)
            if not can_trade:
                continue

            candles = self.feed.get_historical_candles(symbol, symbol, interval=self.candle_interval, count=40)
            if not candles:
                continue

            signal: Optional[IndexSignal] = self.index_screener.evaluate_orb_setup(
                symbol=symbol,
                candles=candles,
                strike_step=cfg.get("strike_step", 50),
                strike_mode=cfg.get("strike_mode", "deep_itm"),
                itm_depth=cfg.get("itm_depth", 2)
            )

            if signal:
                # 1. Open Interest (OI) & PCR Sentiment Validation
                oi_cfg = self.config.get("oi_analysis", {})
                oi_info_dict = None
                if oi_cfg.get("enabled", True):
                    oi_res = self.oi_analyzer.analyze_symbol(
                        symbol,
                        signal.spot_price,
                        num_strikes=oi_cfg.get("num_strikes_each_side", 5)
                    )
                    if oi_res and oi_res.is_valid:
                        valid_oi, oi_rsn = self.oi_analyzer.validate_signal(
                            direction=signal.direction,
                            spot_price=signal.spot_price,
                            oi_result=oi_res,
                            min_pcr_call=oi_cfg.get("min_pcr_for_call", 0.90),
                            max_pcr_put=oi_cfg.get("max_pcr_for_put", 1.15),
                            min_wall_dist=oi_cfg.get("min_distance_to_wall", 25.0),
                            min_conviction_score=oi_cfg.get("min_conviction_score", 55),
                            participant_tracker=self.participant_tracker
                        )
                        if not valid_oi:
                            log.info(f"🛡️ [Order Flow Filter] {symbol} {signal.direction} blocked: {oi_rsn}")
                            continue

                        log.info(f"🔥 [Order Flow Confirmed] {symbol} {signal.direction}: {oi_rsn}")
                        oi_info_dict = {
                            "is_valid": True,
                            "pcr": oi_res.pcr,
                            "sentiment": oi_res.sentiment,
                            "call_wall": oi_res.call_wall,
                            "put_wall": oi_res.put_wall,
                            "max_pain": oi_res.max_pain,
                            "conviction_score": getattr(oi_res, "conviction_score", 50),
                            "conviction_summary": getattr(oi_res, "conviction_summary", ""),
                            "net_oi_flow": getattr(oi_res, "net_oi_flow", "NEUTRAL"),
                            "atm_strike": getattr(oi_res, "atm_strike", 0.0),
                            "atm_call_buildup": getattr(oi_res, "atm_call_buildup", "NEUTRAL"),
                            "atm_put_buildup": getattr(oi_res, "atm_put_buildup", "NEUTRAL"),
                            "atm_call_oi_change": getattr(oi_res, "atm_call_oi_change", 0),
                            "atm_put_oi_change": getattr(oi_res, "atm_put_oi_change", 0),
                            "gamma_regime": getattr(oi_res, "gamma_regime", "NEUTRAL"),
                            "total_net_gex": getattr(oi_res, "total_net_gex", 0.0),
                            "gamma_flip_level": getattr(oi_res, "gamma_flip_level", None),
                        }

                opt_info = self.instrument_mgr.find_option_contract(symbol, signal.target_strike, signal.option_type)
                if opt_info:
                    contract_symbol = opt_info["symbol"]
                    display_name = opt_info.get("display_name", contract_symbol)
                    lot_size = int(opt_info.get("lotsize", cfg.get("lot_size", 25)))
                    expiry = datetime.strptime(opt_info.get("expiry"), "%d%b%Y").date()
                else:
                    expiry = self.instrument_mgr.get_next_expiry(symbol, now.date())
                    contract_symbol = self.instrument_mgr.format_contract_symbol(
                        symbol, expiry, signal.target_strike, signal.option_type
                    )
                    display_name = contract_symbol
                    lot_size = cfg.get("lot_size", 25)

                if contract_symbol in self.broker.positions:
                    continue # Already in this trade

                self.telegram_notifier.notify_signal(
                    symbol=symbol,
                    direction=signal.direction,
                    trigger_reason=signal.trigger_reason,
                    spot=signal.spot_price,
                    strike=contract_symbol,
                    display_name=display_name,
                    oi_info=oi_info_dict
                )

                t_years = time_to_expiry_in_years(expiry, now)
                exch_seg = "BFO" if symbol.upper() == "SENSEX" else "NFO"
                real_premium = self.feed.get_ltp(contract_symbol, exchange=exch_seg)
                entry_premium = real_premium if real_premium > 0 else black_scholes_price(
                    signal.spot_price, signal.target_strike, t_years, iv=0.15, option_type=signal.option_type
                )

                quantity, lots = self.risk_mgr.calculate_position_size(
                    symbol=symbol,
                    lot_size=lot_size,
                    entry_price=entry_premium,
                    broker_capital=self.broker.cash,
                    configured_lots=cfg.get("fixed_lots", 1)
                )

                greeks = calculate_greeks(signal.spot_price, signal.target_strike, t_years, iv=0.15, option_type=signal.option_type)

                pos = self.broker.buy_option(
                    contract_symbol=contract_symbol,
                    symbol=symbol,
                    option_type=signal.option_type,
                    strike=signal.target_strike,
                    market_price=entry_premium,
                    quantity=quantity,
                    lots=lots,
                    sl_pct=self.risk_mgr.default_sl_pct,
                    tp_pct=self.risk_mgr.default_tp_pct,
                    delta=greeks["delta"],
                    trading_mode="INTRADAY",
                    display_name=display_name,
                    exchange=exch_seg
                )

                if pos:
                    order_info = {
                        "contract_symbol": contract_symbol,
                        "display_name": display_name,
                        "symbol": symbol,
                        "spot_price": signal.spot_price,
                        "option_type": signal.option_type,
                        "delta": greeks["delta"],
                        "entry_price": pos.entry_price,
                        "quantity": quantity,
                        "lots": lots,
                        "stop_loss": pos.stop_loss,
                        "sl_pct": self.risk_mgr.default_sl_pct,
                        "target": pos.target,
                        "tp_pct": self.risk_mgr.default_tp_pct,
                        "trading_mode": "INTRADAY",
                        "oi_info": oi_info_dict
                    }
                    self.telegram_notifier.notify_order_entry(order_info)

    def scan_stocks(self):
        """Screen top liquid F&O stocks for momentum breakout option buying."""
        stk_cfg = self.config.get("stocks", {})
        if not stk_cfg.get("enabled", False):
            return

        now = get_now_ist()
        universe = stk_cfg.get("universe", [])
        for symbol in universe:
            if symbol in self.cooldowns and now < self.cooldowns[symbol]:
                continue

            can_trade, reason = self.risk_mgr.can_open_new_trade(self.broker, symbol=symbol)
            if not can_trade:
                continue

            candles = self.feed.get_historical_candles(symbol, symbol, interval=self.candle_interval, count=40)
            if not candles:
                continue

            step = self.instrument_mgr.get_strike_step(symbol)
            signal: Optional[StockSignal] = self.stock_screener.screen_stock(
                symbol=symbol,
                candles=candles,
                strike_step=step
            )

            if signal:
                # Smart Strike Selection via Option Chain Volume & Long Build-Up
                target_strike = signal.target_strike
                best_strike_info = None
                oi_cfg = self.config.get("oi_analysis", {})
                if oi_cfg.get("enabled", True):
                    best_strike_info = self.oi_analyzer.find_best_strike_by_volume(
                        symbol, signal.spot_price, signal.direction, num_strikes=4
                    )
                    if best_strike_info and best_strike_info.get("strike"):
                        target_strike = best_strike_info["strike"]

                opt_info = self.instrument_mgr.find_option_contract(symbol, target_strike, signal.option_type)
                if opt_info:
                    contract_symbol = opt_info["symbol"]
                    display_name = opt_info.get("display_name", contract_symbol)
                    stock_lot_size = int(opt_info.get("lotsize", 500))
                    expiry = datetime.strptime(opt_info.get("expiry"), "%d%b%Y").date()
                else:
                    expiry = self.instrument_mgr.get_next_expiry(symbol, now.date())
                    contract_symbol = self.instrument_mgr.format_contract_symbol(
                        symbol, expiry, target_strike, signal.option_type
                    )
                    display_name = contract_symbol
                    stock_lot_size = max(100, int(500000 / signal.spot_price))

                if contract_symbol in self.broker.positions:
                    continue

                oi_dict = None
                if best_strike_info:
                    oi_dict = {
                        "is_valid": True,
                        "pcr": 1.0,
                        "sentiment": best_strike_info.get("buildup", "LONG_BUILDUP"),
                        "call_wall": target_strike,
                        "put_wall": target_strike,
                        "max_pain": target_strike,
                        "conviction_score": 75 if best_strike_info.get("buildup") == "LONG_BUILDUP" else 60,
                        "conviction_summary": f"Smart Strike Build-Up: {best_strike_info.get('buildup')}",
                        "net_oi_flow": best_strike_info.get("buildup", "LONG_BUILDUP"),
                        "atm_strike": target_strike,
                        "atm_call_buildup": best_strike_info.get("buildup", "LONG_BUILDUP"),
                        "atm_put_buildup": "NEUTRAL",
                        "atm_call_oi_change": best_strike_info.get("oi_change", 0),
                        "atm_put_oi_change": 0
                    }

                self.telegram_notifier.notify_signal(
                    symbol=symbol,
                    direction=signal.direction,
                    trigger_reason=signal.trigger_reason,
                    spot=signal.spot_price,
                    strike=contract_symbol,
                    display_name=display_name,
                    oi_info=oi_dict
                )

                t_years = time_to_expiry_in_years(expiry, now)
                real_premium = self.feed.get_ltp(contract_symbol, exchange="NFO")
                entry_premium = real_premium if real_premium > 0 else black_scholes_price(
                    signal.spot_price, target_strike, t_years, iv=0.20, option_type=signal.option_type
                )

                quantity, lots = self.risk_mgr.calculate_position_size(
                    symbol=symbol,
                    lot_size=stock_lot_size,
                    entry_price=entry_premium,
                    broker_capital=self.broker.cash,
                    configured_lots=stk_cfg.get("fixed_lots", 1)
                )

                pos = self.broker.buy_option(
                    contract_symbol=contract_symbol,
                    symbol=symbol,
                    option_type=signal.option_type,
                    strike=target_strike,
                    market_price=entry_premium,
                    quantity=quantity,
                    lots=lots,
                    sl_pct=self.risk_mgr.default_sl_pct,
                    tp_pct=self.risk_mgr.default_tp_pct,
                    delta=0.55 if signal.option_type == "CE" else -0.55,
                    trading_mode="INTRADAY",
                    display_name=display_name,
                    exchange="NFO"
                )

                if pos:
                    order_info = {
                        "contract_symbol": contract_symbol,
                        "display_name": display_name,
                        "symbol": symbol,
                        "spot_price": signal.spot_price,
                        "option_type": signal.option_type,
                        "delta": pos.delta,
                        "entry_price": pos.entry_price,
                        "quantity": quantity,
                        "lots": lots,
                        "stop_loss": pos.stop_loss,
                        "sl_pct": self.risk_mgr.default_sl_pct,
                        "target": pos.target,
                        "tp_pct": self.risk_mgr.default_tp_pct,
                        "trading_mode": "INTRADAY",
                        "oi_info": oi_dict
                    }
                    self.telegram_notifier.notify_order_entry(order_info)

    def run_cycle(self):
        """Single execution iteration."""
        # 1. Risk check
        is_broken, reason = self.risk_mgr.check_circuit_breaker(self.broker)
        if is_broken:
            if not self.circuit_breaker_triggered:
                for contract in list(self.broker.positions.keys()):
                    p = self.broker.positions[contract]
                    rec = self.broker.sell_option(contract, p.current_price, reason="Circuit Breaker Cutoff")
                    if rec:
                        self.telegram_notifier.notify_order_exit(rec.__dict__)
                self.telegram_notifier.notify_circuit_breaker(
                    current_loss=self.broker.get_portfolio_summary()["total_pnl"],
                    max_loss=self.risk_mgr.max_daily_loss
                )
                self.circuit_breaker_triggered = True
                self._export_live_web_report()
                log.warning("🛑 CIRCUIT BREAKER TRIGGERED: Daily loss limit hit. Trading halted for today.")
            return

        # 2. Update existing trades & evaluate exits
        self.update_open_positions()

        # 3. Check Intraday Square-off
        self.handle_intraday_square_off()

        # 4. Scan for new entries
        self.scan_indices()
        
        now_ts = time.time()
        # Scan stocks dynamically based on configuration (default 30s for high-speed feed)
        stock_interval = float(self.config.get("stocks", {}).get("scan_interval_seconds", 30.0))
        if now_ts - self.last_stock_scan_time >= stock_interval:
            self.scan_stocks()
            self.last_stock_scan_time = now_ts

        # 5. Periodic Heartbeat Log (Every 60 seconds)
        if now_ts - self.last_heartbeat_time >= 60.0:
            self._log_heartbeat()
            self.last_heartbeat_time = now_ts

    def _log_heartbeat(self):
        """Outputs periodic live market status to logs and persists data/live_status.json."""
        now = get_now_ist()
        now_str = now.strftime("%H:%M:%S")
        pos_count = len(self.broker.positions)
        summary = self.broker.get_portfolio_summary()
        cash = summary.get("cash", 100000.0)
        pnl = summary.get("total_pnl", 0.0)

        # Get spot quotes and OI/PCR for enabled indices
        quotes = []
        oi_status = {}
        indices_cfg = self.config.get("indices", {})
        for sym, cfg in indices_cfg.items():
            if cfg.get("enabled", False):
                ltp = self.feed.get_ltp(sym, cfg.get("exchange", "NSE"))
                oi_res = self.oi_analyzer._cache.get(sym.upper())
                pcr_str = ""
                if oi_res and oi_res.is_valid:
                    reg_tag = "POS" if oi_res.gamma_regime == "POSITIVE_GAMMA" else ("NEG" if oi_res.gamma_regime == "NEGATIVE_GAMMA" else "NEU")
                    pcr_str = f" [PCR:{oi_res.pcr:.2f}|GEX:{reg_tag}]"
                if ltp > 0:
                    quotes.append(f"{sym}: ₹{ltp:,.2f}{pcr_str}")
                else:
                    quotes.append(f"{sym}: Monitoring{pcr_str}")
                if oi_res and oi_res.is_valid:
                    oi_status[sym.upper()] = {
                        "pcr": oi_res.pcr,
                        "sentiment": oi_res.sentiment,
                        "call_wall": oi_res.call_wall,
                        "put_wall": oi_res.put_wall,
                        "max_pain": oi_res.max_pain,
                        "gamma_regime": getattr(oi_res, "gamma_regime", "NEUTRAL"),
                        "total_net_gex": getattr(oi_res, "total_net_gex", 0.0),
                        "gamma_flip": getattr(oi_res, "gamma_flip_level", None)
                    }

        quote_line = " | ".join(quotes) if quotes else "Monitoring indices"
        log.info(f"💓 [{now_str} IST] Market Active | Cash: ₹{cash:,.0f} | Open: {pos_count}/{self.risk_mgr.max_open_trades} | P&L: ₹{pnl:+,.2f} | {quote_line}")

        if pos_count > 0:
            for c_sym, p in self.broker.positions.items():
                pnl_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100.0 if p.entry_price > 0 else 0.0
                log.info(f"   ▶ {c_sym}: Entry ₹{p.entry_price:.2f} -> LTP ₹{p.current_price:.2f} ({pnl_pct:+.1f}%) | SL: ₹{p.stop_loss:.2f} | TP: ₹{p.target:.2f}")

        # Persist status for check_status.py
        try:
            status_info = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S IST"),
                "status": "RUNNING",
                "cash": cash,
                "open_positions": pos_count,
                "realized_pnl": summary.get("realized_pnl", 0.0),
                "unrealized_pnl": summary.get("unrealized_pnl", 0.0),
                "total_pnl": pnl,
                "quotes": quotes,
                "oi_analytics": oi_status,
                "positions": [
                    {
                        "contract": c_sym,
                        "entry_price": p.entry_price,
                        "current_price": p.current_price,
                        "quantity": p.quantity,
                        "stop_loss": p.stop_loss,
                        "target": p.target
                    }
                    for c_sym, p in self.broker.positions.items()
                ]
            }
            os.makedirs("data", exist_ok=True)
            with open("data/live_status.json", "w") as f:
                json.dump(status_info, f, indent=2)
        except Exception:
            pass

    def _export_live_web_report(self):
        """Immediately update public_html/index.html with fresh closed trades and analytics."""
        try:
            web_path = self.config.get("system", {}).get("web_report_path")
            if web_path:
                reporter = ReportGenerator(web_export_path=web_path)
                report_path = reporter.generate_html_report()
                log.info(f"🌐 Live web dashboard updated: {report_path}")
        except Exception as e:
            log.error(f"Error auto-exporting live web report: {e}")

    def generate_eod_summary(self):
        """Send End-of-Day summary."""
        if self.eod_summary_sent:
            return
        summary = self.broker.get_portfolio_summary()
        summary["date"] = get_now_ist().strftime("%Y-%m-%d")
        summary["closing_balance"] = summary["portfolio_value"]
        summary["charges"] = summary["total_charges"]
        summary["net_pnl"] = summary["realized_net_pnl"]
        self.telegram_notifier.notify_daily_summary(summary)
        
        # Auto-generate HTML performance dashboard
        self._export_live_web_report()
        self.eod_summary_sent = True

