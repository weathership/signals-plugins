"""Turn a financial utterance into a figure the live call can actually draw.

Bishop directs and Vasquez draws, but neither reliably assembles a payload.
This plans the pattern from the words and the tickers, then viz_show fetches
the bars. Options are not drawn. A cash bridge, ROIC path, consensus history,
or reverse DCF is not invented from a ticker.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("hsengine.engine.market_session")

_TICKER = re.compile(r"\b[A-Z]{1,5}\b")
_STOP = frozenset(
    {
        "A", "I", "AND", "THE", "FOR", "VS", "USD", "ETF", "CEO", "CFO",
        "FMP", "YTD", "OHLC", "RSI", "MACD", "VWAP", "DCF", "ROIC", "WACC",
        "FCF", "EPS", "SEC", "IPO", "GDP", "CPI", "FED", "ATH", "ATL",
        "OK", "PM", "AM", "US", "UK", "EU", "AI", "IT", "OR", "TO", "OF",
    }
)
_PRICE = re.compile(
    r"\b(price|prices|chart|plot|graph|candles?|candlesticks?|volume|return|returns|"
    r"versus|vs\.?|against|relative|market|move|moved|session|sessions)\b",
    re.I,
)
_VERSUS = re.compile(r"\b(versus|vs\.?|against|relative to|compared with)\b", re.I)
_MARKET = re.compile(r"\b(the market|s\s*&\s*p|s&p|spy|benchmark)\b", re.I)
_FILING = re.compile(r"\b(filing|filings|8-k|form\s*4|10-k|13f)\b", re.I)
_OPTIONS = re.compile(
    r"\b(option|options|covered call|implied vol|open interest|strike|expiry)\b",
    re.I,
)
_NAMES = (
    ("exxon", "XOM"),
    ("chevron", "CVX"),
    ("schlumberger", "SLB"),
    ("halliburton", "HAL"),
    ("apple", "AAPL"),
    ("microsoft", "MSFT"),
    ("nvidia", "NVDA"),
)


@dataclass(frozen=True)
class FigurePlan:
    kind: str
    tickers: tuple[str, ...]
    title: str


def tickers_in(*texts: str) -> list[str]:
    found: list[str] = []
    blob = " ".join(texts)
    low = blob.lower()
    for name, symbol in _NAMES:
        if name in low and symbol not in found:
            found.append(symbol)
    for match in _TICKER.findall(blob):
        if match in _STOP or match in found:
            continue
        found.append(match)
    if _MARKET.search(blob) and "SPY" not in found and found:
        found.append("SPY")
    return found[:6]


def plan_figure(user: str, assistant: str = "") -> FigurePlan | None:
    """Which figure this turn can support. None when we would be inventing it."""
    text = f"{user or ''} {assistant or ''}".strip()
    if not text or _OPTIONS.search(text):
        return None
    names = tickers_in(text)
    if _FILING.search(text) and not _PRICE.search(text):
        if not names:
            return None
        return FigurePlan("timeline", tuple(names), _title(names, "Filings"))
    if not names or not _PRICE.search(text):
        return None
    if re.search(r"\bcandlesticks?\b", text, re.I):
        kind = "candle"
    elif re.search(r"\bvolume\b", text, re.I):
        kind = "volume"
    elif re.search(r"\b(range|high-low|band)\b", text, re.I):
        kind = "range"
    elif re.search(r"\b(what moved|return board|across)\b", text, re.I) and len(names) >= 2:
        kind = "return_board"
    elif re.search(r"\bheatmap\b", text, re.I) and len(names) >= 2:
        kind = "heatmap"
    elif re.search(r"\breturns?\b", text, re.I):
        kind = "returns"
    elif _VERSUS.search(text) or _MARKET.search(text):
        kind = "relative"
    else:
        kind = "price_structure"
    if kind in ("relative", "heatmap", "return_board") and len(names) < 2 and "SPY" not in names:
        names = [*names, "SPY"]
    label = {
        "relative": "indexed to 100",
        "candle": "OHLC",
        "volume": "close and volume",
        "range": "high-low",
        "returns": "daily returns",
        "heatmap": "return heatmap",
        "return_board": "return board",
        "price_structure": "price",
    }[kind]
    return FigurePlan(kind, tuple(names[:6]), _title(names, label))


def _title(names: list[str], label: str) -> str:
    return f"{' / '.join(names[:4])} — {label}"


def surface_for_turn(user: str, assistant: str = "") -> bool:
    """Draw the planned figure. False when there is nothing honest to draw."""
    plan = plan_figure(user, assistant)
    if plan is None:
        return False
    try:
        from hsengine.engine.webrtc_program import PROGRAM

        status = PROGRAM.status()
        if status.get("live") and str(status.get("kind") or "") == plan.kind:
            return False
    except Exception:
        log.debug("viz status unread", exc_info=True)
    try:
        from hsengine.engine.webrtc_program import show

        result = show(
            kind=plan.kind,
            title=plan.title,
            highlight=plan.tickers[0] if plan.tickers else "",
            source="",
            data=json.dumps({"tickers": list(plan.tickers)}),
            fade_s=0.4,
        )
    except Exception:
        log.warning("market figure failed", exc_info=True)
        return False
    ok = bool(result.get("ok"))
    if ok:
        log.info("market figure %s %s", plan.kind, ",".join(plan.tickers))
    else:
        log.info("market figure not shown: %s", result.get("error") or result)
    return ok
