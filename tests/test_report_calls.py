"""Generated reports never carry buy / hold / sell (marketmyna/core/compliance.py):
what the Smart report says instead."""

from dataclasses import replace

import pytest

from marketmyna.core import tenant
from marketmyna.core.config import Config
from marketmyna.services.analysis_run import Target
from marketmyna.services.report import ReportPrefs
from marketmyna.services.smart_report import html_report, run_smart, smart_message, without_calls
from marketmyna.storage import UserRecord
from tests.test_smart_report import NOW, FakeDispatcher, _row


@pytest.fixture(autouse=True)
def no_market_overview(monkeypatch):
    """No network: the smart message's Market overview is tested on its own."""
    monkeypatch.setattr("marketmyna.services.smart_report.market_block", lambda rows, prefs, config: None)


def _id(env, email):
    with tenant.system_scope(), env["db"].get_session() as s:
        return s.query(UserRecord).filter_by(email=email).one().id


def _general():
    return [without_calls(_row("TCS", 9, "buy", reasons=["at its buy point", "overbought"], valuation="undervalued",
                               facts={"return_on_equity": 0.22, "earnings_growth": 0.18, "debt_to_equity": 0.2, "trend": "uptrend"})),
            without_calls(_row("INFY", 5, "sell", facts={"return_on_equity": 0.04, "revenue_growth": -0.05, "debt_to_equity": 2.1, "trend": "downtrend"}))]


def test_general_message_has_readings_and_ranges_not_levels():
    prefs = ReportPrefs(smart=True, smart_top_n=2)
    _, body = smart_message(_general(), prefs, "en", "https://sp.example/r/x", NOW)
    assert "▲ TCS" in body and "· BULLISH" in body and "▼ INFY" in body and "· BEARISH" in body
    assert "Why: strong return on equity (ROE 22%), profit up 18% year on year" in body
    assert "Normal range" in body and "Buy ≤" not in body and "Sell ≥" not in body
    assert "not a buy or sell call" in body and "🟢" not in body and "🔴" not in body
    _, hindi = smart_message(_general(), prefs, "hi", None, NOW)
    assert "तेज़ी" in hindi and "मंदी" in hindi


def test_general_email_has_no_calls():
    html = html_report(_general(), "Report", NOW, None)
    assert "Bullish" in html and "Bearish" in html and "not a recommendation to buy, sell or hold" in html
    assert "high debt (debt/equity 2.1)" in html
    for word in ("BUY", "SELL", "Buy ≤", "Stop", "undervalued"):
        assert word not in html


def test_run_smart_always_strips_calls(tmp_path):
    config = replace(Config(), db_path=tmp_path / "t.db")
    prefs = ReportPrefs(smart=True, smart_top_n=2, smart_ai_top=0, smart_file="none")
    _, _, rows, token, _ = run_smart([Target(s, "india") for s in "AB"], prefs, config,
                                     dispatcher=FakeDispatcher(["telegram"]), snap=lambda s, m: _row(s, ord(s), "buy"))
    # A buy action never shows: the view comes from the figures and trend (outlook.py).
    assert "action" not in rows[0] and rows[0]["reading"] in ("bullish", "neutral", "bearish") and "why" in rows[0]
    from marketmyna.storage import DatabaseManager, ReportRunRecord, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as s:
        saved = s.query(ReportRunRecord).filter_by(token=token).one()
        assert saved.meta["compliance"] == "analytics"
        assert "buy_point" not in saved.rows[0]
