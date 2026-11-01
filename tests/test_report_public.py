"""Public (analytics) deploys: reports, the decision agent and the dashboard
carry facts and explanations only - no buy / hold / sell, target or stop
(docs/future/sebi-compliance-mode.md)."""

from types import SimpleNamespace

import pytest

from marketmyna.agent.agents import DecisionAgent
from marketmyna.agent.dashboard import build_dashboard
from marketmyna.services import report
from marketmyna.services.report import ReportPrefs, build_report, section_catalog
from tests.test_report_delivery import NOW, _full_result


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")


def _body(sections):
    other = _full_result()
    other.update(symbol="TCS", quote={"price": 3000, "change_percent": -2.1}, extras={
        "high_52w": 3050, "low_52w": 2500,
        "facts": {"return_on_equity": 0.45, "earnings_growth": 0.12, "debt_to_equity": 0.1, "trend": "sideways"}})
    return build_report([_full_result(), other], ReportPrefs(sections=sections), now=NOW,
                        ideas=[{"symbol": "COFORGE", "market": "india", "price": 1749.1, "reason": "uptrend"}])[1]


def test_public_report_has_no_calls_targets_or_stops(public):
    body = _body([s for s in report.SECTION_IDS])
    for banned in ("BUY", "Buy", "Sell", "strong buy", "Today's calls", "Target", "Stop", "🟢", "🔴", "Overvalued",
                   "Valuation fair"):
        assert banned not in body, banned
    assert "Bullish / Neutral / Bearish" in body
    assert "▲ Bullish: RELIANCE, TCS" in body and "• TCS: strong return on equity (ROE 45%)" in body
    assert "▲ TCS · " in body  # its own block carries the view too
    assert "not a buy or sell call" in body
    assert "AI summary:" in body
    assert "Technical: RSI 41.20" in body  # the fixture's commentary has a verdict word, so values only
    assert "Broker consensus of third-party analysts:" in body
    assert "Valuation vs sector: P/E 21.1 vs 8.6 → 1.49× (Above sector)" in body
    # Stock ideas go out as a screen with an AI note, never as picks to buy.
    assert "Stocks matching your screen (India)" in body and "New ideas to research" not in body
    assert "not a recommendation to buy" in body


def test_catalog_uses_plain_labels(public):
    cat = {sid: label for sid, label, _, _ in section_catalog()}
    assert cat["calls"] == "Bullish / Neutral / Bearish list" and cat["ideas"] == "Stocks matching your screen"
    assert "valuation" in cat


class _Backend:
    def __init__(self, text):
        self.text = text

    def generate(self, prompt, config, system_prompt=""):
        self.system = system_prompt
        return SimpleNamespace(text=self.text)


def test_public_decision_agent_explains_without_a_call(public, monkeypatch):
    monkeypatch.setattr("marketmyna.agent.agents._call_llm",
                        lambda backend, system, prompt, scope=None: '{"rationale": "Revenue grew 6%; margins steady; watch debt."}')
    ctx = SimpleNamespace(symbol="AAPL", market="us", quote={"price": 333}, opinions=[], news=[])
    op = DecisionAgent().run(ctx, None)
    assert op.signal is None and op.details == {}
    assert op.summary.startswith("Revenue grew")


def test_ai_summary_explains_the_figures_based_view_in_three_sentences(public, monkeypatch):
    """AI view (2026-10-27): a general user's AI summary sees the same
    Bullish / Neutral / Bearish view as the list, short and crisp."""
    seen = {}

    def llm(backend, system, prompt, scope=None):
        seen.update(system=system, prompt=prompt)
        return '{"rationale": "Strong ROE backs the view. News is quiet. Watch the high P/E."}'

    monkeypatch.setattr("marketmyna.agent.agents._call_llm", llm)
    info = {"returnOnEquity": 0.3, "earningsGrowth": 0.2, "debtToEquity": 10.0}
    ctx = SimpleNamespace(symbol="TCS", market="india", quote={"price": 3400}, opinions=[], news=[],
                          info=info, history=None, outlook_facts=None)
    op = DecisionAgent().run(ctx, None)
    assert "Figures-based view: Bullish (in favour: strong return on equity (ROE 30%)" in seen["prompt"]
    assert "at most 3 short, plain sentences" in seen["system"] and "Use that view as the outlook" in seen["system"]
    assert op.signal == "bullish"  # the list and the summary carry the same view
    assert ctx.outlook_facts["return_on_equity"] == 0.3  # the report's list reuses these
    assert op.summary.startswith("Strong ROE")


def test_ai_view_is_cut_at_a_sentence_not_mid_word():
    from marketmyna.services.report import _crisp

    text = "First sentence is here. " * 20
    out = _crisp(text, 60)
    assert out.endswith("here.") and len(out) <= 60


def test_public_dashboard_blanks_decision_target_and_stop(public):
    decision = SimpleNamespace(signal="buy", summary="x", details={"target_price": 400, "stop_loss": 300},
                               to_dict=lambda: {})
    ctx = SimpleNamespace(symbol="AAPL", market="us", mode="standard", opinions=[], generated_at=NOW,
                          get_opinion=lambda name: decision if name == "decision" else None)
    d = build_dashboard(ctx)
    assert d["compliance"] == "analytics"
    assert not {"decision_type", "target_price", "stop_loss"} & set(d)


def test_fund_dip_line_in_report(monkeypatch):
    fund = {"name": "Small Cap Fund", "nav": 150.0, "change_percent": -0.5,
            "lumpsum": {"status": "ok", "level": "strong", "met": 3, "total": 4, "below_high": -0.142}}
    body = build_report([_full_result()], ReportPrefs(sections=["portfolio"]), now=NOW, funds=[dict(fund)])[1]
    assert "Dip check 3/4 · 14.2% below high" in body and "opportunity" not in body.lower()
