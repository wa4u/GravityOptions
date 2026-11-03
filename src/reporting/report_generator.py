import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from src.execution.trade_logger import TradeLogger

from src.utils.logger import log

class ReportGenerator:
    """
    Generates a rich, interactive HTML analytics dashboard
    with Daily, Weekly, Monthly, and All-Time views, equity curves,
    charge breakdowns, and trade logs.
    """
    def __init__(
        self,
        db_path: str = "data/trading_history.db",
        output_path: str = "reports/dashboard.html",
        web_export_path: Optional[str] = None
    ):
        self.logger = TradeLogger(db_path)
        self.output_path = output_path
        self.web_export_path = web_export_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)


    def generate_html_report(self) -> str:
        trades = self.logger.fetch_all_trades()
        # Sort trades chronologically for charting
        trades_chronological = sorted(trades, key=lambda x: x["exit_time"])

        trades_json = json.dumps(trades_chronological)
        generated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GravityOptions - Performance Analytics Dashboard</title>
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-dark: #0b0f19;
            --bg-card: #111827;
            --bg-card-hover: #1f2937;
            --border-color: #374151;
            --text-primary: #f9fafb;
            --text-secondary: #9ca3af;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-primary);
            padding: 24px;
            min-height: 100vh;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }}
        .header h1 {{
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header .subtitle {{
            color: var(--text-secondary);
            font-size: 13px;
            margin-top: 4px;
        }}
        /* Period filter tabs */
        .tabs {{
            display: flex;
            gap: 8px;
            background-color: var(--bg-card);
            padding: 4px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            padding: 8px 18px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.2s;
        }}
        .tab-btn:hover {{ color: var(--text-primary); }}
        .tab-btn.active {{
            background-color: var(--accent-blue);
            color: #ffffff;
        }}
        /* KPI Cards Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 18px;
        }}
        .kpi-title {{
            font-size: 12px;
            font-weight: 500;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}
        .kpi-value {{
            font-size: 22px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        .kpi-subtext {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
        }}
        .positive {{ color: var(--accent-green); }}
        .negative {{ color: var(--accent-red); }}
        /* Charts Grid */
        .charts-grid {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}
        @media (max-width: 1024px) {{
            .charts-grid {{ grid-template-columns: 1fr; }}
        }}
        .chart-card {{
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
        }}
        .chart-header {{
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 16px;
        }}
        /* Table Styles */
        .table-container {{
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        th {{
            color: var(--text-secondary);
            font-weight: 600;
            padding: 12px 14px;
            border-bottom: 1px solid var(--border-color);
            white-space: nowrap;
        }}
        td {{
            padding: 12px 14px;
            border-bottom: 1px solid #1f2937;
            white-space: nowrap;
            font-family: 'Inter', sans-serif;
        }}
        tr:hover td {{
            background-color: var(--bg-card-hover);
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }}
        .badge-ce {{ background: rgba(16, 185, 129, 0.15); color: #10b981; }}
        .badge-pe {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; }}
        .badge-win {{ background: rgba(16, 185, 129, 0.15); color: #10b981; }}
        .badge-loss {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; }}
        .mono {{ font-family: 'JetBrains Mono', monospace; }}
    </style>
</head>
<body>

    <div class="header">
        <div>
            <h1>⚡ GravityOptions Analytics</h1>
            <div class="subtitle">Options Buying Automation • Report generated on {generated_at}</div>
        </div>
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
            <a href="/helper.html" style="text-decoration: none; color: #f9fafb; font-size: 13px; font-weight: 600; padding: 8px 16px; border-radius: 6px; border: 1px solid #374151; background-color: #111827; transition: background 0.2s;">🛠️ Helper & Controls</a>
            <div class="tabs">
                <button class="tab-btn" onclick="filterPeriod('daily')">Daily (Today)</button>
                <button class="tab-btn" onclick="filterPeriod('weekly')">Weekly</button>
                <button class="tab-btn" onclick="filterPeriod('monthly')">Monthly</button>
                <button class="tab-btn active" onclick="filterPeriod('all')">All-Time</button>
            </div>
        </div>
    </div>


    <!-- KPI Grid -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-title">Net Realized P&L</div>
            <div class="kpi-value" id="kpi-net-pnl">₹0.00</div>
            <div class="kpi-subtext" id="kpi-roi">0.0% Return</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Win Rate</div>
            <div class="kpi-value" id="kpi-win-rate">0.0%</div>
            <div class="kpi-subtext" id="kpi-trades-count">0 Trades (0W / 0L)</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Profit Factor</div>
            <div class="kpi-value" id="kpi-profit-factor">0.00</div>
            <div class="kpi-subtext" id="kpi-gross-ratio">Gross Win / Gross Loss</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Total Taxes & Charges</div>
            <div class="kpi-value" id="kpi-charges">₹0.00</div>
            <div class="kpi-subtext">STT, Brokerage, GST, Exch</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Avg Win / Avg Loss</div>
            <div class="kpi-value" id="kpi-avg-win-loss">₹0 / ₹0</div>
            <div class="kpi-subtext" id="kpi-rr-ratio">Risk-Reward Metric</div>
        </div>
    </div>

    <!-- Charts Grid -->
    <div class="charts-grid">
        <div class="chart-card">
            <div class="chart-header">Cumulative Net Equity Curve (₹)</div>
            <canvas id="equityChart" height="130"></canvas>
        </div>
        <div class="chart-card">
            <div class="chart-header">PnL by Underlying Symbol</div>
            <canvas id="symbolChart" height="200"></canvas>
        </div>
    </div>

    <!-- Trade Log Table -->
    <div class="table-container">
        <div class="chart-header" style="margin-bottom: 12px;">Detailed Trade History</div>
        <table>
            <thead>
                <tr>
                    <th>Exit Time</th>
                    <th>Contract</th>
                    <th>Underlying</th>
                    <th>Type</th>
                    <th>Qty</th>
                    <th>Buy Price</th>
                    <th>Exit Price</th>
                    <th>Gross PnL</th>
                    <th>Taxes & Fees</th>
                    <th>Net PnL</th>
                    <th>ROI %</th>
                    <th>Exit Reason</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody id="trade-table-body">
                <!-- Dynamically Populated -->
            </tbody>
        </table>
    </div>

    <script>
        const allTrades = {trades_json};
        let currentPeriod = 'all';
        let equityChartInstance = null;
        let symbolChartInstance = null;

        function filterPeriod(period) {{
            currentPeriod = period;
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            renderDashboard();
        }}

        function getFilteredTrades() {{
            if (currentPeriod === 'all') return allTrades;
            const now = new Date();
            const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());

            return allTrades.filter(t => {{
                const exitDate = new Date(t.exit_time);
                if (currentPeriod === 'daily') {{
                    return exitDate >= startOfDay;
                }} else if (currentPeriod === 'weekly') {{
                    const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                    return exitDate >= sevenDaysAgo;
                }} else if (currentPeriod === 'monthly') {{
                    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
                    return exitDate >= thirtyDaysAgo;
                }}
                return true;
            }});
        }}

        function renderDashboard() {{
            const trades = getFilteredTrades();
            
            // KPIs Calculation
            let netPnl = 0;
            let grossWins = 0;
            let grossLosses = 0;
            let totalCharges = 0;
            let wins = 0;
            let losses = 0;
            let winPnls = [];
            let lossPnls = [];

            trades.forEach(t => {{
                netPnl += t.net_pnl;
                totalCharges += t.total_charges;
                if (t.net_pnl > 0) {{
                    wins++;
                    grossWins += t.gross_pnl;
                    winPnls.push(t.net_pnl);
                }} else {{
                    losses++;
                    grossLosses += Math.abs(t.gross_pnl);
                    lossPnls.push(Math.abs(t.net_pnl));
                }}
            }});

            const totalTrades = trades.length;
            const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '0.0';
            const profitFactor = grossLosses > 0 ? (grossWins / grossLosses).toFixed(2) : (grossWins > 0 ? '∞' : '0.00');
            const avgWin = winPnls.length > 0 ? (winPnls.reduce((a,b)=>a+b,0) / winPnls.length).toFixed(0) : '0';
            const avgLoss = lossPnls.length > 0 ? (lossPnls.reduce((a,b)=>a+b,0) / lossPnls.length).toFixed(0) : '0';

            // Update KPI DOM
            const netElem = document.getElementById('kpi-net-pnl');
            netElem.innerText = (netPnl >= 0 ? '+' : '') + '₹' + netPnl.toLocaleString('en-IN', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
            netElem.className = 'kpi-value ' + (netPnl >= 0 ? 'positive' : 'negative');

            document.getElementById('kpi-win-rate').innerText = winRate + '%';
            document.getElementById('kpi-trades-count').innerText = `${{totalTrades}} Trades (${{wins}}W / ${{losses}}L)`;
            document.getElementById('kpi-profit-factor').innerText = profitFactor;
            document.getElementById('kpi-charges').innerText = '₹' + totalCharges.toLocaleString('en-IN', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
            document.getElementById('kpi-avg-win-loss').innerText = `₹${{avgWin}} / ₹${{avgLoss}}`;

            renderCharts(trades);
            renderTable(trades);
        }}

        function renderCharts(trades) {{
            // 1. Cumulative Equity Curve
            let cumulative = 0;
            const labels = [];
            const equityData = [];

            trades.forEach((t, i) => {{
                cumulative += t.net_pnl;
                labels.push(t.exit_time.split(' ')[1] || `#${{i+1}}`);
                equityData.push(cumulative);
            }});

            const ctx1 = document.getElementById('equityChart').getContext('2d');
            if (equityChartInstance) equityChartInstance.destroy();

            equityChartInstance = new Chart(ctx1, {{
                type: 'line',
                data: {{
                    labels: labels.length > 0 ? labels : ['Start'],
                    datasets: [{{
                        label: 'Net P&L (₹)',
                        data: equityData.length > 0 ? equityData : [0],
                        borderColor: cumulative >= 0 ? '#10b981' : '#ef4444',
                        backgroundColor: cumulative >= 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                        fill: true,
                        tension: 0.25,
                        pointRadius: 4
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ grid: {{ color: '#1f2937' }}, ticks: {{ color: '#9ca3af' }} }},
                        y: {{ grid: {{ color: '#1f2937' }}, ticks: {{ color: '#9ca3af' }} }}
                    }}
                }}
            }});

            // 2. Breakdown by Symbol
            const symbolMap = {{}};
            trades.forEach(t => {{
                symbolMap[t.symbol] = (symbolMap[t.symbol] || 0) + t.net_pnl;
            }});

            const ctx2 = document.getElementById('symbolChart').getContext('2d');
            if (symbolChartInstance) symbolChartInstance.destroy();

            const symLabels = Object.keys(symbolMap);
            const symValues = Object.values(symbolMap);

            symbolChartInstance = new Chart(ctx2, {{
                type: 'bar',
                data: {{
                    labels: symLabels.length > 0 ? symLabels : ['None'],
                    datasets: [{{
                        data: symValues.length > 0 ? symValues : [0],
                        backgroundColor: symValues.map(v => v >= 0 ? '#10b981' : '#ef4444'),
                        borderRadius: 4
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{
                        x: {{ grid: {{ display: false }}, ticks: {{ color: '#9ca3af' }} }},
                        y: {{ grid: {{ color: '#1f2937' }}, ticks: {{ color: '#9ca3af' }} }}
                    }}
                }}
            }});
        }}

        function renderTable(trades) {{
            const tbody = document.getElementById('trade-table-body');
            tbody.innerHTML = '';

            if (trades.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="13" style="text-align:center; color:#6b7280; padding:24px;">No closed trades recorded in this period yet.</td></tr>';
                return;
            }}

            // Show newest trades first in table
            const reversed = [...trades].reverse();
            reversed.forEach(t => {{
                const tr = document.createElement('tr');
                const isWin = t.net_pnl >= 0;
                const pnlClass = isWin ? 'positive' : 'negative';
                const typeBadge = t.option_type === 'CE' ? 'badge-ce' : 'badge-pe';

                tr.innerHTML = `
                    <td class="mono" style="font-size:12px;">${{t.exit_time}}</td>
                    <td><b>${{t.contract_symbol}}</b></td>
                    <td>${{t.symbol}}</td>
                    <td><span class="badge ${{typeBadge}}">${{t.option_type}}</span></td>
                    <td class="mono">${{t.quantity}}</td>
                    <td class="mono">₹${{t.entry_price.toFixed(2)}}</td>
                    <td class="mono">₹${{t.exit_price.toFixed(2)}}</td>
                    <td class="mono ${{pnlClass}}">₹${{t.gross_pnl.toFixed(2)}}</td>
                    <td class="mono" style="color:#9ca3af;">₹${{t.total_charges.toFixed(2)}}</td>
                    <td class="mono ${{pnlClass}}" style="font-weight:700;">₹${{t.net_pnl.toFixed(2)}}</td>
                    <td class="mono ${{pnlClass}}">${{t.roi_pct >= 0 ? '+' : ''}}${{t.roi_pct.toFixed(1)}}%</td>
                    <td>${{t.exit_reason}}</td>
                    <td style="color:#9ca3af;">${{t.holding_duration}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        // Initialize on load
        renderDashboard();
    </script>
</body>
</html>
"""
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        log.info(f"📊 Performance Dashboard successfully exported to: {self.output_path}")

        # If a web export path (e.g., /home/gravitywork/public_html/index.html) is provided
        if self.web_export_path:
            try:
                os.makedirs(os.path.dirname(self.web_export_path), exist_ok=True)
                with open(self.web_export_path, "w", encoding="utf-8") as f_web:
                    f_web.write(html_content)
                log.info(f"🌐 Live Web Report published to: {self.web_export_path}")
            except Exception as e:
                log.warning(f"Could not export to web path {self.web_export_path}: {e}")

        return os.path.abspath(self.output_path)

