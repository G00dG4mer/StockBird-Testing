"""Warning flags shown next to a stock: things a reader should know before
looking closer - a spike or crash today, a penny or very small company, thin
trading, an old price, the SME segment, losses, heavy debt, falling earnings.

Independent of any score or AI view (the idea of a separate risk layer comes
from AlphaSift, Apache-2.0; these checks are our own, built on the fields the
market listing and screens.metrics already have). Each flag carries points;
the total gives a level: none, low, medium or high. Facts only, never advice.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..core.numbers import finite as _num

# Total points at which the level becomes medium / high.
MEDIUM_AT = 4.0
HIGH_AT = 8.0

SURGE_PCT = 8.0      # up this much today: buying after a spike
SLUMP_PCT = -7.0     # down this much today
STALE_DAYS = 5       # a last price older than this (calendar days)
DEBT_EQUITY_HIGH = 2.0
EARNINGS_FALL_PCT = -25.0

CURRENCY_SIGN = {"INR": "₹", "USD": "$", "CNY": "¥", "HKD": "HK$"}
# Below this price a stock counts as a penny stock (local currency).
PENNY = {"INR": 10.0, "USD": 1.0, "HKD": 1.0, "CNY": 2.0}
# Below this value traded today (price x volume, local currency): thinly traded.
THIN_TRADE = {"INR": 5e6, "USD": 1e6, "HKD": 8e6, "CNY": 7e6}


def _money(value: float, currency: Optional[str]) -> str:
    sign = CURRENCY_SIGN.get(currency or "", "")
    if currency == "INR":
        lakh = value / 1e5
        return f"{sign}{lakh / 100:,.1f} crore" if lakh >= 100 else f"{sign}{lakh:,.1f} lakh"
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{sign}{value / size:,.1f}{unit}"
    return f"{sign}{value:,.0f}"


def _days_old(close_date, today: date) -> Optional[int]:
    if not close_date:
        return None
    try:
        d = close_date if isinstance(close_date, date) else datetime.fromisoformat(str(close_date)[:10]).date()
    except ValueError:
        return None
    return (today - d).days


def assess(row: dict, figures: Optional[dict] = None, today: Optional[date] = None) -> dict:
    """{"level": None | "low" | "medium" | "high", "points": float,
    "flags": [{"id", "label", "points"}]} for a listing row (and, when given,
    its screens.metrics figures)."""
    flags: list[dict] = []

    def add(flag_id: str, label: str, points: float) -> None:
        flags.append({"id": flag_id, "label": label, "points": points})

    stock = row.get("type") in (None, "stock")
    currency = row.get("currency")
    price = _num(row.get("price"))
    change = _num(row.get("change_percent"))
    volume = _num(row.get("volume"))

    if change is not None and change >= SURGE_PCT:
        add("surge", f"Up {change:.1f}% today: buying right after a spike is risky", 4.0)
    elif change is not None and change <= SLUMP_PCT:
        add("slump", f"Down {abs(change):.1f}% today", 3.5)

    if stock and price and currency in PENNY and price < PENNY[currency]:
        add("penny", f"Penny stock: price under {_money(PENNY[currency], currency)}", 2.0)
    if stock and row.get("market_cap") is not None:
        from ..data.listings import cap_band

        if cap_band(row) == "micro":
            add("micro", "Very small company: prices can swing sharply", 2.0)
    if stock and volume is not None and price:
        traded = volume * price
        if volume == 0:
            add("no_trades", "No shares traded in the last session", 3.0)
        elif currency in THIN_TRADE and traded < THIN_TRADE[currency]:
            add("thin", f"Thinly traded: about {_money(traded, currency)} changed hands", 3.0)
    if row.get("sector") == "SME" or row.get("series") in ("SM", "ST"):
        add("sme", "SME segment: smaller companies, larger lot sizes", 1.5)

    age = _days_old(row.get("close_date"), today or date.today())
    if age is not None and age > STALE_DAYS:
        add("stale", f"Last price is from {str(row['close_date'])[:10]}", 2.0)

    fig = figures or {}
    roe, pe = _num(fig.get("roe")), _num(fig.get("pe"))
    if (roe is not None and roe < 0) or (pe is not None and pe <= 0):
        add("losses", "Loss-making", 3.0)
    debt = _num(fig.get("debt_equity"))
    if debt is not None and debt > DEBT_EQUITY_HIGH:
        add("debt", f"High debt: {debt:.1f} times its equity", 2.0)
    eps = _num(fig.get("earnings_growth"))
    if eps is not None and eps < EARNINGS_FALL_PCT:
        add("earnings_fall", f"Earnings down {abs(eps):.0f}% on a year ago", 2.0)

    points = round(sum(f["points"] for f in flags), 1)
    level = None if not flags else "high" if points >= HIGH_AT else "medium" if points >= MEDIUM_AT else "low"
    flags.sort(key=lambda f: f["points"], reverse=True)
    return {"level": level, "points": points, "flags": flags}


def labels(result: dict, limit: int = 3) -> list[str]:
    return [f["label"] for f in result.get("flags", [])[:limit]]
