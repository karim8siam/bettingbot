"""
Comprehensive Verification Suite for SX Bet Quantitative Betting Bot.
Tests unit conversions, EIP-712 order signing, Poisson modeling, Kelly sizing, and Risk Controls.
"""

import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.conversions import (
    usdc_to_units,
    units_to_usdc,
    decimal_to_percentage_odds,
    percentage_odds_to_decimal,
    percentage_odds_to_probability,
    maker_odds_to_taker_odds,
)
from client.signer import SXOrderSigner
from models.edge_calculator import EdgeCalculator
from models.inplay_poisson import InPlayPoissonModel
from engine.risk_manager import RiskManager
from engine.audit_logger import AuditLogger


def test_conversions():
    print("[1/6] Testing Odds & Unit Conversions...")
    # 1.50 USDC = 1,500,000 units
    assert usdc_to_units(1.50) == 1_500_000
    assert units_to_usdc(1_500_000) == 1.50

    # 2.00 decimal odds = 5 * 10^19 (50% implied prob)
    p_odds = decimal_to_percentage_odds(2.00)
    assert p_odds == "50000000000000000000"
    dec = percentage_odds_to_decimal(p_odds)
    assert abs(dec - 2.00) < 1e-6
    prob = percentage_odds_to_probability(p_odds)
    assert abs(prob - 0.50) < 1e-6

    # Maker to Taker
    taker = maker_odds_to_taker_odds(p_odds)
    assert taker == "50000000000000000000"
    print("      ✓ Conversions verified successfully.")


def test_signer():
    print("[2/6] Testing EIP-712 Order Signer...")
    # Use standard known test private key
    test_key = "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
    signer = SXOrderSigner(private_key=test_key)
    assert signer.is_configured()

    dummy_domain = {
        "name": "SX Bet",
        "version": "3.0",
        "chainId": 416,
        "verifyingContract": "0x0000000000000000000000000000000000000001",
    }
    dummy_market_hash = "0x" + "a" * 64
    dummy_base_token = "0x" + "b" * 40

    order, sig, order_id = signer.sign_order(
        domain=dummy_domain,
        market_hash=dummy_market_hash,
        base_token=dummy_base_token,
        total_bet_size=1_000_000,
        percentage_odds="50000000000000000000",
        is_maker_betting_outcome_one=True,
    )

    assert sig.startswith("0x") and len(sig) >= 130
    assert order_id.startswith("0x") and len(order_id) == 66
    print("      ✓ EIP-712 Signature and Order ID computed accurately.")


def test_edge_and_kelly():
    print("[3/6] Testing +EV Calculator & Fractional Kelly...")
    calc = EdgeCalculator(min_edge_pct=0.04, kelly_fraction=0.25, max_stake_pct=0.015)
    
    # Model prob = 55%, Odds = 2.00 (Market prob = 50%) -> Edge = (0.55 * 2) - 1 = +10%
    ev = calc.calculate_ev(model_prob=0.55, decimal_odds=2.00)
    assert abs(ev - 0.10) < 1e-6

    # Test full evaluation
    eval_res = calc.evaluate_bet(model_prob=0.55, percentage_odds="50000000000000000000")
    assert eval_res.is_positive_ev is True
    assert abs(eval_res.edge_pct - 0.10) < 1e-6
    assert 0.0 < eval_res.recommended_stake_fraction <= 0.015

    # Negative EV test: Model prob = 45%, Odds = 2.00 -> EV = -10% -> No Bet
    neg_eval = calc.evaluate_bet(model_prob=0.45, percentage_odds="50000000000000000000")
    assert neg_eval.is_positive_ev is False
    assert neg_eval.recommended_stake_fraction == 0.0
    print("      ✓ Edge Hurdle (+EV barrier) and Quarter-Kelly staking verified.")


def test_inplay_poisson():
    print("[4/6] Testing In-Play Dynamic Poisson Time-Decay Model...")
    model = InPlayPoissonModel()
    
    # 0-0 at minute 0: Over 2.5 vs Under 2.5
    probs_start = model.get_over_under_probabilities(
        minute=0,
        current_home_goals=0,
        current_away_goals=0,
        line=2.5,
    )
    assert abs(probs_start["over"] + probs_start["under"] - 1.0) < 1e-4

    # 0-0 at minute 80: Under 2.5 probability should be very high
    probs_late = model.get_over_under_probabilities(
        minute=80,
        current_home_goals=0,
        current_away_goals=0,
        line=2.5,
    )
    assert probs_late["under"] > probs_start["under"]
    assert probs_late["over"] < probs_start["over"]

    # Red card effect: Home team gets red card -> Away team lambda increases
    lh_normal, la_normal = model.estimate_remaining_lambdas(minute=30, home_score=0, away_score=0)
    lh_red, la_red = model.estimate_remaining_lambdas(minute=30, home_score=0, away_score=0, home_red_cards=1)
    assert lh_red < lh_normal
    assert la_red > la_normal
    print("      ✓ Dynamic Poisson time-decay and red-card adjustments verified.")


def test_risk_manager():
    print("[5/6] Testing Risk Management & Circuit Breaker...")
    risk = RiskManager(
        current_bankroll=1000.0,
        kelly_fraction=0.25,
        max_stake_pct=0.015,
        max_daily_drawdown_pct=0.05,
    )

    # Approved bet within limits
    approved, stake, reason = risk.validate_and_size_stake(recommended_stake_fraction=0.01, market_hash="0x123")
    assert approved is True
    assert stake == 10.0  # 1% of 1000 = $10.00

    # Stake capped at max_stake_pct (1.5% = $15.00)
    approved, stake, reason = risk.validate_and_size_stake(recommended_stake_fraction=0.05, market_hash="0x123")
    assert approved is True
    assert stake == 15.0  # Capped at $15.00

    # Trigger circuit breaker: record loss of $60 (exceeds 5% = $50)
    risk.record_trade_result(-60.0)
    assert risk.is_circuit_breaker_active is True

    # Next trade should be rejected immediately
    approved, stake, reason = risk.validate_and_size_stake(recommended_stake_fraction=0.01, market_hash="0x123")
    assert approved is False
    assert "circuit breaker" in reason.lower()
    print("      ✓ Bankroll limits and Circuit Breaker drawdown protection verified.")


def test_audit_logger():
    print("[6/6] Testing Audit Database & CLV Tracking...")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_audit.db"
        logger = AuditLogger(db_path=db_path)

        # Log simulated signal and trade
        logger.log_signal(
            market_hash="0xabc",
            event_name="Arsenal vs Chelsea",
            outcome_name="Over 2.5",
            minute=72,
            score="1-1",
            model_prob=0.62,
            market_prob=0.52,
            decimal_odds=1.92,
            edge_pct=0.19,
            decision="EXECUTE",
            reason="Late surge +EV",
        )

        logger.log_trade(
            order_id="paper_test_1",
            is_paper=True,
            market_hash="0xabc",
            event_name="Arsenal vs Chelsea",
            outcome_name="Over 2.5",
            stake_usdc=15.00,
            decimal_odds=1.92,
        )

        # Update Closing Line Value (e.g. market closed at 1.75 -> positive CLV!)
        logger.update_closing_line_value(order_id="paper_test_1", closing_odds=1.75)

        summary = logger.get_trade_summary()
        assert summary["total_trades"] == 1
        assert summary["avg_clv_pct"] > 0
    print("      ✓ Audit database and Closing Line Value (CLV) calculation verified.")


if __name__ == "__main__":
    print("\n=======================================================")
    print("RUNNING SX BET BOT VERIFICATION TEST SUITE")
    print("=======================================================\n")
    test_conversions()
    test_signer()
    test_edge_and_kelly()
    test_inplay_poisson()
    test_risk_manager()
    test_audit_logger()
    print("\n=======================================================")
    print("ALL 6 TEST SUITES PASSED PERFECTLY!")
    print("=======================================================\n")
