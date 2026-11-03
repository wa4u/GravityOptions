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
