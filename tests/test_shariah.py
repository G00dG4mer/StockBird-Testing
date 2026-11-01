"""Ethical screen: listing tags, the listings filter, and the full
per-stock profile (yfinance mocked)."""

import pandas as pd
import pytest

from marketmyna.data.categories import enrich
from marketmyna.data.listings import _row, query
from marketmyna.data.shariah import ETHICAL, EXCLUDED, INTEREST, MIXED, UNKNOWN, screen_row, stamp


def _status(*args, **fields):
    return screen_row(enrich([_row(*args, **fields)])[0])[0]


class TestListingRules:
    @pytest.mark.parametrize("symbol,name,sector", [
        ("HDFCBANK", "HDFC Bank Limited", "Financial Services"),
        ("BAJFINANCE", "Bajaj Finance Limited", "Financial Services"),
        ("LICI", "Life Insurance Corporation Of India", "Financial Services"),
    ])
    def test_india_interest_based(self, symbol, name, sector):
        assert _status(symbol, name, "india", "stock", sector=sector) == INTEREST

    @pytest.mark.parametrize("symbol,name,sector", [
        ("UBL", "United Breweries Limited", "Fast Moving Consumer Goods"),
        ("ITC", "ITC Limited", "Fast Moving Consumer Goods"),
    ])
    def test_india_excluded(self, symbol, name, sector):
        assert _status(symbol, name, "india", "stock", sector=sector) == EXCLUDED

    def test_india_permissible(self):
        assert _status("TCS", "Tata Consultancy Services Limited", "india", "stock", sector="Information Technology") == ETHICAL

    def test_hotels_are_mixed(self):
        assert _status("INDHOTEL", "The Indian Hotels Company Limited", "india", "stock", sector="Consumer Services") == MIXED

    def test_us_industries(self):
        assert _status("JPM", "JP Morgan Chase & Co.", "us", "stock", sector="Finance", industry="Major Banks") == INTEREST
        assert _status("PM", "Philip Morris International", "us", "stock", sector="Consumer Staples", industry="Tobacco") == EXCLUDED
        assert _status("LVS", "Las Vegas Sands Corp.", "us", "stock", sector="Consumer Discretionary",
                       industry="Hotels/Resorts") == EXCLUDED
        assert _status("O", "Realty Income", "us", "stock", sector="Real Estate",
                       industry="Real Estate Investment Trusts") == MIXED
        assert _status("AAPL", "Apple Inc.", "us", "stock", sector="Technology", industry="Computer Manufacturing") == ETHICAL

    def test_cannabis(self):
        assert _status("TLRY", "Tilray Brands Inc. Common Stock", "us", "stock", sector="Health Care",
                       industry="Medicinal Chemicals and Botanical Products") == EXCLUDED
        assert _status("XCAN", "Some Cannabis Corp", "us", "stock", sector="Health Care") == EXCLUDED

    def test_holding_word_only_matters_without_a_sector(self):
        assert _status("ASML", "ASML Holding N.V.", "us", "stock", sector="Technology",
                       industry="Industrial Machinery/Components") == ETHICAL
        assert _status("X1", "Futian Holdings", "hong_kong", "stock") == MIXED

    def test_chinese_names(self):
        assert _status("601398", "工商银行", "china_a", "stock") == INTEREST
        assert _status("600519", "贵州茅台", "china_a", "stock") == EXCLUDED

    def test_unclassified(self):
        assert _status("00700", "Tencent", "hong_kong", "stock") == UNKNOWN

    def test_screened_funds(self):
        assert _status("119172", "Tata Ethical Fund - Direct Plan - Growth Option", "india", "mf",
                       fund_group="Equity Scheme - Sectoral/ Thematic") == ETHICAL
        assert _status("154197", "UTI Nifty500 Shariah Index Fund - Direct Plan - Growth", "india", "mf") == ETHICAL
        assert _status("HLAL", "Wahed FTSE USA Shariah ETF", "us", "etf") == ETHICAL
        assert _status("SPUS", "SP Funds S&P 500 Sharia Industry Exclusions ETF", "us", "etf") == ETHICAL

    def test_ethical_outside_india_is_not_shariah(self):
        assert _status("ESGX", "Some Ethical Leaders ETF", "us", "etf") == MIXED

    def test_interest_and_conventional_funds(self):
        assert _status("1", "HDFC Liquid Fund - Direct Plan - Growth", "india", "mf",
                       fund_group="Debt Scheme - Liquid Fund") == INTEREST
        assert _status("NIFTYBEES", "Nifty 50 ETF", "india", "etf") == MIXED
        assert _status("GOLDBEES", "Nippon India ETF Gold BeES", "india", "etf") == MIXED

    def test_no_false_hits_inside_words(self):
        # "Grumman" contains "umma", "Osprey" contains "spre".
        assert _status("NOC", "Northrop Grumman Corporation", "us", "stock", sector="Industrials",
                       industry="Aerospace") == ETHICAL


class TestQueryFilter:
    def _rows(self):
        return stamp(enrich([
            _row("TCS", "Tata Consultancy Services Limited", "india", "stock", sector="Information Technology", market_cap=3.0),
            _row("HDFCBANK", "HDFC Bank Limited", "india", "stock", sector="Financial Services", market_cap=2.0),
            _row("INDHOTEL", "The Indian Hotels Company Limited", "india", "stock", sector="Consumer Services", market_cap=1.0),
        ]))

    def test_filter_and_facets(self):
        res = query(self._rows(), shariah=["ethical"])
        assert [r["symbol"] for r in res["rows"]] == ["TCS"]
        # The facet ignores its own filter so every chip keeps a count.
        assert res["facets"]["shariah"] == {"ethical": 1, "interest": 1, "mixed": 1}
        assert res["facets"]["types"] == {"stock": 1}

    def test_multiple_statuses(self):
        res = query(self._rows(), shariah=["ethical", "mixed"])
        assert {r["symbol"] for r in res["rows"]} == {"TCS", "INDHOTEL"}

    def test_old_links_still_work(self):
        assert [r["symbol"] for r in query(self._rows(), shariah=["halal"])["rows"]] == ["TCS"]
        assert [r["symbol"] for r in query(self._rows(), shariah=["haram"])["rows"]] == ["HDFCBANK"]


YEARS = [pd.Timestamp(f"{y}-03-31") for y in (2026, 2025)]


def _frame(rows: dict) -> pd.DataFrame:
    return pd.DataFrame(rows, index=YEARS).T


@pytest.fixture
def ticker(monkeypatch):
    import yfinance as yf

    from marketmyna.services import shariah

    shariah._cache.clear()
    state = {
        "info": {"longName": "Test Corp", "sector": "Technology", "industry": "Software - Application",
                 "marketCap": 1000.0, "currency": "INR", "financialCurrency": "INR"},
        "balance": _frame({
            "Total Assets": [800.0, 700.0],
            "Total Debt": [100.0, 120.0],
            "Cash Cash Equivalents And Short Term Investments": [150.0, 100.0],
            "Accounts Receivable": [100.0, 90.0],
        }),
        "income": _frame({"Total Revenue": [500.0, 450.0], "Interest Income Non Operating": [10.0, 8.0]}),
    }

    class Ticker:
        def __init__(self, symbol):
            self.info = state["info"]
            self.balance_sheet = state["balance"]
            self.income_stmt = state["income"]

        def history(self, period=None, interval=None):
            return pd.DataFrame({"Close": [100.0] * 36})

    monkeypatch.setattr(yf, "Ticker", Ticker)
    return state


class TestProfile:
    def test_numbers_without_a_verdict(self, ticker):
        from marketmyna.services.shariah import build_shariah_profile

        d = build_shariah_profile("TEST", "india")
        assert "verdict" not in d
        assert d["business"]["status"] == "ethical"
        by_key = {c["key"]: c for c in d["checks"]}
        assert by_key["debt"]["value"] == 10.0
        assert by_key["debt"]["reference"] == 33.0 and by_key["debt"]["strict_reference"] == 30.0
        assert by_key["cash"]["value"] == 15.0
        assert by_key["receivables"]["value"] == 25.0
        assert by_key["interest_income"]["value"] == 2.0
        assert all("status" not in c for c in d["checks"])

    def test_high_debt_is_just_a_number(self, ticker):
        from marketmyna.services.shariah import build_shariah_profile

        ticker["balance"].loc["Total Debt"] = [400.0, 400.0]
        d = build_shariah_profile("TEST", "india")
        assert {c["key"]: c["value"] for c in d["checks"]}["debt"] == 40.0
        assert d["business"]["status"] == "ethical"

    def test_bank_is_tagged_interest_based(self, ticker):
        from marketmyna.services.shariah import build_shariah_profile

        ticker["info"] = {**ticker["info"], "sector": "Financial Services", "industry": "Banks - Regional"}
        assert build_shariah_profile("TEST", "india")["business"]["status"] == "interest"

    def test_crypto_rejected(self, ticker):
        from marketmyna.services.shariah import build_shariah_profile

        with pytest.raises(ValueError):
            build_shariah_profile("BTC", "crypto")
