"""Report sections end to end: each checkbox controls exactly its own part
of the message and its data fetch, and every channel receives the whole
report (split, not silently cut) - offline."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from marketmyna.notifiers import base
from marketmyna.services import analysis_run
from marketmyna.services.report import SECTION_IDS, ReportPrefs, build_report

NOW = datetime(2026, 9, 25, 8, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

# A marker that appears in the message only when its section is on.
MARKERS = {
    "market": "Market overview",
    "calls": "Bullish / Neutral / Bearish",
    "portfolio": "Core: ₹",
    "alerts": "Your alerts",
    "hot_trade": "Hot for trading",
    "hot_invest": "Trending for investors",
    "levels": "Normal range ₹1,170.00",
    "ideas": "Stocks matching your screen (India)",
    "price": "Price ₹1,219.40",
    "ai": "AI summary: Uptrend intact",
    "technical": "Technical: RSI 41.20",
    "indicators": "Indicators: RSI 41.20",
    "fundamentals": "Fundamentals: Score 62/100",
    "risk": "Risk: Medium · swings ~21% a year · fell up to 26% from a high",
    "analysts": "Broker consensus of third-party analysts: bullish",
    "events": "Upcoming: Earnings 16 Oct 2999",
    "news": "News: Positive coverage",
    "valuation": "Valuation vs sector: P/E 21.1 vs 8.6",
}


def _full_result():
    return {
        "symbol": "RELIANCE", "market": "india", "ok": True, "name": "Reliance Industries",
        "quote": {"price": 1219.4, "change_percent": 0.5},
        "dashboard": {
            "decision_type": "buy", "outlook": "bullish", "analysis_summary": "Uptrend intact above the 50-day average.",
            "target_price": 1300, "stop_loss": 1150, "technical_signal": "bullish", "technical_confidence": 0.72,
            "risk_level": "medium",
            "opinions": [
                {"agent_name": "technical", "summary": "3 bullish indicators",
                 "details": {"indicators": {"rsi": {"value": 41.2, "signal": "neutral"}}}},
                {"agent_name": "risk", "details": {"volatility": 0.21, "max_drawdown": -0.26}},
                {"agent_name": "news", "signal": "bullish", "summary": "Positive coverage"},
            ],
        },
        "extras": {
            "high_52w": 1600, "low_52w": 1100,
            "fundamentals": {"overall_score": 62, "valuation": {"status": "fair", "value": 22.7}},
            "analysts": {"recommendation": "strong_buy", "target_mean": 1676.8, "count": 26},
            "events": {"earnings_date": "2999-10-16"},
            "news": [{"title": "Reliance expands_retail *today*", "source": "Mint"}],
            "valuation": {"position": 1.49, "zone": "above", "sector": "Energy", "multiples": [
                {"key": "pe", "label": "P/E", "value": 21.1, "sector_median": 8.6, "ratio": 2.45}]},
            "levels": {"price": 1219.4, "buy_point": 1180.0, "sell_point": 1290.0, "stop_loss": 1150.0, "atr": 22.3,
                       "normal_low": 1170.0, "normal_high": 1265.0, "week_low": 1190.0, "week_high": 1250.0,
                       "trend": "uptrend"},
        },
    }


def _build(sections):
    prefs = ReportPrefs(sections=sections)
    return build_report(
        [_full_result()], prefs, now=NOW,
        overview=[{"name": "NIFTY 50", "price": 22400, "change_percent": -0.9}],
        funds=[{"code": "118989", "name": "HDFC Mid Cap", "nav": 220.58, "change_percent": -0.35, "return_1m": -7.1, "return_1y": 4.2}],
        ideas=[{"symbol": "COFORGE", "market": "india", "price": 1749.1, "reason": "uptrend"}],
        portfolios=[{"name": "Core", "value": 250000, "currency_symbol": "₹", "day_change": 1200, "day_change_pct": 0.48,
                     "gain": 30000, "gain_pct": 13.6, "movers": [{"symbol": "RELIANCE", "change": 600, "change_pct": 0.5}]}],
        alerts={"fired": [{"symbol": "TCS", "message": "TCS rose to 3,500"}], "near": [], "active": 3},
        hot=[{"section": section, "area": area, "markets": {"india": [
                 {"key": "momentum", "title": "Momentum", "rows": [{"symbol": "IFCI", "change_percent": 3.8, "why": "+3.8% today"}]}]}}
             for section, area in (("hot_trade", "trader"), ("hot_invest", "investor"))],
    )[1]


@pytest.mark.parametrize("section", SECTION_IDS)
def test_each_section_is_controlled_by_its_checkbox(section):
    assert MARKERS.keys() == set(SECTION_IDS)
    on = _build([section])
    off = _build([s for s in SECTION_IDS if s != section])
    assert MARKERS[section] in on, f"{section} missing when it is the only section checked"
    assert MARKERS[section] not in off, f"{section} still shown when unchecked"


def test_all_sections_together_and_none():
    everything = _build(list(SECTION_IDS))
    assert all(m in everything for m in MARKERS.values())
    nothing = _build([])
    assert not any(m in nothing for m in MARKERS.values())
    # no per-stock section ticked: no stock block, just the header and disclaimer
    assert "RELIANCE" not in nothing and "Not investment advice" in nothing


def test_extras_fetched_only_for_checked_sections(monkeypatch):
    calls = []

    class FakeTicker:
        def __init__(self, sym):
            calls.append("ticker")

        @property
        def info(self):
            calls.append("info")
            return {"fiftyTwoWeekHigh": 1, "fiftyTwoWeekLow": 0.5, "recommendationKey": "buy", "targetMeanPrice": 2}

        @property
        def calendar(self):
            calls.append("calendar")
            return {}

    import sys
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))
    news_calls = []
    monkeypatch.setattr("marketmyna.data.news_search.stock_news", lambda *a, **k: news_calls.append(1) or [])

    assert analysis_run.collect_extras("TCS", "india", ["risk", "technical"]) == {}
    assert calls == [] and news_calls == []
    out = analysis_run.collect_extras("TCS", "india", ["analysts"])
    assert out["analysts"]["recommendation"] == "buy" and "calendar" not in calls and news_calls == []
    analysis_run.collect_extras("TCS", "india", ["events", "news"])
    assert "calendar" in calls and news_calls == [1]


class _Dispatcher:
    def __init__(self, routed):
        self.routed, self.sent = routed, {}

    def configured_channels(self, purpose=None):
        return list(self.routed)

    def send_each(self, messages, purpose=None):
        self.sent.update(messages)
        return {k: True for k in messages}


def _deliver(dispatcher, monkeypatch):
    prefs = ReportPrefs(sections=["calls"])
    return analysis_run.deliver_report([_full_result()], prefs, config=None, dispatcher=dispatcher)


def test_routed_channels_each_get_the_report(monkeypatch):
    d = _Dispatcher(["telegram", "email"])
    _, delivery = _deliver(d, monkeypatch)
    assert set(d.sent) == {"telegram", "email"} and delivery == {"telegram": True, "email": True}
    assert "" in d.sent["email"][1]


def test_no_routed_channel_sends_nothing(monkeypatch):
    d = _Dispatcher([])
    _, delivery = _deliver(d, monkeypatch)
    assert d.sent == {} and delivery == {}


# --------------------------------------------------------------- channels


def test_truncate_says_it_cut_and_respects_bytes():
    text = "\n".join(f"line {i} 📈 RELIANCE" for i in range(500))
    out = base.truncate(text, 1024)
    assert len(out) <= 1024 and out.endswith("Open MarketMyna for the full report.)")
    out_b = base.truncate("你好📈" * 3000, 4000, measure=base.utf8_len)
    assert base.utf8_len(out_b) <= 4000


def test_split_message_by_bytes():
    text = "\n".join("📈 " + "数据" * 50 for _ in range(200))
    chunks = base.split_message(text, 4000, measure=base.utf8_len)
    assert len(chunks) > 1 and all(base.utf8_len(c) <= 4000 for c in chunks)
    assert "\n".join(chunks) == text


class _Resp:
    def __init__(self, status=200, body=None, text="ok"):
        self.status_code, self._body, self.text = status, body or {}, text

    def json(self):
        return self._body


LONG = "\n".join(f"🟢 STOCK{i} · price ₹{i},000.00 · AI view: steady uptrend_continues *strong*" for i in range(300))


def test_discord_sends_every_part(monkeypatch):
    from marketmyna.notifiers import discord

    posts = []
    monkeypatch.setattr(discord.requests, "post", lambda url, json, timeout: posts.append(json["content"]) or _Resp(204))
    monkeypatch.setattr(discord.time, "sleep", lambda s: None)
    assert discord.DiscordSender(SimpleNamespace(discord_webhook_url="https://x")).send(LONG, title="Report")
    assert len(posts) > 1 and all(len(p) <= discord.DISCORD_MAX_LENGTH for p in posts)
    assert "STOCK299" in posts[-1] and posts[0].startswith("**Report**")


def test_google_chat_sends_every_part(monkeypatch):
    from marketmyna.notifiers import googlechat

    posts = []
    monkeypatch.setattr(googlechat, "http_ok", lambda ch, m, url, json, timeout: posts.append(json["text"]) or True)
    assert googlechat.GoogleChatSender(SimpleNamespace(google_chat_webhook_url="https://x")).send(LONG)
    assert len(posts) > 1 and "STOCK299" in posts[-1]


def test_wechat_splits_by_bytes(monkeypatch):
    from marketmyna.notifiers import wechat

    posts = []
    monkeypatch.setattr(wechat.requests, "post",
                        lambda url, json, timeout: posts.append(json["markdown"]["content"]) or _Resp(200, {"errcode": 0}))
    assert wechat.WechatSender(SimpleNamespace(wechat_webhook_url="https://x")).send(LONG)
    assert all(len(p.encode()) <= 4096 for p in posts) and "STOCK299" in posts[-1]


def test_telegram_escapes_and_splits(monkeypatch):
    from marketmyna.notifiers import telegram

    posts = []
    monkeypatch.setattr(telegram.requests, "post", lambda url, json, timeout: posts.append(json) or _Resp(200))
    s = telegram.TelegramSender(SimpleNamespace(telegram_bot_token="t", telegram_chat_id="1, 2"))
    assert s.send(LONG + "\nAT&T <b>not bold</b>", title="Daily <report>")
    assert {p["chat_id"] for p in posts} == {"1", "2"}
    assert all(p["parse_mode"] == "HTML" and len(p["text"]) <= 4096 for p in posts)
    first = posts[0]["text"]
    assert first.startswith("<b>Daily &lt;report&gt;</b>")
    assert "uptrend_continues *strong*" in first  # Markdown characters arrive verbatim
    assert "AT&amp;T &lt;b&gt;not bold&lt;/b&gt;" in posts[-1]["text"]


def test_fund_holdings_go_to_funds_section_not_analysis():
    from marketmyna.services.schedule_config import ScheduleConfig, resolve_funds, resolve_targets

    catalog = {
        "portfolios": [{"name": "Family", "symbols": [{"symbol": "RELIANCE", "market": "india"}], "funds": ["118989"]}],
        "watchlists": [{"id": 1, "name": "W", "symbols": [{"symbol": "AAPL", "market": "us"}], "funds": ["120716", "118989"]}],
    }
    cfg = ScheduleConfig(sources=["portfolio", "watchlist"], mf_codes=["100"])
    assert [(t.symbol, t.market) for t in resolve_targets(cfg, catalog=catalog)] == [("RELIANCE", "india"), ("AAPL", "us")]
    assert resolve_funds(cfg, catalog=catalog) == ["100", "118989", "120716"]


def test_funds_sit_under_the_portfolio_that_holds_them():
    """Mutual funds merged into Your portfolio (2026-10-27): held funds under
    their portfolio, picked / watched ones under "Funds you watch"."""
    funds = [{"code": "118989", "name": "HDFC Mid Cap", "nav": 220.58, "change_percent": -0.35, "return_1y": 4.2},
             {"code": "120716", "name": "UTI Nifty 50", "nav": 160.1, "change_percent": 0.2}]
    ports = [{"name": "Family MF", "value": 50000, "currency_symbol": "₹", "gain": 5000, "gain_pct": 11.1,
              "movers": [{"symbol": "118989", "name": "HDFC Mid Cap", "change": -120, "change_pct": -0.35}],
              "fund_codes": ["118989"]}]
    body = build_report([], ReportPrefs(sections=["portfolio"]), now=NOW, funds=funds, portfolios=ports)[1]
    head, watched = body.split("Funds you watch (not owned)")
    assert "Family MF: ₹50,000" in head and "▼ HDFC Mid Cap -0.35%" in head
    assert "• HDFC Mid Cap" in head and "1Y +4.20%" in head and "UTI Nifty 50" not in head
    assert "• UTI Nifty 50" in watched and "HDFC Mid Cap" not in watched
    assert "Mutual funds" not in body


def test_old_funds_tick_becomes_portfolio():
    from marketmyna.services.report import clean_sections

    assert clean_sections(["funds", "market"]) == ["market", "portfolio"]
    assert "funds" not in SECTION_IDS


def test_portfolio_snapshot_prices_funds_from_their_nav(monkeypatch):
    from marketmyna.services import analysis_run

    class Rec:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Q:
        def __init__(self, rows):
            self.rows = rows

        def order_by(self, *_):
            return self

        def filter(self, *_):
            return self

        def __iter__(self):
            return iter(self.rows)

    class Session:
        def query(self, model):
            if model.__name__ == "PortfolioRecord":
                return Q([Rec(id=1, name="MF")])
            return Q([Rec(symbol="118989", market="mf", quantity=100, avg_cost=200, current_price=0)])

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("marketmyna.storage.DatabaseManager.instance", lambda *_: SimpleNamespace(get_session=Session))
    fund = lambda code: {"code": code, "name": "HDFC Mid Cap", "nav": 220.0, "change_percent": 10.0}
    (p,) = analysis_run.portfolio_snapshots([], [], fund=fund)
    assert p["fund_codes"] == ["118989"] and p["value"] == 22000
    assert round(p["day_change"]) == 2000 and p["movers"][0]["name"] == "HDFC Mid Cap"
