import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.utils.logger import log

class TradeLogger:
    """
    Persists paper and live trades into a local SQLite database
    for persistent daily, weekly, monthly, and all-time reporting.
    """
    DB_PATH = "data/trading_history.db"

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_symbol TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    instrument_type TEXT NOT NULL, -- 'INDEX' or 'STOCK'
                    option_type TEXT NOT NULL,     -- 'CE' or 'PE'
                    strike REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    exit_reason TEXT NOT NULL,
                    gross_pnl REAL NOT NULL,
                    brokerage REAL NOT NULL,
                    stt REAL NOT NULL,
                    exchange_charges REAL NOT NULL,
                    gst REAL NOT NULL,
                    stamp_duty REAL NOT NULL,
                    total_charges REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    roi_pct REAL NOT NULL,
                    holding_duration TEXT NOT NULL,
                    trading_mode TEXT NOT NULL      -- 'INTRADAY' or 'SWING'
                )
            """)
            conn.commit()

    def log_trade(self, trade_data: Dict[str, Any]):
        """Insert a completed trade record into the database."""
        symbol = trade_data.get("symbol", "")
        inst_type = "INDEX" if symbol in ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"] else "STOCK"

        query = """
            INSERT INTO trades (
                contract_symbol, symbol, instrument_type, option_type, strike, quantity,
                entry_price, exit_price, entry_time, exit_time, exit_reason,
                gross_pnl, brokerage, stt, exchange_charges, gst, stamp_duty,
                total_charges, net_pnl, roi_pct, holding_duration, trading_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        entry_time_str = trade_data["entry_time"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(trade_data["entry_time"], datetime) else str(trade_data["entry_time"])
        exit_time_str = trade_data["exit_time"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(trade_data["exit_time"], datetime) else str(trade_data["exit_time"])

        params = (
            trade_data["contract_symbol"],
            symbol,
            inst_type,
            trade_data["option_type"],
            trade_data["strike"],
            trade_data["quantity"],
            trade_data["entry_price"],
            trade_data["exit_price"],
            entry_time_str,
            exit_time_str,
            trade_data["exit_reason"],
            trade_data["gross_pnl"],
            trade_data["brokerage"],
            trade_data["stt"],
            trade_data["exchange_charges"],
            trade_data["gst"],
            trade_data["stamp_duty"],
            trade_data["total_charges"],
            trade_data["net_pnl"],
            trade_data["roi_pct"],
            trade_data["holding_duration"],
            trade_data.get("trading_mode", "INTRADAY")
        )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            log.info(f"💾 Trade saved to database: {trade_data['contract_symbol']} (Net PnL: ₹{trade_data['net_pnl']:+,.2f})")

    def fetch_all_trades(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY exit_time DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
