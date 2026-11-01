"""Bullish / Neutral / Bearish: the view a general user's report shows in
place of a Buy / Hold / Sell call (marketmyna/core/compliance.py report_calls).

Computed from the company's fundamentals (return on equity, profit and sales
growth, net margin, debt, P/E against its sector median - the same peers as
Valuation vs sector, marketmyna/services/valuation.py) and the price trend,
never from the AI, so every view comes with the figures behind it:

  Bullish   2 or more points net in favour
  Bearish   2 or more points net against
  Neutral   anything in between

Each figure scores +1, 0 or -1. Without fundamentals (crypto, no data) the
trend alone decides, at 1 point. It describes what the figures show; it is
not a recommendation to buy, hold or sell.
"""

from __future__ import annotations

from typing import Optional

from ..core.numbers import finite as _num

VIEWS = ("bullish", "neutral", "bearish")
LABELS = {"bullish": "Bullish", "neutral": "Neutral", "bearish": "Bearish"}
ICONS = {"bullish": "▲", "neutral": "◆", "bearish": "▼"}
# Messages use the same marks as the PDF (no emoji anywhere). A call (Buy /
# Hold / Sell) carries no mark at all, only its word, so a view never reads as a call.
EMOJI = ICONS
# Fundamental figures kept on a row (yfinance_fundamentals keys).
FIGURES = ("return_on_equity", "earnings_growth", "revenue_growth", "profit_margin", "debt_to_equity", "pe_ratio")


def trend_of(close) -> Optional[str]:
    """uptrend / downtrend / sideways from closing prices (50- and 200-day
    averages), as in smart_report.compute_snapshot; None without a year."""
    try:
        close = close.astype(float)
    except Exception:
        return None
    if len(close) < 200:
        return None
    price, sma50, sma200 = float(close.iloc[-1]), float(close.tail(50).mean()), float(close.tail(200).mean())
    if price > sma50 > sma200:
        return "uptrend"
    if price < sma50 < sma200:
        return "downtrend"
    return "sideways"


def sector_pe(info: Optional[dict], market: Optional[str]) -> Optional[float]:
    """The median P/E of the stock's sector among the market's largest
    companies (marketmyna/services/valuation.py, cached for hours); None when the
    sector has too few profitable peers to compare with."""
    if not info or not market or market == "crypto" or not info.get("sector"):
        return None
    try:
        from .valuation import MIN_PEERS, sector_medians

        peers = sector_medians(market).get(info["sector"]) or {}
        return _num(peers.get("pe")) if peers.get("n", 0) >= MIN_PEERS else None
    except Exception:
        return None


def facts(info: Optional[dict], trend: Optional[str] = None, market: Optional[str] = None) -> dict:
    """The figures the view is built from, from a yfinance info dict; with
    `market`, also the sector's median P/E to compare against."""
    out: dict = {}
    if info:
        try:
            from ..analysis.fundamental import yfinance_fundamentals

            f = yfinance_fundamentals(info)
            out = {k: f[k] for k in FIGURES if _num(f.get(k)) is not None}
            median = sector_pe(info, market) if out.get("pe_ratio", 0) > 0 else None
            if median:
                out["sector_pe"] = median
        except Exception:
            out = {}
    if trend:
        out["trend"] = trend
    return out


def _points(f: dict) -> list[tuple[int, str, bool]]:
    """(+1 / -1, plain-words reason, is a fundamental) for every figure that leans."""
    out = []

    def add(points: int, text: str, fundamental: bool = True) -> None:
        out.append((points, text, fundamental))

    roe = _num(f.get("return_on_equity"))
    if roe is not None:
        if roe >= 0.15:
            add(1, f"strong return on equity (ROE {roe * 100:.0f}%)")
        elif roe < 0.08:
            add(-1, f"weak return on equity (ROE {roe * 100:.0f}%)")
    eg = _num(f.get("earnings_growth"))
    if eg is not None:
        if eg >= 0.10:
            add(1, f"profit up {eg * 100:.0f}% year on year")
        elif eg <= -0.10:
            add(-1, f"profit down {-eg * 100:.0f}% year on year")
    rg = _num(f.get("revenue_growth"))
    if rg is not None:
        if rg >= 0.10:
            add(1, f"sales up {rg * 100:.0f}% year on year")
        elif rg < 0:
            add(-1, f"sales down {-rg * 100:.0f}% year on year")
    pm = _num(f.get("profit_margin"))
    if pm is not None:
        if pm >= 0.15:
            add(1, f"healthy net margin ({pm * 100:.0f}%)")
        elif pm < 0:
            add(-1, f"loss-making (net margin {pm * 100:.0f}%)")
    de = _num(f.get("debt_to_equity"))
    if de is not None:
        if de <= 0.5:
            add(1, f"low debt (debt/equity {de:.1f})")
        elif de >= 1.5:
            add(-1, f"high debt (debt/equity {de:.1f})")
    # Same bands as Valuation vs sector (valuation.BELOW / ABOVE), so the two agree.
    pe, med = _num(f.get("pe_ratio")), _num(f.get("sector_pe"))
    if pe and pe > 0 and med:
        if pe <= med * 0.8:
            add(1, f"P/E {pe:.0f}, below its sector median of {med:.0f}")
        elif pe >= med * 1.2:
            add(-1, f"P/E {pe:.0f}, above its sector median of {med:.0f}")
    trend = f.get("trend")
    if trend == "uptrend":
        add(1, "price in an uptrend (above its 50- and 200-day averages)", False)
    elif trend == "downtrend":
        add(-1, "price in a downtrend (below its 50- and 200-day averages)", False)
    return out


def outlook(f: Optional[dict]) -> dict:
    """{"view", "score", "for", "against"}: the view and the figures on each
    side, fundamentals first."""
    points = _points(f or {})
    score = sum(p for p, _, _ in points)
    has_fundamentals = any(fund for _, _, fund in points) or any(k in (f or {}) for k in FIGURES)
    bar = 2 if has_fundamentals else 1
    view = "bullish" if score >= bar else "bearish" if score <= -bar else "neutral"
    def order(items):  # fundamentals first, then the trend
        return [text for _, text, _ in sorted(items, key=lambda x: not x[2])]

    return {"view": view, "score": score,
            "for": order([x for x in points if x[0] > 0]),
            "against": order([x for x in points if x[0] < 0])}


def why(o: dict, limit: int = 3) -> str:
    """One line: the figures behind the view, and the main one against it."""
    if o["view"] == "neutral":
        sides = o["for"][:1] + o["against"][:1]
        if not sides:
            return "no figure leans clearly either way"
        if o["for"] and o["against"]:
            return f"{o['for'][0]}, but {o['against'][0]}"
        return sides[0] + "; the rest is middling"
    main, other = (o["for"], o["against"]) if o["view"] == "bullish" else (o["against"], o["for"])
    text = ", ".join(main[:limit])
    return f"{text} · offset by {other[0]}" if other else text


NOTE = ("Bullish / Neutral / Bearish sums up what the company's figures (return on equity, profit and sales growth, "
        "margin, debt, P/E against its sector median) and the price trend show today. It is not a recommendation to buy, "
        "sell or hold. Figures can change quickly and are often wrong; do your own research or speak to a "
        "SEBI-registered adviser before you invest.")
