import math
from typing import Dict, Optional

def norm_cdf(x: float) -> float:
    """Cumulative standard normal distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float,
    interest_rate: float = 0.07, # ~7% RBI repo rate proxy
    option_type: str = "CE"
) -> Dict[str, float]:
    """
    Calculate Black-Scholes Option Greeks.
    option_type: "CE" for Call or "PE" for Put.
    """
    if time_to_expiry_years <= 0.0001 or iv <= 0.001 or spot <= 0 or strike <= 0:
        return {
            "delta": 0.5 if option_type == "CE" else -0.5,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "iv": iv
        }

    T = max(time_to_expiry_years, 0.0001)
    sigma = iv
    r = interest_rate
    sqrt_T = math.sqrt(T)

    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    pdf_d1 = norm_pdf(d1)
    gamma = pdf_d1 / (spot * sigma * sqrt_T)
    vega = (spot * sqrt_T * pdf_d1) / 100.0  # Per 1% IV change

    if option_type.upper() == "CE":
        delta = norm_cdf(d1)
        theta = (-(spot * sigma * pdf_d1) / (2.0 * sqrt_T) - r * strike * math.exp(-r * T) * norm_cdf(d2)) / 365.0
    else:
        delta = norm_cdf(d1) - 1.0
        theta = (-(spot * sigma * pdf_d1) / (2.0 * sqrt_T) + r * strike * math.exp(-r * T) * norm_cdf(-d2)) / 365.0

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 2),
        "vega": round(vega, 2),
        "iv": round(iv, 4)
    }

def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float = 0.15,
    interest_rate: float = 0.07,
    option_type: str = "CE"
) -> float:
    """Calculate theoretical Black-Scholes option premium."""
    if spot <= 0 or strike <= 0:
        return 0.05
    T = max(time_to_expiry_years, 0.0001)
    sigma = max(iv, 0.01)
    r = interest_rate
    sqrt_T = math.sqrt(T)

    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type.upper() == "CE":
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)

    return max(0.05, round(price, 2))

def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    interest_rate: float = 0.07,
    option_type: str = "CE"
) -> float:
    """
    Compute Implied Volatility using Newton-Raphson approximation.
    """
    if price <= 0.05 or time_to_expiry_years <= 0:
        return 0.15 # fallback 15%

    sigma = 0.25 # Initial guess 25%
    max_iter = 100
    tolerance = 1e-3

    for _ in range(max_iter):
        sqrt_T = math.sqrt(time_to_expiry_years)
        d1 = (math.log(spot / strike) + (interest_rate + 0.5 * sigma ** 2) * time_to_expiry_years) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        if option_type.upper() == "CE":
            est_price = spot * norm_cdf(d1) - strike * math.exp(-interest_rate * time_to_expiry_years) * norm_cdf(d2)
        else:
            est_price = strike * math.exp(-interest_rate * time_to_expiry_years) * norm_cdf(-d2) - spot * norm_cdf(-d1)

        diff = est_price - price
        if abs(diff) < tolerance:
            return round(sigma, 4)

        vega = spot * sqrt_T * norm_pdf(d1)
        if abs(vega) < 1e-6:
            break
        sigma = sigma - diff / vega
        if sigma <= 0.01:
            sigma = 0.01
        elif sigma > 3.0:
            sigma = 3.0

    return round(sigma, 4)


def implied_forward(
    strike: float,
    call_price: float,
    put_price: float,
    time_to_expiry_years: float,
    interest_rate: float = 0.07
) -> float:
    """Put-Call Parity implied forward: F = K + exp(r*T) * (C - P)."""
    if strike <= 0 or call_price <= 0 or put_price <= 0:
        return strike
    T = max(time_to_expiry_years, 1e-5)
    return strike + math.exp(interest_rate * T) * (call_price - put_price)


def black76_price(
    forward: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float = 0.15,
    interest_rate: float = 0.07,
    option_type: str = "CE"
) -> float:
    """Black-76 futures/forward option price."""
    if forward <= 0 or strike <= 0:
        return 0.05
    T = max(time_to_expiry_years, 1e-5)
    sigma = max(iv, 0.01)
    sqrt_T = math.sqrt(T)
    df = math.exp(-interest_rate * T)

    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    if option_type.upper() == "CE":
        price = df * (forward * norm_cdf(d1) - strike * norm_cdf(d2))
    else:
        price = df * (strike * norm_cdf(-d2) - forward * norm_cdf(-d1))
    return max(0.05, round(price, 4))


def implied_vol_76(
    price: float,
    forward: float,
    strike: float,
    time_to_expiry_years: float,
    interest_rate: float = 0.07,
    option_type: str = "CE"
) -> Optional[float]:
    """
    Solve Black-76 Implied Volatility using Newton-Raphson with bisection safeguard.
    Returns None if price is below intrinsic or invalid.
    """
    if price <= 0.05 or forward <= 0 or strike <= 0 or time_to_expiry_years <= 0:
        return None
    T = max(time_to_expiry_years, 1e-5)
    df = math.exp(-interest_rate * T)
    is_call = option_type.upper() == "CE"
    intrinsic = df * max(0.0, (forward - strike) if is_call else (strike - forward))
    if price <= intrinsic + 0.01:
        return None

    sqrt_T = math.sqrt(T)
    # Corrado-Miller style seed or 0.20 fallback
    sigma = 0.20
    low, high = 0.02, 3.0

    for _ in range(30):
        d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T
        est = df * (forward * norm_cdf(d1) - strike * norm_cdf(d2)) if is_call else df * (strike * norm_cdf(-d2) - forward * norm_cdf(-d1))
        diff = est - price
        if abs(diff) < 1e-3:
            return round(sigma, 4)
        if diff > 0:
            high = min(high, sigma)
        else:
            low = max(low, sigma)

        vega = df * forward * sqrt_T * norm_pdf(d1)
        if vega > 1e-6:
            nxt = sigma - diff / vega
            sigma = nxt if low < nxt < high else 0.5 * (low + high)
        else:
            sigma = 0.5 * (low + high)

    return round(sigma, 4) if 0.02 <= sigma <= 3.0 else None


def greeks_76_spot(
    spot: float,
    forward: float,
    strike: float,
    time_to_expiry_years: float,
    iv: float,
    interest_rate: float = 0.07,
    option_type: str = "CE"
) -> Dict[str, float]:
    """
    Spot-adjusted Black-76 Greeks (Option Hub greeks76Spot model).
    """
    if time_to_expiry_years <= 1e-5 or iv <= 0.005 or spot <= 0 or forward <= 0 or strike <= 0:
        return {"delta": 0.5 if option_type.upper() == "CE" else -0.5, "gamma": 0.0, "vega": 0.0, "iv": iv}

    T = max(time_to_expiry_years, 1e-5)
    sigma = max(iv, 0.01)
    sqrt_T = math.sqrt(T)
    df = math.exp(-interest_rate * T)
    f_over_s = forward / spot

    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    pdf_d1 = norm_pdf(d1)

    gamma_f = df * pdf_d1 / (forward * sigma * sqrt_T)
    gamma_s = gamma_f * (f_over_s * f_over_s)

    if option_type.upper() == "CE":
        delta_s = df * norm_cdf(d1) * f_over_s
    else:
        delta_s = df * (norm_cdf(d1) - 1.0) * f_over_s

    vega = (df * forward * sqrt_T * pdf_d1) / 100.0
    return {
        "delta": round(delta_s, 4),
        "gamma": round(gamma_s, 7),
        "vega": round(vega, 3),
        "iv": round(sigma, 4),
    }


def expected_move_1day(spot: float, atm_iv: float) -> float:
    """1-day 1-sigma expected move: spot * atm_iv / sqrt(252)."""
    if spot <= 0 or atm_iv <= 0:
        return 0.0
    return round(spot * atm_iv / math.sqrt(252.0), 1)


def realized_vol_from_candles(candles: list, window: int = 20) -> Optional[float]:
    """
    Annualized Close-to-Close realised volatility from intraday/daily Candle objects.
    Aggregates intraday bars to daily closes when multiple days exist, otherwise scales bar returns.
    """
    if not candles or len(candles) < 10:
        return None

    # Group by date to get daily closes if >= 5 trading days are present
    daily_closes = {}
    for c in candles:
        ts = getattr(c, "timestamp", None)
        d = ts.date() if hasattr(ts, "date") else None
        if d is not None:
            daily_closes[d] = float(c.close)

    if len(daily_closes) >= 6:
        closes = [daily_closes[d] for d in sorted(daily_closes.keys())][-(window + 1):]
        ann_factor = 252.0
    else:
        closes = [float(c.close) for c in candles[-(window + 1):]]
        ann_factor = 252.0 * 75.0  # 5m bars per NSE session

    if len(closes) < 5:
        return None

    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    if len(rets) < 4:
        return None

    mean_r = sum(rets) / len(rets)
    var = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    hv = math.sqrt(var * ann_factor)
    return round(hv, 4) if hv > 0.005 else None


def find_strike_for_delta(
    spot: float,
    forward: float,
    strikes_data: list,
    time_to_expiry_years: float,
    target_delta: float = 0.65,
    option_type: str = "CE"
) -> Optional[float]:
    """
    Pick the liquid strike whose Black-76 spot |delta| is closest to target_delta.
    Filters out strikes with zero LTP/volume when liquid alternatives exist.
    """
    if not strikes_data or spot <= 0 or forward <= 0:
        return None

    is_call = option_type.upper() == "CE"
    T = max(time_to_expiry_years, 1e-4)
    best_strike = None
    best_diff = float("inf")

    for row in strikes_data:
        ltp = row.ce_ltp if is_call else row.pe_ltp
        vol = row.ce_volume if is_call else row.pe_volume
        iv = (row.ce_iv if is_call else row.pe_iv) or 0.15
        if ltp <= 0.5 and vol <= 0:
            continue
        g = greeks_76_spot(spot, forward, row.strike, T, iv, option_type="CE" if is_call else "PE")
        abs_d = abs(g.get("delta", 0.5))
        diff = abs(abs_d - abs(target_delta))
        if diff < best_diff:
            best_diff = diff
            best_strike = row.strike

    return best_strike
