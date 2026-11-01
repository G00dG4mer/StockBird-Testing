"""The report file Smart messaging sends with its short message.

Only the sections ticked in the Scheduler go in (2026-10-27; Market overview
stays in the message), each under a clear title, rendered as a PDF (to read)
or an Excel workbook (to sort and filter):

  summary     tiles (stocks, bullish / neutral / bearish counts, best / worst today)
  calls       Bullish / Neutral / Bearish from each company's fundamentals and
              price trend (marketmyna/services/outlook.py); never a buy / hold /
              sell call (marketmyna/core/compliance.py)
  portfolio   value, today's change and total gain, then each mutual fund
              held (and picked or watched) with its NAV and returns
  stocks      price, day, view, valuation vs sector and the AI summary
  guide       how to read the report, term by term
  cards       one per stock: ranges, trend, RSI, risk, next results, the AI
              summary and valuation vs sector

Every other ticked section goes in too (2026-10-27): alerts, hot for trading,
trending for investors and new stock ideas as tables; fundamentals, analyst
ratings and news on each stock's card. Only Market overview stays in the
message. The core set above calls no AI; stock ideas do (marketmyna/services/ideas.py).
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..core.compliance import outlook
from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)

WORKERS = 6
# Per-stock data the file needs from collect_extras (marketmyna/services/analysis_run.py).
FILE_EXTRAS = {"valuation", "events"}  # fetched only when their section is ticked
# Fetched too when the section is ticked: shown on each stock's card.
CARD_EXTRAS = {"fundamentals", "analysts", "news"}
FILE_TYPES = {"pdf": "pdf", "xlsx": "xlsx"}
# Marks AI-reviewed stocks (plain text: the PDF font has no emoji).
AI_TAG = " · AI"
DISCLAIMER = "MarketMyna · Computed from market data; AI notes may be wrong. Not investment advice."


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    note: str = ""
    # The columns the PDF shows when the page is too narrow for all (Excel keeps every one).
    pdf_columns: Optional[list[str]] = None


@dataclass
class Text:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Tile:
    """A summary figure at the top of the report."""
    label: str
    value: str
    sub: str = ""
    tone: Optional[str] = None  # up | down | warn | accent


@dataclass
class StockCard:
    """One stock's details, following the ticked sections."""
    symbol: str
    name: str
    call: str
    price: str
    change: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    # Groups of (label, text, tone) shown side by side: the AI's view, bull vs bear, the risk team.
    notes: list[list[tuple[str, str, Optional[str]]]] = field(default_factory=list)
    news: list[str] = field(default_factory=list)


@dataclass
class Document:
    title: str
    subtitle: str
    blocks: list = field(default_factory=list)
    highlights: list[Tile] = field(default_factory=list)
    cards: list[StockCard] = field(default_factory=list)
    # Shown in a box under the summary: what this report is and is not (general users).
    notice: str = ""
    # Name in the title band: an Enterprise organization's (branded_exports), else MarketMyna.
    brand: str = "MarketMyna"


# ------------------------------------------------------------- formatting

def _fmt(value, digits: int = 2) -> str:
    v = _num(value)
    if v is None:
        return ""
    return f"{v:,.{digits}f}" if abs(v) >= 1 else f"{v:.4f}"


def _pct(value, signed: bool = True) -> str:
    v = _num(value)
    if v is None:
        return ""
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _ratio_pct(value) -> str:
    """0.12 -> 12% (risk metrics and yields come as fractions)."""
    v = _num(value)
    return "" if v is None else f"{v * 100:.0f}%"


def _word(value) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


# ------------------------------------------------------------- building

def _extras(rows: list[dict], wanted=FILE_EXTRAS) -> dict:
    """symbol -> collect_extras() for the file's per-stock data (parallel)."""
    from .analysis_run import collect_extras

    good = [r for r in rows if "error" not in r]

    def one(r):
        try:
            return r["symbol"], collect_extras(r["symbol"], r["market"], wanted)
        except Exception as exc:
            logger.warning("Extras for %s unavailable: %s", r["symbol"], exc)
            return r["symbol"], {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return dict(pool.map(one, good))


def _section_tables(rows: list[dict], prefs, config, sections: set) -> list[Table]:
    """The report-wide sections ticked in the Scheduler, as tables: alerts,
    hot for trading, trending for investors and stocks matching your screen. Each is
    best effort; one that fails is left out."""
    from . import analysis_run
    from .report import CURRENCY_SYMBOLS, INVEST_TITLES, MARKET_NAMES, _invest_figures

    results = _results_like(rows)
    out: list[Table] = []
    if "alerts" in sections:
        try:
            digest = analysis_run.alert_digest(results, config)
            fired = [[e["symbol"], "Fired", e.get("message") or ""] for e in digest.get("fired", [])]
            near = [[a["symbol"], "Close", f"{a['describe']} · {abs(a['distance_pct']):.1f}% away"]
                    for a in digest.get("near", [])]
            if fired or near:
                out.append(Table("Your alerts", ["Stock", "Status", "Alert"], fired + near,
                                 note=f"{digest.get('active', 0)} alerts active."))
        except Exception as exc:
            logger.warning("Alerts unavailable for the report file: %s", exc)
    hot_sections = {"hot_trade", "hot_invest"} & sections
    if hot_sections:
        try:
            blocks = analysis_run.hot_blocks(results, hot_sections,
                                             invest_markets=getattr(prefs, "hot_invest_markets", None),
                                             invest_detail="hot_invest" in hot_sections)
            for block in blocks:
                invest = block["section"] == "hot_invest"
                table = Table("Trending for investors" if invest else "Hot for trading",
                              ["Market", "List", "Stock", "Name", "Day", "Why"])
                for market, boards in block["markets"].items():
                    for b in boards:
                        title = INVEST_TITLES.get(b["key"], (b["title"], ""))[0] if invest else b["title"]
                        for row in b["rows"]:
                            why = (_invest_figures(row) if invest and block.get("detail") else "") or row.get("why") or ""
                            table.rows.append([MARKET_NAMES.get(market, market), title, row["symbol"],
                                               row.get("name") or "", _pct(row.get("change_percent")), why])
                if table.rows:
                    table.note = "Screens of company and market figures, not recommendations." if invest else ""
                    out.append(table)
        except Exception as exc:
            logger.warning("Hot stocks unavailable for the report file: %s", exc)
    if "ideas" in sections:
        try:
            from .ideas import find_ideas

            ideas = []
            for market in getattr(prefs, "ideas_markets", None) or [prefs.ideas_market]:
                ideas += find_ideas(market, prefs.ideas_categories, prefs.ideas_count,
                                    exclude=[r["symbol"] for r in results], config=config, calls=False)
            if ideas:
                table = Table("Stocks matching your screen",
                              ["Stock", "Name", "Market", "Price", "Day", "Figures", "Why", "Watch"],
                              note="A screen of trend and company figures with an AI note, not a recommendation to buy.")
                for i in ideas:
                    price, hi, lo = (_num(i.get(k)) for k in ("price", "high_52w", "low_52w"))
                    figures = _invest_figures({**(i.get("figures") or {}),
                                               "from_high": (price / hi - 1) * 100 if price and hi else None,
                                               "from_low": (price / lo - 1) * 100 if price and lo else None})
                    table.rows.append([i["symbol"], i.get("name") or "", MARKET_NAMES.get(i["market"], i["market"]),
                                       f"{CURRENCY_SYMBOLS.get(i['market'], '')}{_fmt(price)}",
                                       _pct(i.get("change_percent")), figures, i.get("reason") or "", i.get("watch") or ""])
                out.append(table)
        except Exception as exc:
            logger.warning("Stock ideas unavailable for the report file: %s", exc)
    return out


def _results_like(rows: list[dict]) -> list[dict]:
    """Smart rows in the shape the normal report helpers take."""
    return [{"symbol": r["symbol"], "market": r["market"],
             "quote": {"price": r.get("price"), "change_percent": r.get("change_percent")},
             "dashboard": {}} for r in rows if "error" not in r]


def _fund_cells(f: Optional[dict], code: str) -> list:
    f = f or {}
    return [f.get("name") or code, _fmt(f.get("nav"), 4 if (_num(f.get("nav")) or 0) < 100 else 2),
            _pct(f.get("change_percent")), _pct(f.get("return_1m")), _pct(f.get("return_1y"))]


def _call(r: dict) -> str:
    """The Bullish / Neutral / Bearish view, never a call."""
    from .smart_report import reading_label

    return reading_label(r) + (AI_TAG if r.get("ai") else "")


def _why(r: dict) -> str:
    if "reading" in r and r.get("why"):  # a general user: the figures behind the view
        return r["why"]
    return r.get("ai_summary") or ", ".join(r.get("reasons") or [])


def _valuation(r: dict, ex: dict) -> str:
    """Valuation against the sector median, as a comparison: an
    "undervalued / overvalued" verdict would be a call."""
    val = ex.get("valuation") or {}
    position = _num(val.get("position"))
    sector = val.get("sector") or "sector"
    if position:
        gap = (position - 1) * 100
        where = (f"in line with the {sector} median" if abs(gap) < 1 else
                 f"{abs(gap):.0f}% {'below' if gap < 0 else 'above'} the {sector} median")
        return f"Priced {where}"
    pe = _num(r.get("pe"))
    return f"P/E {pe:.1f}; no sector median to compare" if pe else ""


# Per-stock sections, in the order their figures appear on a stock's card.
STOCK_SECTIONS = ("calls", "price", "levels", "technical", "indicators", "risk", "fundamentals", "valuation",
                  "analysts", "events", "ai", "news")


def _stock_table(rows: list[dict], extras: dict, sections: set) -> Optional[Table]:
    """One row per stock with the ticked headline figures only."""
    from .report import CURRENCY_SYMBOLS, MARKET_NAMES

    view, price, value = "calls" in sections, "price" in sections, "valuation" in sections
    why = view or "ai" in sections
    if not (view or price or value or why):
        return None
    multi = len({r["market"] for r in rows}) > 1
    cols = (["Stock", "Name"] + (["Market"] if multi else []) + (["View"] if view else [])
            + (["Price", "Day"] if price else []) + (["Valuation vs sector"] if value else []) + (["Why"] if why else []))
    note = ""
    if view:
        note = ("View: Bullish, Neutral or Bearish from the company's figures and price trend; Why lists them. "
                "A description of the data, not a recommendation.")
    table = Table("Stocks at a glance", cols, note=note)
    for r in rows:
        if "error" in r:
            table.rows.append([r["symbol"], f"no data: {str(r['error'])[:60]}"] + [""] * (len(cols) - 2))
            continue
        cur = CURRENCY_SYMBOLS.get(r["market"], "")
        table.rows.append([r["symbol"], r.get("name") or ""] + ([MARKET_NAMES.get(r["market"], r["market"])] if multi else [])
                          + ([_call(r)] if view else [])
                          + ([f"{cur}{_fmt(r.get('price'))}", _pct(r.get("change_percent"))] if price else [])
                          + ([_valuation(r, extras.get(r["symbol"]) or {})] if value else [])
                          + ([_why(r) if view else (r.get("ai_summary") or "")] if why else []))
    return table


def _band_position(r: dict) -> str:
    """Where the price sits in its normal (20-day) range: 0% bottom, 100% top."""
    low, high, price = _num(r.get("normal_low")), _num(r.get("normal_high")), _num(r.get("price"))
    if None in (low, high, price) or high <= low:
        return ""
    pos = (price - low) / (high - low) * 100
    return f"{pos:.0f}%" + (" (above it)" if pos > 100 else " (below it)" if pos < 0 else "")


def _rsi_word(rsi) -> str:
    v = _num(rsi)
    if v is None:
        return ""
    return f"{v:.0f}" + (" (fast rise)" if v >= 70 else " (fast fall)" if v <= 30 else "")


def _range_position(r: dict) -> str:
    """Where today's price sits between the 52-week low (0%) and high (100%)."""
    low, high, price = _num(r.get("low_52w")), _num(r.get("high_52w")), _num(r.get("price"))
    if None in (low, high, price) or high <= low:
        return ""
    return f"{(price - low) / (high - low) * 100:.0f}% up from low"


def _card(r: dict, ex: dict, sections: set) -> Optional[StockCard]:
    """One stock's figures, for the ticked sections only; None when none of
    them has anything for this stock."""
    from .report import CURRENCY_SYMBOLS

    cur = CURRENCY_SYMBOLS.get(r["market"], "")
    facts: list[tuple[str, str]] = []

    def add(label: str, value) -> None:
        if value not in (None, "", "–", " ()"):
            facts.append((label, str(value)))

    def money(value) -> str:
        return f"{cur}{_fmt(value)}" if _fmt(value) else ""

    if "price" in sections:
        add("52-week range", f"{money(r.get('low_52w'))} – {money(r.get('high_52w'))}"
            if _fmt(r.get("low_52w")) and _fmt(r.get("high_52w")) else "")
        add("Where it sits", _range_position(r))
    if "levels" in sections:
        add("Normal range", f"{money(r.get('normal_low'))} – {money(r.get('normal_high'))}"
            if _fmt(r.get("normal_low")) else "")
        add("Expected 1-week range", f"{money(r.get('week_low'))} – {money(r.get('week_high'))}"
            if _fmt(r.get("week_low")) else "")
        add("Average daily move", money(r.get("atr")))
    if "technical" in sections or "indicators" in sections:
        add("Trend", _word(r.get("trend")))
        add("RSI (14)", _rsi_word(r.get("rsi")))
    if "indicators" in sections:
        add("Position in normal range", _band_position(r))
    if "risk" in sections:
        add("Yearly swing", _ratio_pct(r.get("volatility")))
        add("Worst fall from a high", _ratio_pct(abs(_num(r.get("max_drawdown")) or 0) or None))
    fund = ex.get("fundamentals") or {}
    if "fundamentals" in sections and fund:
        score = fund.get("quality_score", fund.get("overall_score"))
        add("Quality score", f"{score}/100" if score is not None else "")
        add("P/E", _fmt(r.get("pe"), 1))
        add("ROE", _pct(((fund.get("profitability") or {}).get("roe") or {}).get("value"), signed=False))
        add("Revenue growth", _pct(((fund.get("growth") or {}).get("revenue_growth") or {}).get("value")))
        add("Financial health", _word((fund.get("financial_health") or {}).get("rating")))
        add("Dividend yield", _pct((fund.get("dividend") or {}).get("yield"), signed=False))
    an = ex.get("analysts") or {}
    if "analysts" in sections and an.get("recommendation"):
        # Short values: a card cell holds about 25 characters.
        # A direction (bullish / neutral / bearish), without the brokers' price target.
        add("Broker consensus", _word(outlook(an["recommendation"]) or an["recommendation"])
            + (f" · {an['count']} analysts" if an.get("count") else ""))
    ev = ex.get("events") or {}
    if "events" in sections:
        add("Next results", str(ev.get("earnings_date") or "")[:10])
        add("Ex-dividend", str(ev.get("ex_dividend_date") or "")[:10])

    summary = []
    if "calls" in sections and r.get("why"):
        summary.append(("Why " + _call(r).split(" ", 1)[-1].replace(AI_TAG, "").strip().lower(), r["why"], "accent"))
    if "ai" in sections and r.get("ai") and r.get("ai_summary"):
        summary.append(("AI summary", r["ai_summary"], "accent"))
    if "valuation" in sections and _valuation(r, ex):
        summary.append(("Valuation vs sector", _valuation(r, ex), "accent"))
    notes: list = [summary] if summary else []
    news = [f"{n.get('title')}" + (f" — {n['source']}" if n.get("source") else "")
            for n in (ex.get("news") or [])[:3] if n.get("title")] if "news" in sections else []
    if not (facts or notes or news):
        return None
    return StockCard(symbol=r["symbol"], name=r.get("name") or "", call=_call(r) if "calls" in sections else "",
                     price=f"{cur}{_fmt(r.get('price'))}", change=_pct(r.get("change_percent")),
                     facts=facts, notes=notes, news=news)


def _highlights(rows: list[dict], good: list[dict], sections: set) -> list[Tile]:
    ai = sum(1 for r in good if r.get("ai"))
    tiles = [Tile("Stocks", str(len(rows)), f"{ai} reviewed by the AI" if ai else "in this report", "accent")]
    if good and "calls" in sections:
        counts = {k: sum(1 for r in good if r.get("reading") == k) for k in ("bullish", "neutral", "bearish")}
        tiles += [Tile("Bullish", str(counts["bullish"]), "figures lean up", "up"),
                  Tile("Neutral", str(counts["neutral"]), "figures split", "warn"),
                  Tile("Bearish", str(counts["bearish"]), "figures lean down", "down")]
    moves = [r for r in good if _num(r.get("change_percent")) is not None]
    if moves and "price" in sections:
        best = max(moves, key=lambda r: r["change_percent"])
        worst = min(moves, key=lambda r: r["change_percent"])
        tiles.append(Tile("Best today", _pct(best["change_percent"]), best["symbol"], "up" if best["change_percent"] >= 0 else "down"))
        tiles.append(Tile("Worst today", _pct(worst["change_percent"]), worst["symbol"], "down" if worst["change_percent"] < 0 else "up"))
    return tiles


def _guide(sections: set) -> Optional[Table]:
    """"How to read this report": the terms of the ticked sections only, in plain words."""
    terms: list[tuple[str, str]] = []
    if "calls" in sections:
        terms += [("View", "▲ Bullish, ◆ Neutral or ▼ Bearish. Each figure counts +1 or -1: return on equity, profit "
                           "and sales growth, net margin, debt, P/E against its sector median and the price trend. "
                           "A net +2 reads Bullish, -2 Bearish, anything between Neutral. It describes the data and "
                           "is not a recommendation."),
                  ("Why", "The figures behind the view, strongest first, and the main one pointing the other way.")]
    if "price" in sections:
        terms.append(("52-week range", "The year's lowest and highest price, and where today's price sits between them."))
    if "levels" in sections:
        terms += [("Normal range", "Where the price usually trades (the 20-day band)."),
                  ("Expected 1-week range", "Where about 2 of 3 weeks end, from recent swings. Not a target.")]
    if "technical" in sections or "indicators" in sections:
        terms += [("Trend", "Uptrend: price above its 50- and 200-day averages; downtrend: below both; else sideways."),
                  ("RSI", "Momentum from 0 to 100: above 70 a fast rise, below 30 a fast fall.")]
    if "risk" in sections:
        terms += [("Yearly swing", "How much the price typically moves in a year (volatility)."),
                  ("Worst fall from a high", "The deepest drop from a peak in the past year (max drawdown).")]
    if "fundamentals" in sections:
        terms.append(("Quality score", "Profitability, financial health and growth, 0 to 100."))
    if "valuation" in sections:
        terms.append(("Valuation vs sector", "P/E, P/B and P/S against the median of the sector's largest companies; "
                                             "a comparison, not a verdict."))
    if "ai" in sections:
        terms.append(("AI summary", "Written by an AI model from the figures. It can be wrong."))
    if not terms:
        return None
    return Table("How to read this report", ["Term", "What it means"], [list(t) for t in terms])


def build_document(rows: list[dict], prefs, config, now: datetime, title: str) -> Document:
    """The report file: the ticked sections only, each clearly titled (see the module doc)."""
    from .smart_report import READING_LABELS, READING_NOTE, reading_label

    good = [r for r in rows if "error" not in r]
    sections = set(getattr(prefs, "sections", None) or [])
    ai_count = sum(1 for r in good if r.get("ai"))
    doc = Document(title, f"{now:%d %b %Y, %H:%M %Z}".strip() + f" · {len(rows)} stocks"
                          + (f" · {ai_count} reviewed by the AI" if ai_count else ""),
                   notice="" if not sections & {"calls", "ai", "ideas", "hot_invest"} else READING_NOTE)

    results = _results_like(rows)

    if good and "calls" in sections:
        groups = {k: [r["symbol"] + (AI_TAG if r.get("ai") else "") for r in good if r.get("reading") == k]
                  for k in READING_LABELS}
        doc.blocks.append(Table("Bullish / Neutral / Bearish", ["View", "Stocks", "Count"],
                                [[reading_label({"reading": k}), ", ".join(v) or "—", len(v)] for k, v in groups.items()],
                                note="Grouped by what each company's fundamentals and price trend show today; see "
                                     "Why for each stock. This sorts the data; it does not say what to do."))

    if config is not None and "portfolio" in sections:
        try:
            from .analysis_run import fund_cache, portfolio_snapshots

            nav = fund_cache()
            ports = portfolio_snapshots(prefs.portfolios, results, config, fund=nav)
            if ports:
                doc.blocks.append(Table("Your portfolio", ["Portfolio", "Value", "Today", "Today %", "Total gain", "Gain %", "Moved most"], [
                    [p["name"], f"{p.get('currency_symbol', '')}{_fmt(p.get('value'), 0)}", _fmt(p.get("day_change"), 0),
                     _pct(p.get("day_change_pct")), _fmt(p.get("gain"), 0), _pct(p.get("gain_pct")),
                     ", ".join(f"{m['symbol']} {_pct(m.get('change_pct'))}" for m in p.get("movers", []))]
                    for p in ports]))
            fund_rows, held = [], set()
            for p in ports:
                for code in p.get("fund_codes", []):
                    held.add(code)
                    fund_rows.append([p["name"], *_fund_cells(nav(code), code)])
            for code in dict.fromkeys(str(c) for c in getattr(prefs, "funds", None) or []):
                if code not in held:
                    fund_rows.append(["Watching", *_fund_cells(nav(code), code)])
            if fund_rows:
                doc.blocks.append(Table("Your mutual funds", ["Portfolio", "Fund", "NAV", "Day", "1M", "1Y"], fund_rows,
                                        note="Funds held in each portfolio, then the ones you picked or watch."))
        except Exception as exc:
            logger.warning("Portfolio unavailable for the report file: %s", exc)

    if config is not None and good:
        doc.blocks += _section_tables(rows, prefs, config, sections)

    wanted = (FILE_EXTRAS & sections) | (CARD_EXTRAS & sections)
    extras = _extras(rows, wanted) if wanted else {}
    table = _stock_table(rows, extras, sections)
    if table:
        doc.blocks.append(table)

    guide = _guide(sections) if good else None
    if guide:
        doc.blocks.append(guide)
    doc.cards = [c for c in (_card(r, extras.get(r["symbol"]) or {}, sections) for r in good) if c]
    doc.highlights = _highlights(rows, good, sections)
    return doc


# ------------------------------------------------------------- rendering

def to_pdf(doc: Document) -> bytes:
    """A4 landscape: title band, summary tiles, the sections, a card per stock."""
    from .smart_pdf import render

    return render(doc, DISCLAIMER)


def _cell_value(value):
    """'₹1,312.40' -> 1312.4, '+1.2%' -> (0.012, percent format), so Excel
    sorts and filters numbers as numbers; anything else stays as it is."""
    from .report import CURRENCY_SYMBOLS

    if not isinstance(value, str) or not any(ch.isdigit() for ch in value):  # also keeps "INF", "NAN" as text
        return value, None
    text = value.replace(",", "")
    for sign in sorted(filter(None, CURRENCY_SYMBOLS.values()), key=len, reverse=True):
        text = text.removeprefix(sign)
    percent = text.endswith("%")
    try:
        number = float(text.rstrip("%"))
    except ValueError:
        return value, None
    if percent:
        return number / 100, "0.0%" if "." in text else "0%"
    return number, "#,##0.00" if "." in text else "#,##0"


def to_xlsx(doc: Document) -> bytes:
    """A styled workbook: a Summary sheet (title, summary figures, the
    report-wide tables), "Stocks" to sort and filter, "Stock details" with
    every ticked detail and the AI's notes per stock, and a sheet for any
    other long table. Numbers are stored as numbers; gains are green,
    losses red, calls coloured."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    from .smart_pdf import tone_of

    fill = lambda hex_: PatternFill("solid", fgColor=hex_)  # noqa: E731
    tone_font = {"up": "0B7A52", "down": "C02F2F", "warn": "9A6408", "accent": "1F3A8A"}
    tone_fill = {"up": "E3F4EC", "down": "FBE7E7", "warn": "FDF3DC", "accent": "E8EDF8"}
    thin = Side(style="thin", color="DCE0E8")
    grid = Border(bottom=thin, top=thin, left=thin, right=thin)
    head_font, head_fill = Font(bold=True, color="FFFFFF", size=10), fill("0F2A5C")
    top_left = Alignment(vertical="top", wrap_text=True)
    signed_pct = '[Color10]+0.0%;[Red]-0.0%;0.0%'

    wb = Workbook()

    def banner(ws, width: int) -> None:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
        ws.cell(1, 1, doc.title).font = Font(bold=True, size=16, color="FFFFFF")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
        ws.cell(2, 1, doc.subtitle).font = Font(italic=True, size=9, color="D6DEEE")
        for row in (1, 2):
            for col in range(1, width + 1):
                ws.cell(row, col).fill = head_fill
        ws.row_dimensions[1].height = 30
        ws.cell(1, 1).alignment = Alignment(vertical="center", indent=1)
        ws.cell(2, 1).alignment = Alignment(vertical="center", indent=1)

    def style_value(cell, value, column: str) -> None:
        number, number_format = _cell_value(value)
        cell.value = number
        cell.border = grid
        cell.alignment = Alignment(vertical="top", wrap_text=isinstance(number, str) and len(number) > 40,
                                   horizontal="right" if number_format else None)
        tone = tone_of(value) if isinstance(value, str) else None
        if number_format:
            signed = isinstance(value, str) and value[:1] in "+-−" and number_format.endswith("%")
            cell.number_format = signed_pct if signed else number_format
        elif tone and column in ("Call", "Result", "Indicators"):
            cell.font = Font(bold=True, color=tone_font[tone])
            cell.fill = fill(tone_fill[tone])
            cell.alignment = Alignment(horizontal="center", vertical="top")
        elif tone in ("up", "down"):
            cell.font = Font(color=tone_font[tone])

    def put_table(ws, table: Table, row: int, zebra: bool = True) -> int:
        for j, name in enumerate(table.columns, start=1):
            c = ws.cell(row, j, name)
            c.font, c.fill, c.border = head_font, head_fill, grid
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 20
        for i, values in enumerate(table.rows, start=1):
            for j, (name, value) in enumerate(zip(table.columns, values), start=1):
                c = ws.cell(row + i, j)
                style_value(c, value, name)
                if j == 1:
                    c.font = Font(bold=True, color="0F2A5C")
                if zebra and i % 2 == 0 and c.fill.fgColor.rgb in (None, "00000000"):
                    c.fill = fill("F5F7FA")
        row += len(table.rows) + 1
        if table.note:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(len(table.columns), 1))
            c = ws.cell(row, 1, table.note)
            c.font, c.alignment = Font(italic=True, size=8, color="6B7280"), Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 14 * (1 + len(table.note) // 140)
            row += 1
        return row

    def section_title(ws, row: int, title: str, width: int) -> int:
        c = ws.cell(row, 1, title)
        c.font = Font(bold=True, size=12, color="0F2A5C")
        for col in range(1, max(width, 1) + 1):
            ws.cell(row, col).border = Border(bottom=Side(style="medium", color="1F3A8A"))
        return row + 1

    def fit(ws, first_row: int, cap: int = 60, wide: Optional[set] = None) -> None:
        for i, col in enumerate(ws.iter_cols(min_row=first_row, max_row=min(ws.max_row, 400)), start=1):
            longest = max((len(str(c.value)) for c in col if c.value is not None and not
                           (isinstance(c.value, str) and len(c.value) > 140)), default=8)
            width = 55 if wide and i in wide else min(max(longest + 3, 9), cap)
            ws.column_dimensions[get_column_letter(i)].width = width

    def page_setup(ws) -> None:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_view.showGridLines = False

    # ---- Summary
    summary = wb.active
    summary.title = "Summary"
    small = [b for b in doc.blocks if not (isinstance(b, Table) and (b.title.startswith("Stocks") or len(b.rows) > 8))]
    width = max([len(doc.highlights)] + [len(b.columns) for b in small if isinstance(b, Table)] + [6])
    banner(summary, width)
    row = 4
    if doc.notice:
        summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        c = summary.cell(row, 1, doc.notice)
        c.font = Font(bold=True, size=10, color="0F2A5C")
        c.fill = fill("EEF3FB")
        c.alignment = Alignment(wrap_text=True, vertical="center", indent=1)
        c.border = Border(left=Side(style="thick", color="1F3A8A"))
        summary.row_dimensions[row].height = 48
        row += 2
    if doc.highlights:
        for j, t in enumerate(doc.highlights, start=1):
            color = tone_font.get(t.tone, "0F2A5C")
            for k, (value, font) in enumerate(((t.label.upper(), Font(bold=True, size=8, color="6B7280")),
                                               (t.value, Font(bold=True, size=18, color=color)),
                                               (t.sub, Font(size=8, color="6B7280")))):
                c = summary.cell(row + k, j, value)
                c.font, c.fill = font, fill("F7F9FC")
                c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                c.border = Border(left=Side(style="thick", color=color), top=thin if k == 0 else None,
                                  bottom=thin if k == 2 else None, right=thin)
        summary.row_dimensions[row + 1].height = 28
        row += 4
    for b in small:
        row = section_title(summary, row, b.title, len(b.columns) if isinstance(b, Table) else width)
        if isinstance(b, Table):
            row = put_table(summary, b, row)
        else:
            for line in b.lines:
                summary.cell(row, 1, line).alignment = Alignment(wrap_text=True)
                row += 1
        row += 1
    c = summary.cell(row, 1, DISCLAIMER)
    c.font = Font(italic=True, size=8, color="6B7280")
    fit(summary, 4, cap=48)
    page_setup(summary)

    used = {"Summary"}

    def sheet(title: str):
        name = title[:31].replace("/", "-")
        while name in used:
            name = name[:28] + "_2"
        used.add(name)
        ws = wb.create_sheet(name)
        page_setup(ws)
        return ws

    # ---- big tables (the stocks at a glance or a long track record)
    for b in doc.blocks:
        if b in small:
            continue
        ws = sheet("Stocks" if b.title.startswith("Stocks") else b.title)
        end = put_table(ws, b, 1)
        ws.freeze_panes = "B2"
        if b.rows:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(b.columns))}{len(b.rows) + 1}"
        fit(ws, 1)
        if b.note and end:
            ws.row_dimensions[end - 1].height = 28

    # ---- Stock details: one row per stock with every ticked detail and the AI's notes
    if doc.cards:
        labels: list[str] = []
        for card in doc.cards:
            labels += [label for label, _ in card.facts if label not in labels]
        # The AI's reasoning and the computed reasons share one column.
        same = {"Why (computed)": "AI view"}
        note_labels: list[str] = []
        for card in doc.cards:
            for group in card.notes:
                note_labels += [same.get(label, label) for label, _, _ in group
                                if same.get(label, label) not in note_labels]
        news = any(card.news for card in doc.cards)
        columns = ["Stock", "Name", "Call", "Price", "Day"] + labels + note_labels + (["News"] if news else [])
        rows = []
        for card in doc.cards:
            facts = dict(card.facts)
            notes = {same.get(label, label): text for group in card.notes for label, text, _ in group}
            rows.append([card.symbol, card.name, card.call, card.price, card.change]
                        + [facts.get(label, "") for label in labels]
                        + [notes.get(label, "") for label in note_labels]
                        + (["\n".join(card.news)] if news else []))
        ws = sheet("Stock details")
        put_table(ws, Table("Stock details", columns, rows), 1)
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
        long_cols = {i for i, name in enumerate(columns, start=1) if name in note_labels or name == "News"}
        fit(ws, 1, wide=long_cols)
        for i in range(2, len(rows) + 2):
            for j in long_cols:
                ws.cell(i, j).alignment = top_left
            if long_cols:
                longest = max(len(str(ws.cell(i, j).value or "")) for j in long_cols)
                ws.row_dimensions[i].height = min(max(15, 15 * (longest // 55 + 1)), 400)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report_file(rows: list[dict], prefs, config, now: datetime, title: str) -> Optional[tuple[str, bytes]]:
    """(filename, bytes) in the format the user picked, or None for "none"
    or when building fails (the short message still goes out)."""
    kind = FILE_TYPES.get(getattr(prefs, "smart_file", "pdf"))
    if not kind or not rows:
        return None
    try:
        doc = build_document(rows, prefs, config, now, title)
        data = to_pdf(doc) if kind == "pdf" else to_xlsx(doc)
    except Exception:
        logger.exception("Smart report file could not be built")
        return None
    return f"MarketMyna-report-{now:%Y-%m-%d}.{kind}", data
