"""Ethical screening for listings: what a business does, stated as fact.

Owner's rule: MarketMyna never says a business is halal / haram /
compliant. "Ethical business" only means the core business is not in an
excluded activity (alcohol, tobacco, gambling, pork, adult content,
weapons, cannabis). Interest is shown as data - an interest-based
business gets the factual "interest" tag, and the debt / cash /
interest-income numbers sit on the stock page - and the investor decides.

Two layers:

1. ``screen_row`` - a fast, per-listing tag run on every row when the
   listing cache loads, from sector / industry / name (funds: mandate).
   This is what the Markets "Ethical" filter uses.
2. ``marketmyna/services/shariah.py`` - the full per-stock profile (business
   tag + balance-sheet numbers), computed on demand.

Tags:
    ethical   - core business is not in an excluded activity and is not
                interest-based (funds: an ethically screened mandate)
    interest  - interest-based business: banks, lenders, insurers,
                brokers; funds holding interest-bearing debt or leverage
    mixed     - mixed or unclear activity (hotels, media, REITs,
                conventional all-sector funds, ...)
    excluded  - alcohol, tobacco, gambling, pork, adult content, weapons,
                cannabis
    unknown   - not enough information
"""

from __future__ import annotations

import re
from typing import Optional

ETHICAL = "ethical"
INTEREST = "interest"
MIXED = "mixed"
EXCLUDED = "excluded"
UNKNOWN = "unknown"

STATUSES = (ETHICAL, INTEREST, MIXED, EXCLUDED, UNKNOWN)

# Old filter values in saved links / screens (?sh=halal) map onto the new tags.
LEGACY = {"halal": (ETHICAL,), "doubtful": (MIXED,), "haram": (INTEREST, EXCLUDED)}


def normalize(values) -> set[str]:
    out: set[str] = set()
    for v in values:
        out.update(LEGACY.get(v, (v,)))
    return out

# ---------------------------------------------------------------- funds

# Known Shariah-screened funds/ETFs whose names don't say so.
SHARIAH_TICKERS = {
    # SP Funds (all Shariah-screened by S&P / Dow Jones)
    "SPUS", "SPSK", "SPRE", "SPTE", "SPWO",
    # Wahed, Manzil
    "HLAL", "UMMA", "MNZL", "KWIN",
    # Amana, Iman, Azzad (US mutual funds)
    "AMAGX", "AMANX", "AMAPX", "AMIGX", "AMINX", "AMIDX", "IMANX", "ADJEX", "WISEX",
    # India
    "SHARIABEES",
}

_SHARIAH_NAME = re.compile(
    r"shari'?a[h]?|islamic|\bhalal\b|\bsukuk\b|\bamana\b|\bwahed\b|\bmanzil\b|\biman fund\b|\bazzad\b|"
    r"\bsp funds\b|\bfalah\b",
    re.I,
)
# In India every "Ethical" fund (Tata, Taurus, Quantum, The Wealth Company)
# benchmarks a Shariah index and follows Shariah screening. Elsewhere
# "ethical" usually means ESG, which still allows banks and interest.
_INDIA_ETHICAL = re.compile(r"\bethical\b", re.I)

_INTEREST_FUND = re.compile(
    r"\b(liquid|money market|overnight|gilt|g-?sec|treasury|t-?bill|bonds?|debt|income|credit|"
    r"corporate bond|banking (and|&) psu|floater|floating rate|duration|fixed (maturity|income)|"
    r"fmp|arbitrage|sdl|bharat bond|aggregate|municipal|muni|high yield|mortgage)\b",
    re.I,
)


_SUKUK = re.compile(r"\bsukuk\b", re.I)
_HYBRID = re.compile(r"\bhybrid|balanced|asset allocat|multi asset|equity savings\b", re.I)
_METAL = re.compile(r"\b(gold|silver)\b", re.I)
_METAL_EQUITY = re.compile(r"miners?|mining|futures|equity|stocks", re.I)
_REIT = re.compile(r"\breit\b", re.I)
_FUND_NAME = re.compile(r"\b(etf|bees)\b", re.I)


def _zh_hit(words: tuple[str, ...], text: str) -> Optional[str]:
    return next((w for w in words if w in text), None)


def _fund(row: dict) -> tuple[str, str]:
    name = row.get("name") or ""
    symbol = (row.get("symbol") or "").upper()
    if symbol in SHARIAH_TICKERS or _SHARIAH_NAME.search(name):
        if _SUKUK.search(name) or symbol in ("SPSK", "KWIN"):
            return ETHICAL, "Ethical bond fund - asset-backed, no interest"
        return ETHICAL, "Ethically screened fund - its mandate leaves out interest-based finance and excluded activities"
    if row.get("market") == "india" and _INDIA_ETHICAL.search(name):
        return ETHICAL, "Indian 'Ethical' fund - follows an ethically screened index"

    category = row.get("category") or ""
    text = f"{name} {row.get('fund_group') or ''} {row.get('sector') or ''}"
    if category in ("Debt", "Bonds") or _INTEREST_FUND.search(text):
        return INTEREST, "Holds interest-bearing debt"
    if category == "Leveraged & Inverse":
        return INTEREST, "Uses borrowed money and derivatives"
    if category == "Hybrid" or _HYBRID.search(text):
        return INTEREST, "Hybrid fund - part of the money sits in interest-bearing debt"
    if _METAL.search(text) and not _METAL_EQUITY.search(text):
        return MIXED, "Precious-metal fund - check whether it holds physical metal"
    if category == "Commodities":
        return MIXED, "Commodity futures - the collateral earns interest"
    return MIXED, "No screening mandate - holds all sectors, including banks and insurers"


# --------------------------------------------------------------- stocks

# Interest-based core business. Checked against the company name and industry.
_INTEREST_WORDS = re.compile(
    r"\b(banks?|banking|bancorp\w*|bancshares|bankshares|banc|financ(e|ial|iers?|ing)|fincorp|finserv|fincap|"
    r"finvest|credit|lending|loans?|insurance|insurers?|assurance|reinsurance|nbfc|micro ?finance|"
    r"mortgage|securities|broking|stock ?brokers?)\b",
    re.I,
)
# Excluded core business.
_EXCLUDED_WORDS = re.compile(
    r"\b(brew(ery|eries|ers|ing)|distiller(y|ies|s)?|wines?|winery|wineries|spirits|liquors?|beers?|"
    r"whisk(e)?y|vodka|alcohol\w*|"
    r"tobacco|cigarettes?|cigars?|vap(e|ing)|cannabis|marijuana|"
    r"casinos?|gambling|betting|lotter(y|ies)|wagering|bookmakers?|sportsbook|"
    r"pork|swine|hogs?|"
    r"adult entertainment|pornograph\w*|"
    r"firearms?|ammunition|munitions?|ordnance|guns?)\b",
    re.I,
)
# Gambling, alcohol and tobacco companies whose names don't say so.
_EXCLUDED_BRANDS = re.compile(
    r"\b(las vegas sands|sands china|wynn|melco|sjm holdings|galaxy ent\w*|mgm (resorts|china)|caesars|"
    r"draftkings|flutter|churchill downs|penn entertainment|boyd gaming|red rock resorts|monarch casino|"
    r"delta corp|"
    r"itc limited|godfrey phillips|vst industries|altria|philip morris|british american tobacco|turning point brands|"
    r"radico khaitan|tilaknagar|sula vineyards|constellation brands|molson coors|boston beer|brown-forman|"
    r"diageo|anheuser|heineken|pernod|carlsberg|ambev|tsingtao|budweiser)\b",
    re.I,
)
# Banks and insurers whose names don't say so.
_INTEREST_BRANDS = re.compile(
    r"\b(hsbc|stanchart|standard chartered|boc hong kong|ping an|china life|prudential|berkshire hathaway|"
    r"allianz|manulife|sun life)\b",
    re.I,
)
# Cannabis companies listed under Health Care / Pharma whose names don't say so.
_CANNABIS_BRANDS = re.compile(
    r"\b(tilray|canopy growth|cronos group|sndl|sundial growers|curaleaf|trulieve|green thumb industries|"
    r"organigram|high tide|cresco labs|aurora cannabis)\b",
    re.I,
)
_ISLAMIC_FINANCE = re.compile(r"islamic|shari'?a|takaful|sukuk", re.I)
# Chinese names (China A / Hong Kong): banks, brokers, insurers, trusts,
# futures, finance, alcohol, tobacco, lottery / gaming.
_INTEREST_ZH = ("银行", "证券", "保险", "信托", "期货", "金融", "租赁", "人寿", "中国平安")
_EXCLUDED_ZH = ("酒业", "酒厂", "啤酒", "白酒", "葡萄酒", "烟草", "彩票", "博彩", "茅台", "五粮液", "老窖", "汾酒", "洋河", "古井贡", "酒鬼")
_DOUBTFUL_ZH = ("酒店", "影视", "传媒", "娱乐", "游戏", "军工", "兵装")

# Mixed or unclear activity.
_DOUBTFUL_WORDS = re.compile(
    r"\b(hotels?|resorts?|hospitality|restaurants?|bars?|pubs?|night ?clubs?|cinemas?|multiplex|films?|"
    r"studios?|movies?|music|entertainment|broadcast\w*|media|television|advertising|"
    r"defen[cs]e|military|weapons?|explosives?|aerospace (and|&) defen[cs]e|"
    r"leasing|reit|meat|poultry|beverages?)\b",
    re.I,
)
# Name words that often mean a finance / holding company, but only matter
# when nothing else classifies the business ("XYZ Holdings", "ABC Capital").
_VAGUE_FINANCE_WORDS = re.compile(r"\b(capital|holdings?|invest\w*|trusts?|ventures)\b", re.I)

# Exact US (NASDAQ screener) industries.
_US_INTEREST_INDUSTRY = {
    "major banks", "commercial banks", "savings institutions", "banks", "finance: consumer services",
    "finance companies", "investment bankers/brokers/service", "investment managers",
    "finance/investors services", "property-casualty insurers", "life insurance", "specialty insurers",
    "accident &health insurance", "diversified financial services", "blank checks",
}
_US_EXCLUDED_INDUSTRY = {"tobacco", "ordnance and accessories"}
_US_DOUBTFUL_INDUSTRY = {
    "services-misc. amusement & recreation", "hotels/resorts", "restaurants", "movies/entertainment",
    "broadcasting", "cable & other pay television services", "advertising", "military/government/technical",
    "real estate investment trusts", "trusts except educational religious and charitable",
    "meat/poultry/fish", "rental/leasing companies", "misc corporate leasing services",
    "beverages (production/distribution)", "managed health care", "real estate",
}
_INDIA_SECTOR = {
    "financial services": (INTEREST, "Financial services - interest-based business"),
    "media entertainment & publication": (MIXED, "Media & entertainment - content may include prohibited material"),
}


def _stock(row: dict) -> tuple[str, str]:
    name = row.get("name") or ""
    local = row.get("name_local") or ""
    sector = (row.get("sector") or "").strip()
    industry = (row.get("industry") or "").strip()
    text = f"{name} {industry}"

    if _ISLAMIC_FINANCE.search(name):
        return MIXED, "Ethical-finance company - check its ethics board certification"
    if _EXCLUDED_BRANDS.search(name):
        return EXCLUDED, "Excluded activity (gambling, alcohol or tobacco)"
    if _CANNABIS_BRANDS.search(name):
        return EXCLUDED, "Excluded activity (cannabis)"
    hit = _EXCLUDED_WORDS.search(text)
    if hit:
        return EXCLUDED, f"Excluded activity ({hit.group(0).lower()})"
    if _INTEREST_BRANDS.search(name):
        return INTEREST, "Interest-based business (banking or insurance)"
    hit = _INTEREST_WORDS.search(text)
    if hit:
        return INTEREST, f"Interest-based business ({hit.group(0).lower()})"
    if sector == "REIT" or _REIT.search(name):
        return MIXED, "REIT - depends on its tenants and its borrowing"
    if sector == "InvIT":
        return MIXED, "InvIT - roads and power assets, usually with interest-bearing debt"
    # Chinese words only matter when a name or sector has Chinese text.
    cjk = "" if (name + local + sector).isascii() else f"{local}|{name}|{sector}"
    zh = cjk and _zh_hit(_EXCLUDED_ZH, cjk)
    if zh:
        return EXCLUDED, f"Excluded activity ({zh})"
    zh = cjk and _zh_hit(_INTEREST_ZH, cjk)
    if zh:
        return INTEREST, f"Interest-based business ({zh})"

    ind = industry.lower()
    if ind in _US_EXCLUDED_INDUSTRY:
        return EXCLUDED, f"Excluded activity ({industry})"
    if ind in _US_INTEREST_INDUSTRY:
        return INTEREST, f"Interest-based business ({industry})"
    if sector.lower() == "finance" and ind not in _US_DOUBTFUL_INDUSTRY:
        return INTEREST, "Financial services - interest-based business"
    if ind in _US_DOUBTFUL_INDUSTRY:
        return MIXED, f"Mixed activity ({industry}) - check revenue sources"
    mapped = _INDIA_SECTOR.get(sector.lower())
    if mapped:
        return mapped

    doubt = _DOUBTFUL_WORDS.search(text)
    if doubt:
        return MIXED, f"Mixed or unclear activity ({doubt.group(0).lower()}) - check revenue sources"
    zh = cjk and _zh_hit(_DOUBTFUL_ZH, cjk)
    if zh:
        return MIXED, f"Mixed or unclear activity ({zh}) - check revenue sources"

    category = row.get("category")
    unclassified = not sector and not industry
    vague = _VAGUE_FINANCE_WORDS.search(name)
    if unclassified and vague:
        return MIXED, f"Name suggests a finance or holding company ({vague.group(0).lower()}) - check"
    if category == "Financials":
        return MIXED, "Looks like a financial company - check"
    if not category or category == "Other":
        return UNKNOWN, "Business not classified - open the stock for details"
    how = "guessed from the company name" if row.get("category_inferred") else "sector"
    return ETHICAL, f"No excluded or interest-based activity ({category}, {how}) - debt and interest numbers on the stock page"


def screen_row(row: dict) -> tuple[str, str]:
    """(status, reason) for one listing row."""
    type_ = row.get("type")
    # Some exchanges list ETFs alongside stocks.
    if type_ in ("mf", "etf") or _FUND_NAME.search(row.get("name") or ""):
        return _fund(row)
    if type_ == "crypto":
        return UNKNOWN, "Crypto - not covered by the ethical screen"
    return _stock(row)


def stamp(rows: list[dict]) -> list[dict]:
    """Stamp ``shariah`` + ``shariah_reason`` on every row in place."""
    for row in rows:
        row["shariah"], row["shariah_reason"] = screen_row(row)
    return rows


def business_status(name: str, sector: Optional[str], industry: Optional[str], summary: str = "") -> tuple[str, str, list[str]]:
    """Business tag for the full profile, from the market-data sector/industry.

    Returns (status, reason, flags) where flags are excluded activities
    mentioned in the business description."""
    ind = (industry or "").lower()
    excluded = ("brewers", "wineries", "distilleries", "tobacco", "gambling", "resorts & casinos")
    interest = ("banks", "credit services", "capital markets", "mortgage finance", "insurance", "asset management",
                "financial conglomerates")
    mixed = (
        "shell companies", "aerospace & defense", "entertainment", "lodging", "restaurants", "broadcasting", "advertising",
        "reit", "leisure", "financial data & stock exchanges", "beverages", "farm products", "packaged foods",
    )

    flags = sorted({m.group(0).lower() for m in _SUMMARY_FLAGS.finditer(summary or "")})

    if _ISLAMIC_FINANCE.search(name):
        return MIXED, "Ethical-finance company - check its ethics board certification", flags
    if _EXCLUDED_BRANDS.search(name):
        return EXCLUDED, "Excluded activity (gambling, alcohol or tobacco)", flags
    if _INTEREST_BRANDS.search(name):
        return INTEREST, "Interest-based business (banking or insurance)", flags
    hit = next((k for k in excluded if k in ind), None)
    if hit:
        return EXCLUDED, f"Excluded activity ({industry})", flags
    hit = next((k for k in interest if k in ind), None)
    if hit:
        return INTEREST, f"Interest-based business ({industry})", flags
    if (sector or "").lower() == "financial services":
        return INTEREST, f"Financial services - interest-based business ({industry or sector})", flags
    doubt = next((k for k in mixed if k in ind), None)
    if doubt and not ("non-alcoholic" in ind and doubt == "beverages"):
        # Packaged food / farm products only matter if pork or alcohol shows up.
        if doubt in ("farm products", "packaged foods", "beverages") and not flags:
            pass
        else:
            return MIXED, f"Mixed activity ({industry}) - check revenue sources", flags
    if not industry and not sector:
        status, reason = _stock({"name": name, "type": "stock"})
        return status, reason, flags
    if flags:
        return MIXED, "Business description mentions: " + ", ".join(flags), flags
    return ETHICAL, f"No excluded or interest-based activity ({industry or sector})", flags


# Excluded activities worth flagging when they appear in the business
# description (e.g. a hotel chain that sells alcohol, a food group with pork).
_SUMMARY_FLAGS = re.compile(
    r"\b(casinos?|gambling|betting|lotter(y|ies)|wagering|alcoholic|beer|wines?|spirits|liquor|brewing|"
    r"distill\w*|pork|tobacco|cigarettes?|adult entertainment|pornograph\w*|firearms|ammunition|"
    r"weapons|conventional (banking|insurance))\b",
    re.I,
)
