"""Deterministic payment-plan math. Pure functions, integer cents only.

This is the heart of the refactor: **code builds the plan, Claude never emits a
dollar amount or a date.** `generate_schedule` is the single source of every
installment amount and date; `get_options` returns the only arrangements the
credit union's policy allows. No floats anywhere.
"""

import calendar
from dataclasses import dataclass
from datetime import date

from enums import PlanType


@dataclass(frozen=True)
class ScheduleItem:
    installment_number: int  # 1-based
    amount_cents: int
    due_date: date


def _add_months(anchor: date, months: int) -> date:
    """`anchor` shifted by whole months, keeping its day-of-month.

    Always computed from the *original* anchor (not the previous installment),
    so a short month clamps to its last day without drifting: Jan 31 + 1 →
    Feb 28/29, + 2 → Mar 31, + 3 → Apr 30.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last_day))


class ScheduleError(ValueError):
    """The requested plan can't be built within policy (so it isn't offered)."""


def generate_schedule(total_cents: int, due_date: date, plan_type: str, policy) -> list[ScheduleItem]:
    """The exact installments for a plan type, or raise ScheduleError.

    `policy` needs `.max_installments` and `.min_installment_cents`.
    FULL → one installment on the due date.
    SPLIT → `max_installments` monthly installments summing exactly to total;
            the last absorbs the remainder.
    """
    if total_cents <= 0:
        raise ScheduleError("amount must be positive")

    if plan_type == PlanType.FULL:
        return [ScheduleItem(1, total_cents, due_date)]

    if plan_type == PlanType.SPLIT:
        n = policy.max_installments
        if n < 2:
            raise ScheduleError("split needs at least 2 installments")
        base = total_cents // n
        items = [
            ScheduleItem(
                installment_number=i + 1,
                amount_cents=base if i < n - 1 else total_cents - base * (n - 1),
                due_date=_add_months(due_date, i),
            )
            for i in range(n)
        ]
        if any(it.amount_cents < policy.min_installment_cents for it in items):
            raise ScheduleError("an installment would fall below the policy minimum")
        return items

    raise ScheduleError(f"unknown plan type {plan_type!r}")


def get_options(loan, policy) -> list[dict]:
    """Every plan the policy allows for this loan, fully computed.

    Returns [{plan_type, installments: [{n, amount_cents, due_date (ISO)}]}].
    An option that can't be built within policy is silently omitted.
    """
    options = []
    for plan_type in policy.allowed_plan_types:
        try:
            schedule = generate_schedule(loan.amount_due_cents, loan.due_date, plan_type, policy)
        except ScheduleError:
            continue
        options.append({
            "plan_type": plan_type,
            "installments": [
                {"n": it.installment_number, "amount_cents": it.amount_cents, "due_date": it.due_date.isoformat()}
                for it in schedule
            ],
        })
    return options
