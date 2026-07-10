"""
tests/test_ghetto_sd.py — unit tests for the pure Ghetto Standard Deviation engine.

The engine has zero I/O; every rule from the strategy brief is pinned here, with
the DRI example serving as the end-to-end golden fixture.
"""

from __future__ import annotations

from datetime import date

import pytest

from tradingagents.analytics.ghetto_sd import (
    AnalysisInput,
    ContractQuote,
    ExpirationClass,
    GhettoSDConfig,
    ScanCriteria,
    analyze,
    atm_from_chain,
    build_screener,
    candidate_contracts,
    classify_expiration,
    compute_sd,
    evaluate_candidate,
    pick_best_strangle,
    select_atm_strike,
    select_ideal_expiration,
    select_nearest_expiration,
    score_suitability,
)

CFG = GhettoSDConfig.default()


# ─── compute_sd ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_compute_sd_dri_golden():
    sd = compute_sd(current_price=218.10, atm_call_ask=8.90, atm_put_ask=9.50, atm_strike=220.0)
    assert sd.one_sd == pytest.approx(18.40)
    assert sd.two_sd == pytest.approx(36.80)
    assert sd.upside_target == pytest.approx(254.90)
    assert sd.downside_target == pytest.approx(181.30)
    assert sd.one_sd_pct == pytest.approx(18.40 / 218.10 * 100)
    assert sd.two_sd_pct == pytest.approx(36.80 / 218.10 * 100)


@pytest.mark.unit
@pytest.mark.parametrize("price", [0, -5])
def test_compute_sd_rejects_nonpositive_price(price):
    with pytest.raises(ValueError):
        compute_sd(current_price=price, atm_call_ask=1.0, atm_put_ask=1.0, atm_strike=10.0)


@pytest.mark.unit
@pytest.mark.parametrize("call,put", [(0, 1.0), (1.0, 0), (-1.0, 1.0)])
def test_compute_sd_rejects_missing_quotes(call, put):
    with pytest.raises(ValueError):
        compute_sd(current_price=100.0, atm_call_ask=call, atm_put_ask=put, atm_strike=100.0)


# ─── select_atm_strike ──────────────────────────────────────────────────


@pytest.mark.unit
def test_select_atm_strike_nearest_above():
    assert select_atm_strike(218.10, [210, 215, 220, 225]) == 220


@pytest.mark.unit
def test_select_atm_strike_exact_match():
    assert select_atm_strike(220.0, [210, 215, 220, 225]) == 220


@pytest.mark.unit
def test_select_atm_strike_none_above_falls_back_to_highest():
    assert select_atm_strike(300.0, [210, 215, 220]) == 220


@pytest.mark.unit
def test_select_atm_strike_empty_raises():
    with pytest.raises(ValueError):
        select_atm_strike(100.0, [])


# ─── classify_expiration ────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_expiration_zero_day_invalid():
    today = date(2026, 6, 18)
    info = classify_expiration(date(2026, 6, 18), earnings_date=date(2026, 6, 25), today=today)
    assert info.classification is ExpirationClass.INVALID
    assert info.days_to_expiry == 0


@pytest.mark.unit
def test_classify_expiration_week_of_is_ideal():
    today = date(2026, 6, 18)
    info = classify_expiration(date(2026, 6, 27), earnings_date=date(2026, 6, 25), today=today)
    assert info.classification is ExpirationClass.IDEAL
    assert info.days_after_earnings == 2


@pytest.mark.unit
def test_classify_expiration_far_is_usable_not_ideal():
    # DRI: Jul 17 is 29 days out, 22 days after June 25 earnings → usable, not ideal.
    today = date(2026, 6, 18)
    info = classify_expiration(date(2026, 7, 17), earnings_date=date(2026, 6, 25), today=today)
    assert info.classification is ExpirationClass.USABLE_NOT_IDEAL
    assert info.days_to_expiry == 29
    assert info.days_after_earnings == 22


@pytest.mark.unit
def test_classify_expiration_before_earnings_not_ideal():
    today = date(2026, 6, 18)
    info = classify_expiration(date(2026, 6, 20), earnings_date=date(2026, 6, 25), today=today)
    assert info.classification is ExpirationClass.USABLE_NOT_IDEAL
    assert info.days_after_earnings == -5


@pytest.mark.unit
def test_select_ideal_expiration_picks_closest_after_earnings():
    today = date(2026, 6, 18)
    expiries = [date(2026, 6, 18), date(2026, 6, 20), date(2026, 6, 27), date(2026, 7, 17)]
    chosen = select_ideal_expiration(expiries, earnings_date=date(2026, 6, 25), today=today)
    assert chosen == date(2026, 6, 27)


@pytest.mark.unit
def test_select_ideal_expiration_none_when_no_week_of():
    today = date(2026, 6, 18)
    expiries = [date(2026, 6, 18), date(2026, 7, 17)]
    chosen = select_ideal_expiration(expiries, earnings_date=date(2026, 6, 25), today=today)
    assert chosen is None


# ─── build_screener (verdicts + ratings + liquidity) ────────────────────


@pytest.mark.unit
def test_screener_verdicts_cost_bands():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)  # upside ~254.90, downside ~181.30
    quotes = [
        ContractQuote(strike=260, side="call", bid=0.70, ask=0.80),   # $80  → Valid
        ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),   # $200 → Too Expensive
        ContractQuote(strike=255, side="call", bid=1.10, ask=1.20),   # $120 → Borderline
        ContractQuote(strike=300, side="call", bid=0.05, ask=0.10),   # $10  → Too Far OTM
    ]
    rows = {r.strike: r for r in build_screener(quotes, sd, CFG)}
    assert rows[260].verdict == "Valid Play"
    assert rows[250].verdict == "Too Expensive"
    assert rows[255].verdict == "Borderline"
    assert rows[300].verdict == "Too Far OTM"
    assert rows[260].cost_per_contract == pytest.approx(80.0)


@pytest.mark.unit
def test_screener_band_boundaries_inclusive():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)
    quotes = [
        ContractQuote(strike=255, side="call", bid=0.18, ask=0.20),   # exactly $20  → Valid
        ContractQuote(strike=255, side="call", bid=0.95, ask=1.00),   # exactly $100 → Valid
        ContractQuote(strike=255, side="call", bid=1.45, ask=1.50),   # exactly $150 → Borderline
    ]
    verdicts = [r.verdict for r in build_screener(quotes, sd, CFG)]
    assert verdicts == ["Valid Play", "Valid Play", "Borderline"]


@pytest.mark.unit
def test_screener_2sd_rating_zone():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)  # upside target 254.90
    quotes = [
        ContractQuote(strike=255, side="call", bid=1.0, ask=1.10),    # ~0% from target → in zone
        ContractQuote(strike=275, side="call", bid=0.4, ask=0.50),    # ~8% away → near
        ContractQuote(strike=320, side="call", bid=0.1, ask=0.15),    # far
    ]
    rows = build_screener(quotes, sd, CFG)
    assert rows[0].in_two_sd_zone is True
    assert rows[1].in_two_sd_zone is False


@pytest.mark.unit
def test_screener_negative_downside_target_not_in_zone():
    # Cheap stock: price 8, 1SD 5 → 2SD 10 → downside target = -2 (below zero).
    sd = compute_sd(8.0, 3.0, 2.0, 8.0)
    assert sd.downside_target == pytest.approx(-2.0)
    quotes = [ContractQuote(strike=5, side="put", bid=0.4, ask=0.50)]
    rows = build_screener(quotes, sd, CFG)
    assert rows[0].in_two_sd_zone is False


@pytest.mark.unit
def test_screener_puts_use_downside_target():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)  # downside target 181.30
    quotes = [ContractQuote(strike=181, side="put", bid=1.0, ask=1.10)]
    rows = build_screener(quotes, sd, CFG)
    assert rows[0].in_two_sd_zone is True


@pytest.mark.unit
def test_screener_liquidity_flag_on_wide_spread():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)
    quotes = [
        ContractQuote(strike=255, side="call", bid=0.50, ask=1.00),   # 50% spread → flagged
        ContractQuote(strike=256, side="call", bid=0.95, ask=1.00),   # 5% spread → clean
    ]
    rows = build_screener(quotes, sd, CFG)
    assert rows[0].liquidity_warning is True
    assert rows[1].liquidity_warning is False


# ─── score_suitability ──────────────────────────────────────────────────


@pytest.mark.unit
def test_score_high_priced_clean_setup():
    score = score_suitability(
        current_price=218.10,
        earnings_this_week=True,
        two_sd_min_cost=80.0,
        large_historical_moves=True,
        same_day_expiry=False,
        cfg=CFG,
    )
    # base 5 +3(>150) +3(<100 cost) +2(earnings) +2(history) = 15 → clamp 10
    assert score.score == 10


@pytest.mark.unit
def test_score_cheap_stock_expensive_options_clamped():
    score = score_suitability(
        current_price=35.0,
        earnings_this_week=False,
        two_sd_min_cost=200.0,
        large_historical_moves=False,
        same_day_expiry=True,
        cfg=CFG,
    )
    # base 5 -3(<50) -2(>150 cost) -2(same day) = -2 → clamp 1
    assert score.score == 1


@pytest.mark.unit
def test_score_history_unknown_is_neutral():
    # cost 120 (no +3/-2), earnings off → base 5 +3(>150) = 8, +2 only if history known.
    s_known = score_suitability(150.01, False, 120.0, True, False, cfg=CFG)
    s_unknown = score_suitability(150.01, False, 120.0, None, False, cfg=CFG)
    assert s_known.score == 10
    assert s_unknown.score == 8


# ─── analyze (orchestrator + warnings) ──────────────────────────────────


def _dri_input(**overrides) -> AnalysisInput:
    base = dict(
        ticker="DRI",
        current_price=218.10,
        earnings_date=date(2026, 6, 25),
        today=date(2026, 6, 18),
        expiry_date=date(2026, 7, 17),
        has_e_badge=False,
        atm_strike=220.0,
        atm_call_ask=8.90,
        atm_put_ask=9.50,
        contracts=(
            ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),
            ContractQuote(strike=260, side="call", bid=0.70, ask=0.80),
            ContractQuote(strike=185, side="put", bid=1.40, ask=1.50),
        ),
        large_historical_moves=None,
    )
    base.update(overrides)
    return AnalysisInput(**base)


@pytest.mark.unit
def test_analyze_dri_end_to_end():
    result = analyze(_dri_input(), cfg=CFG)
    assert result.sd.two_sd == pytest.approx(36.80)
    assert result.expiration.classification is ExpirationClass.USABLE_NOT_IDEAL
    assert len(result.screener) == 3
    messages = [w.message for w in result.warnings]
    # Jul 17 is not the week-of expiry, and no E badge present.
    assert any("expiration" in m.lower() for m in messages)
    assert any("earnings" in m.lower() and "week" in m.lower() for m in messages)


@pytest.mark.unit
def test_analyze_low_price_warning_is_critical():
    result = analyze(_dri_input(current_price=42.0), cfg=CFG)
    crit = [w for w in result.warnings if w.level == "critical"]
    assert crit, "stock under $50 must raise a critical warning"
    assert any("overpay" in w.message.lower() for w in crit)


@pytest.mark.unit
def test_analyze_zero_day_expiry_blocks_sd():
    result = analyze(_dri_input(expiry_date=date(2026, 6, 18), earnings_date=date(2026, 6, 18)), cfg=CFG)
    assert result.sd is None
    assert result.expiration.classification is ExpirationClass.INVALID
    assert any(w.level == "critical" for w in result.warnings)


@pytest.mark.unit
def test_analyze_iv_crush_warning_day_after_earnings():
    result = analyze(
        _dri_input(expiry_date=date(2026, 6, 26), earnings_date=date(2026, 6, 25), has_e_badge=True),
        cfg=CFG,
    )
    assert any("iv crush" in w.message.lower() for w in result.warnings)


# ─── select_nearest_expiration (earnings-free) ──────────────────────────


@pytest.mark.unit
def test_select_nearest_expiration_skips_zero_dte():
    today = date(2026, 6, 18)
    expiries = [date(2026, 6, 18), date(2026, 6, 20), date(2026, 6, 27)]
    assert select_nearest_expiration(expiries, today) == date(2026, 6, 20)


@pytest.mark.unit
def test_select_nearest_expiration_respects_min_dte():
    today = date(2026, 6, 18)
    expiries = [date(2026, 6, 20), date(2026, 6, 25), date(2026, 7, 2)]
    assert select_nearest_expiration(expiries, today, min_dte=5) == date(2026, 6, 25)


@pytest.mark.unit
def test_select_nearest_expiration_none_when_all_too_soon():
    today = date(2026, 6, 18)
    assert select_nearest_expiration([date(2026, 6, 18)], today) is None
    assert select_nearest_expiration([], today) is None


# ─── atm_from_chain ─────────────────────────────────────────────────────


def _chain():
    return [
        {"strike": 215, "side": "call", "bid": 5.0, "ask": 5.2},
        {"strike": 220, "side": "call", "bid": 8.8, "ask": 8.9},
        {"strike": 220, "side": "put", "bid": 9.4, "ask": 9.5},
        {"strike": 225, "side": "put", "bid": 11.0, "ask": 11.2},
    ]


@pytest.mark.unit
def test_atm_from_chain_nearest_above():
    atm, call_ask, put_ask = atm_from_chain(_chain(), 218.10)
    assert atm == 220
    assert call_ask == pytest.approx(8.9)
    assert put_ask == pytest.approx(9.5)


@pytest.mark.unit
def test_atm_from_chain_empty_returns_none_asks():
    atm, call_ask, put_ask = atm_from_chain([], 100.0)
    assert atm == 100
    assert call_ask is None and put_ask is None


# ─── candidate_contracts ────────────────────────────────────────────────


@pytest.mark.unit
def test_candidate_contracts_within_band_of_targets():
    # price 218.10, one_sd 18.40 → upside 254.90, downside 181.30. band 15%.
    chain = [
        {"strike": 255, "side": "call", "bid": 1.0, "ask": 1.1},   # ~0% from upside → in
        {"strike": 181, "side": "put", "bid": 1.4, "ask": 1.5},    # ~0% from downside → in
        {"strike": 400, "side": "call", "bid": 0.05, "ask": 0.1},  # far → out
    ]
    out = candidate_contracts(chain, 218.10, 18.40, band_pct=15.0)
    strikes = sorted(c.strike for c in out)
    assert strikes == [181, 255]
    assert all(isinstance(c, ContractQuote) for c in out)


@pytest.mark.unit
def test_candidate_contracts_empty_chain():
    assert candidate_contracts([], 100.0, 5.0, band_pct=15.0) == []


@pytest.mark.unit
def test_candidate_contracts_carries_occ_symbol():
    # The OCC symbol from the chain row must survive into the ContractQuote so the
    # eventual order can name the exact contract.
    chain = [{"strike": 255, "side": "call", "bid": 1.0, "ask": 1.1, "symbol": "DRI260627C00255000"}]
    out = candidate_contracts(chain, 218.10, 18.40, band_pct=15.0)
    assert out[0].symbol == "DRI260627C00255000"


@pytest.mark.unit
def test_build_screener_carries_occ_symbol():
    sd = compute_sd(218.10, 8.90, 9.50, 220.0)
    quotes = [ContractQuote(strike=255, side="call", bid=1.0, ask=1.10, symbol="DRI260627C00255000")]
    assert build_screener(quotes, sd, CFG)[0].symbol == "DRI260627C00255000"


# ─── pick_best_play ─────────────────────────────────────────────────────


def _scan_input(**overrides) -> AnalysisInput:
    """A clean week-of-earnings setup on a high-priced stock, used for scan gates."""
    base = dict(
        ticker="DRI",
        current_price=218.10,
        earnings_date=date(2026, 6, 25),
        today=date(2026, 6, 18),
        expiry_date=date(2026, 6, 27),
        has_e_badge=True,
        atm_strike=220.0,
        atm_call_ask=8.90,
        atm_put_ask=9.50,
        contracts=(
            ContractQuote(strike=255, side="call", bid=0.75, ask=0.80),   # $80 valid call, in-zone, tight
            ContractQuote(strike=280, side="call", bid=0.45, ask=0.50),   # $50 valid call, near-zone (not in zone)
            ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),   # $200 too expensive
            ContractQuote(strike=181, side="put", bid=0.75, ask=0.80),    # $80 valid put, in-zone (downside ~181.30)
        ),
        large_historical_moves=True,
    )
    base.update(overrides)
    return AnalysisInput(**base)


@pytest.mark.unit
def test_pick_best_strangle_prefers_cheapest_in_zone_each_leg():
    result = analyze(_scan_input(), cfg=CFG)
    call_leg, put_leg = pick_best_strangle(result)
    assert call_leg is not None and put_leg is not None
    assert call_leg.strike == 255  # in-zone $80 call wins over the cheaper near-zone $50
    assert call_leg.in_two_sd_zone is True
    assert put_leg.strike == 181
    assert put_leg.side == "put"


@pytest.mark.unit
def test_pick_best_strangle_none_legs_when_no_valid_play():
    result = analyze(
        _scan_input(contracts=(ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),)),
        cfg=CFG,
    )
    assert pick_best_strangle(result) == (None, None)


# ─── evaluate_candidate (the four gates) ────────────────────────────────


SCAN_CRIT = ScanCriteria(min_suitability=6, max_2sd_cost=100.0)


@pytest.mark.unit
def test_evaluate_candidate_all_gates_pass():
    result = analyze(_scan_input(), cfg=CFG)
    cand = evaluate_candidate(result, SCAN_CRIT, price=218.10)
    assert cand.qualifies is True
    assert cand.failed_gates == ()
    assert cand.call_leg.strike == 255
    assert cand.put_leg.strike == 181
    assert cand.strangle_cost == pytest.approx(160.0)  # $80 call + $80 put
    assert cand.ticker == "DRI"


@pytest.mark.unit
def test_evaluate_candidate_fails_when_missing_put_leg():
    # A clean call leg but no put → not a strangle, so valid_play fails.
    result = analyze(
        _scan_input(contracts=(ContractQuote(strike=255, side="call", bid=0.75, ask=0.80),)),
        cfg=CFG,
    )
    cand = evaluate_candidate(result, SCAN_CRIT, price=218.10)
    assert cand.qualifies is False
    assert "valid_play" in cand.failed_gates
    assert cand.call_leg is not None and cand.put_leg is None


@pytest.mark.unit
def test_evaluate_candidate_fails_suitability():
    # cheap stock + expensive options + no earnings/history tanks the score below threshold.
    result = analyze(
        _scan_input(
            current_price=30.0,
            has_e_badge=False,
            large_historical_moves=False,
            contracts=(ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),),
        ),
        cfg=CFG,
    )
    cand = evaluate_candidate(result, SCAN_CRIT, price=30.0)
    assert cand.qualifies is False
    assert "suitability" in cand.failed_gates


@pytest.mark.unit
def test_evaluate_candidate_fails_cost_and_valid_play():
    result = analyze(
        _scan_input(contracts=(ContractQuote(strike=250, side="call", bid=1.90, ask=2.00),)),
        cfg=CFG,
    )
    cand = evaluate_candidate(result, SCAN_CRIT, price=218.10)
    assert cand.qualifies is False
    assert "valid_play" in cand.failed_gates
    assert "cost" in cand.failed_gates


@pytest.mark.unit
def test_evaluate_candidate_fails_liquidity():
    # Both legs are Valid Plays, but the call leg has a wide spread → liquidity gate trips.
    result = analyze(
        _scan_input(contracts=(
            ContractQuote(strike=255, side="call", bid=0.40, ask=0.80),   # $80 valid call, wide spread
            ContractQuote(strike=181, side="put", bid=0.75, ask=0.80),    # $80 valid put, tight
        )),
        cfg=CFG,
    )
    cand = evaluate_candidate(result, SCAN_CRIT, price=218.10)
    assert cand.qualifies is False
    assert "liquidity" in cand.failed_gates
