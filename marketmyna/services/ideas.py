"""New stock ideas for the scheduled report: candidates outside the
watchlist, in the user's focus market and categories, that look
constructive under current conditions.

Pipeline (cheap to expensive):
1. Screen the full market listing (marketmyna/data/listings.py): stocks with an
   official industry, in the focus categories, at least small-cap (no illiquid micro caps),
   traded today, trending up but not pinned at the 52-week high.
2. Trend check on the best ~25: one year of daily closes - keep stocks
   in an established uptrend that isn't overheated (see technical_check).
3. Fundamentals of the leaders (ROE, debt, EPS and sales growth, margin,
   P/E): loss-makers and collapsing earnings drop out.
4. Warning flags (marketmyna/services/risk_flags.py): a finalist whose flags add
   up to "high" (a spike today, thin trading, losses...) drops out; the rest
   carry their flags into the report.
5. Final pick: the LLM chooses and explains `count` of them when one is
   configured - what stands out, what to watch and what would weaken the
   case; otherwise the rule-based ranking and a plain reason. The AI's reply
   is checked (only candidates, no repeats, retried once if it misses), and
   any gap is filled from the rule ranking. At most MAX_PER_CATEGORY ideas
   share a category, so one hot sector can't fill the list.

The report shows them as "Stocks matching your screen": the AI explains what
stands out and what to watch under marketmyna/core/compliance.py NO_CALLS_RULE,
never a buy call, and the report says they are a screen match to research,
not advice.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from typing import Iterable, Optional

from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)

SCREEN_SIZE = 25
MAX_PER_CATEGORY = 2  # ideas from one category, unless too few others qualify
FIGURES_FOR = 8  # finalists whose fundamentals are fetched (one info call each)
# Fundamentals kept per idea (marketmyna/services/screens.py metrics).
FIGURES = ("roe", "debt_equity", "earnings_growth", "revenue_growth", "operating_margin", "pe", "dividend_yield")


def screen(rows: Iterable[dict], categories: list[str], exclude: set[str], limit: int = SCREEN_SIZE) -> list[dict]:
    """Rank listing rows by a quick trend/size score; no network."""
    from ..data.listings import cap_band

    wanted = set(categories or [])
    scored = []
    for row in rows:
        if row.get("type") not in ("stock", "crypto") or row["symbol"].upper() in exclude:
            continue
        if wanted and row.get("category") not in wanted:
            continue
        # Recommend only stocks with an official industry: a category guessed
        # from a company name ("Technocraft" -> Technology) is fine for
        # browsing, not for a buy idea.
        if row.get("type") == "stock" and row.get("category_inferred"):
            continue
        price = _num(row.get("price"))
        if not price or price <= 0:
            continue
        if row.get("type") == "stock" and cap_band(row) not in ("mega", "large", "mid", "small"):
            continue
        if row.get("volume") is not None and not _num(row.get("volume")):
            continue

        score = 0.0
        high, low = _num(row.get("high_52w")), _num(row.get("low_52w"))
        if high and low and high > low:
            position = (price - low) / (high - low)
            if position < 0.35:
                continue  # still in a downtrend
            # Best around 75% of the range: uptrend with room left to the high.
            score += 2.0 * (1 - abs(position - 0.75) / 0.75)
        change = _num(row.get("change_percent"))
        if change is not None:
            if change < -4 or change > 8:
                continue  # skip today's crashes and blow-off spikes
            score += 0.3 if 0 < change <= 4 else 0.0
        cap = _num(row.get("market_cap")) or _num(row.get("volume")) or 0
        score += min(math.log10(cap + 1) / 12, 1.0)  # mild preference for size/liquidity
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:limit]]


def _rsi(close, period: int = 14) -> Optional[float]:
    """Wilder RSI (same as broker charts and the scanner)."""
    from ..trading.indicators import rsi

    if len(close.dropna()) <= period:
        return None
    value = rsi(close.astype(float), period).iloc[-1]
    return None if value != value else float(value)


def technical_check(row: dict) -> Optional[dict]:
    """Trend-following check on a year of daily closes; None if it fails.

    Deliberately not the analyzer's oscillator vote: RSI/Bollinger/
    Stochastic there are mean-reversion signals that call strong uptrends
    "sell" (overbought), which is the opposite of what a buy idea needs.
    Rules: price > 50-day > 200-day average, positive 3-month return, RSI
    45-72 (momentum without being overheated), at most 15% above the 50-day.
    """
    from ..agent.agents import _resolve_fetcher

    try:
        history = _resolve_fetcher(row["market"]).get_history(row["symbol"], period="1y")
    except Exception as exc:
        logger.info("Idea check skipped for %s: %s", row["symbol"], exc)
        return None
    if history is None or len(history) < 120:
        return None
    close = history["close"].astype(float)
    last = float(close.iloc[-1])
    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean())
    ret_3m = (last / float(close.iloc[-64]) - 1) * 100
    ret_1m = (last / float(close.iloc[-22]) - 1) * 100
    rsi = _rsi(close)
    stretch = (last / sma50 - 1) * 100
    if not (last > sma50 > sma200) or ret_3m <= 0 or rsi is None or not 45 <= rsi <= 72 or stretch > 15:
        return None
    # Higher = stronger, steadier trend: reward 3-month momentum, penalise
    # being stretched far above the 50-day average.
    score = ret_3m - 0.5 * max(0.0, stretch - 5) + (5 if 50 <= rsi <= 65 else 0)
    return {"score": score, "rsi": rsi, "return_1m": ret_1m, "return_3m": ret_3m,
            "above_sma50_pct": stretch, "above_sma200_pct": (last / sma200 - 1) * 100}


def _rule_reason(row: dict, tech: dict) -> str:
    bits = [f"uptrend: {tech['above_sma50_pct']:+.1f}% vs 50-day, {tech['above_sma200_pct']:+.1f}% vs 200-day average",
            f"3-month {tech['return_3m']:+.1f}%", f"RSI {tech['rsi']:.0f}"]
    high = _num(row.get("high_52w"))
    if high and _num(row.get("price")):
        bits.append(f"{(1 - row['price'] / high) * 100:.0f}% below 52-week high")
    return "; ".join(bits)


def fetch_figures(row: dict) -> dict:
    """The company's fundamentals (percent values as screens.metrics gives
    them); {} for crypto or when unavailable."""
    if row.get("market") == "crypto":
        return {}
    try:
        from . import screens
        from .analysis_run import yahoo_symbol
        from .compare import _yahoo_info

        info = _yahoo_info(yahoo_symbol(row["symbol"], row["market"])) or {}
        m = screens.metrics(info)
        return {k: m.get(k) for k in FIGURES if _num(m.get(k)) is not None}
    except Exception as exc:
        logger.info("Figures for idea %s unavailable: %s", row.get("symbol"), exc)
        return {}


def _weak(fig: dict) -> bool:
    """Loss-making or earnings collapsing: no idea, whatever the chart says."""
    roe, eps = _num(fig.get("roe")), _num(fig.get("earnings_growth"))
    return (roe is not None and roe < 0) or (eps is not None and eps < -25)


def _figure_text(fig: dict) -> str:
    names = {"roe": "ROE %", "debt_equity": "debt/equity", "earnings_growth": "EPS growth %",
             "revenue_growth": "sales growth %", "operating_margin": "operating margin %", "pe": "P/E",
             "dividend_yield": "dividend yield %"}
    return ", ".join(f"{names[k]} {fig[k]:.1f}" for k in FIGURES if k in fig) or "no fundamentals"


_PICK_PROMPTS = {
    True: ("You are an equity research assistant. From the candidates only, choose the best ideas for a "
           "retail investor under current conditions, balancing trend strength, fundamentals, valuation risk "
           "and diversification across categories.",
           "Pick the {count} best new positions to consider buying now."),
    False: ("You are an equity research assistant writing for an analytics report. From the candidates only, "
            "choose the ones whose figures stand out most - trend, profitability, growth, debt, valuation - "
            "spread across categories. Describe them factually.",
            "Choose the {count} candidates whose figures stand out most, and say what stands out and what to watch."),
}


def _parse_picks(text: str) -> list:
    """The JSON list in the AI's reply, forgiving the usual slips (a code
    fence, prose around it, a trailing comma); [] when there is none."""
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not match:
        return []
    raw = match.group(0)
    for attempt in (raw, re.sub(r",\s*([\]}])", r"\1", raw)):
        try:
            picks = json.loads(attempt)
            return picks if isinstance(picks, list) else []
        except ValueError:
            continue
    return []


def _llm_pick(finalists: list[dict], count: int, market: str, categories: list[str], config,
              calls: bool = True) -> Optional[list[dict]]:
    """The AI's choice among `finalists` (checked: only candidates, each once),
    or None. Asked again once when the reply is unreadable or picks too few."""
    from ..llm.backend_factory import create_generation_backend
    from ..llm.channels import llm_configured
    from ..llm.protocol import GenerationConfig

    if config is None or not llm_configured(config):
        return None
    lines = []
    for f in finalists:
        flags = "; ".join(x["label"] for x in (f.get("risk") or {}).get("flags", [])) or "none"
        lines.append(
            f"- {f['symbol']} ({f.get('name')}), category {f.get('category')}, price {f.get('price')}, "
            f"day {f.get('change_percent')}%, cap {f.get('market_cap')}, technical: {f['reason']}; "
            f"fundamentals: {_figure_text(f.get('figures') or {})}; warning flags: {flags}"
        )
    role, ask = _PICK_PROMPTS[calls]
    prompt = (
        f"Market: {market}. Focus categories: {', '.join(categories) or 'any'}.\n"
        f"Candidates:\n" + "\n".join(lines) + "\n\n" + ask.format(count=count)
    )
    system = (
        role + " Use only the candidates listed, each at most once, and only their figures. "
        "Reply ONLY with JSON: "
        '[{"symbol": "...", "reason": "one sentence on what stands out, with figures", '
        '"watch": "one sentence on the main risk or weak figure to watch", '
        '"invalidator": "one sentence on what would weaken the case, e.g. a level or a figure"}]'
    )
    if not calls:
        from ..core.compliance import NO_CALLS_RULE

        system += "\n\n" + NO_CALLS_RULE
    by_symbol = {f["symbol"].upper(): f for f in finalists}
    want = min(count, len(finalists))
    backend = create_generation_backend(config)
    # Same market, categories and candidates within a 4-hour block: one AI pick
    # shared by every report and user (the prompt's prices move, the choice holds).
    now = datetime.now()
    scope = "|".join(["ideas", market, ",".join(sorted(categories)), str(count), str(calls),
                      ",".join(sorted(by_symbol)), now.strftime("%Y-%m-%d"), str(now.hour // 4)])
    chosen: list[dict] = []
    for attempt in range(2):
        ask_text = prompt if attempt == 0 else (
            prompt + f"\n\nYour last reply could not be used. Return exactly {want} items as a JSON list, "
            "with symbols copied from the candidate list.")
        try:
            text = backend.generate(ask_text, GenerationConfig(max_tokens=600, cache_scope=scope if attempt == 0 else None),
                                    system_prompt=system).text
        except Exception as exc:
            logger.warning("AI idea selection unavailable: %s", exc)
            return None
        chosen = []
        for pick in _parse_picks(text):
            if not isinstance(pick, dict):
                continue
            f = by_symbol.get(str(pick.get("symbol", "")).strip().upper())
            if f is None or any(c["symbol"] == f["symbol"] for c in chosen):
                continue  # not a candidate, or a repeat
            chosen.append({**f, "reason": str(pick.get("reason") or f["reason"]).strip(),
                           "watch": str(pick.get("watch") or "").strip() or None,
                           "invalidator": str(pick.get("invalidator") or "").strip() or None, "ai": True})
            if len(chosen) >= count:
                break
        if len(chosen) >= want:
            break
        logger.info("AI idea selection returned %d of %d usable picks (attempt %d)", len(chosen), want, attempt + 1)
    return chosen or None


def find_ideas(market: str, categories: list[str], count: int = 3, exclude: Iterable[str] = (),
               config=None, rows: Optional[list[dict]] = None, check=technical_check,
               figures=fetch_figures, calls: Optional[bool] = None) -> list[dict]:
    """`calls`: admins and the owner (the AI's ideas) or, False, a general
    user (the same screen, explained as facts); None = the current user's."""
    if calls is None:
        from ..core.compliance import report_calls

        calls = report_calls()
    market = "us" if market in ("global", "all") else market
    exclude_set = {s.upper() for s in exclude}
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    candidates = screen(rows, categories, exclude_set)

    finalists = []
    for row in candidates:
        tech = check(row)
        if tech:
            finalists.append({
                "symbol": row["symbol"], "name": row.get("name"), "market": row["market"],
                "category": row.get("category"), "price": row.get("price"), "currency": row.get("currency"),
                "change_percent": row.get("change_percent"), "market_cap": row.get("market_cap"),
                "high_52w": row.get("high_52w"), "low_52w": row.get("low_52w"),
                "volume": row.get("volume"), "close_date": row.get("close_date"), "sector": row.get("sector"),
                "series": row.get("series"), "type": row.get("type"),
                "technical": tech, "reason": _rule_reason(row, tech),
            })
    if not finalists:
        return []
    finalists.sort(key=lambda f: f["technical"]["score"], reverse=True)
    finalists = finalists[:max(FIGURES_FOR, count)]
    for f in finalists:
        f["figures"] = figures(f) or {}
    finalists = [f for f in finalists if not _weak(f["figures"])]
    from .risk_flags import assess

    for f in finalists:
        f["risk"] = assess(f, f["figures"])
    finalists = [f for f in finalists if f["risk"]["level"] != "high"]
    if not finalists:
        return []
    picked = _llm_pick(finalists, count, market, categories, config, calls) or []
    # Gaps (no AI, or it picked too few or too many of one kind) from the rule ranking.
    taken = {p["symbol"] for p in picked}
    return diversify(picked + [f for f in finalists if f["symbol"] not in taken], count)


def diversify(items: list[dict], count: int, per_category: int = MAX_PER_CATEGORY) -> list[dict]:
    """The first `count` items in order, with at most `per_category` from one
    category; skipped ones come back only if too few others qualify."""
    chosen, skipped, seen = [], [], {}
    for item in items:
        key = item.get("category") or item.get("symbol")
        if seen.get(key, 0) < per_category:
            chosen.append(item)
            seen[key] = seen.get(key, 0) + 1
        else:
            skipped.append(item)
        if len(chosen) >= count:
            return chosen
    return (chosen + skipped)[:count]
