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


def test_ripley_does_not_fetch_or_draw():
    from hsengine.engine.ops import spoken_tool_defs

    names = {tool["function"]["name"] for tool in spoken_tool_defs()}
    assert "fmp" not in names
    assert "viz_show" not in names
    assert "hermes" in names or "bishop_suggest" in names


def test_bishop_figure_move_tells_him_to_draw():
    from hsengine.engine.named_bots import bishop_prompt

    _, prompt, _ = bishop_prompt(
        move="figure",
        handoff='kind=relative tickers=XOM,SPY',
    )
    assert "viz_show" in prompt
    assert "MONOLOGUE empty" in prompt


def test_a_valuation_ask_is_workflow_not_a_live_chart():
    from hsengine.engine.market_session import needs_workflow

    assert needs_workflow("Run a reverse DCF on XOM.")
    assert plan_figure("Run a reverse DCF on XOM.") is None


def test_horizons_are_session_windows_not_calendar_ytd():
    closes = [100.0] * 22
    closes[-1] = 110.0
    points = [(str(i), price) for i, price in enumerate(closes)]
    horizons = return_horizons(points)
    assert "ytd" not in horizons
    assert horizons["d"] == 10.0
    assert horizons["span"] == 10.0
    assert horizons["m"] == 10.0
