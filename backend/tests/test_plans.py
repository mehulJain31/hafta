"""Phase 1 — schedule generation (pure, no DB, no Claude)."""

from datetime import date
from types import SimpleNamespace

import pytest

from enums import PlanType
from plans import ScheduleError, generate_schedule, get_options


def policy(**kw):
    base = dict(
        max_installments=4,
        min_installment_cents=2500,
        allowed_plan_types=[PlanType.FULL, PlanType.SPLIT],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def amounts(items):
    return [it.amount_cents for it in items]


def dates(items):
    return [it.due_date for it in items]


def test_split_even():
    items = generate_schedule(100_000, date(2026, 1, 15), PlanType.SPLIT, policy())
    assert amounts(items) == [25000, 25000, 25000, 25000]
    assert dates(items) == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)]


def test_split_remainder_on_last():
    items = generate_schedule(100_001, date(2026, 1, 15), PlanType.SPLIT, policy())
    assert amounts(items) == [25000, 25000, 25000, 25001]
    assert sum(amounts(items)) == 100_001


def test_month_end_clamps_from_original_anchor():
    # Non-leap year: Jan 31 → Feb 28, Mar 31, Apr 30.
    items = generate_schedule(100_000, date(2026, 1, 31), PlanType.SPLIT, policy())
    assert dates(items) == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_month_end_leap_year():
    items = generate_schedule(100_000, date(2028, 1, 31), PlanType.SPLIT, policy())
    assert dates(items)[1] == date(2028, 2, 29)


def test_full_is_single_installment():
    items = generate_schedule(45_000, date(2026, 2, 2), PlanType.FULL, policy())
    assert len(items) == 1
    assert items[0].amount_cents == 45_000 and items[0].due_date == date(2026, 2, 2)


def test_split_below_minimum_raises():
    # $90 over 4 → $22.50 each, below the $25 minimum.
    with pytest.raises(ScheduleError):
        generate_schedule(9_000, date(2026, 1, 15), PlanType.SPLIT, policy())


def test_options_exclude_split_when_below_minimum():
    loan = SimpleNamespace(amount_due_cents=9_000, due_date=date(2026, 1, 15))
    opts = get_options(loan, policy())
    assert [o["plan_type"] for o in opts] == [PlanType.FULL]


def test_options_respect_allowed_plan_types():
    loan = SimpleNamespace(amount_due_cents=100_000, due_date=date(2026, 1, 15))
    opts = get_options(loan, policy(allowed_plan_types=[PlanType.FULL]))
    assert [o["plan_type"] for o in opts] == [PlanType.FULL]


def test_options_full_and_split():
    loan = SimpleNamespace(amount_due_cents=100_000, due_date=date(2026, 1, 15))
    opts = get_options(loan, policy())
    assert [o["plan_type"] for o in opts] == [PlanType.FULL, PlanType.SPLIT]
    assert len(opts[1]["installments"]) == 4
    assert opts[1]["installments"][0] == {"n": 1, "amount_cents": 25000, "due_date": "2026-01-15"}
