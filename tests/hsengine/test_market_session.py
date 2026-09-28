"""A financial turn plans a figure. It does not invent options or a cash bridge."""
from __future__ import annotations

from hsengine.engine.market_session import plan_figure
from hsengine.engine.webrtc_viz_apps import return_horizons


def test_versus_the_market_is_an_indexed_pair():
    plan = plan_figure("Let's look at XOM versus the market as a line graph.")
    assert plan is not None
    assert plan.kind == "relative"
    assert plan.tickers[0] == "XOM"
    assert "SPY" in plan.tickers


def test_candles_stay_on_one_name():
    plan = plan_figure("Show candlesticks for XOM.")
    assert plan is not None
    assert plan.kind == "candle"
    assert plan.tickers == ("XOM",)


def test_filings_are_not_a_price_chart():
    plan = plan_figure("Pull the recent Form 4 filings for SLB.")
    assert plan is not None
    assert plan.kind == "timeline"


def test_options_are_not_drawn():
    assert plan_figure("Price a covered call on XOM.") is None


def test_small_talk_does_not_draw():
    assert plan_figure("Good morning.") is None


def test_horizons_are_session_windows_not_calendar_ytd():
    closes = [100.0] * 22
    closes[-1] = 110.0
    points = [(str(i), price) for i, price in enumerate(closes)]
    horizons = return_horizons(points)
    assert "ytd" not in horizons
    assert horizons["d"] == 10.0
    assert horizons["span"] == 10.0
    assert horizons["m"] == 10.0
