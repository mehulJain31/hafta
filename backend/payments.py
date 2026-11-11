"""Posted-payments feed (Phase 6). Integer cents only.

A payment is applied to the loan's confirmed plan, marking the earliest
SCHEDULED installments PAID in order; the loan balance drops by the amount
received. A loan whose confirmed plan is fully paid becomes `resolved`.
"""

import csv
import io
from datetime import date

from sqlmodel import Session, select

from db import now_utc
from enums import InstallmentStatus, PlanStatus
from models import Installment, Loan, PaymentPlan


def _confirmed_plan(session: Session, loan_id: int) -> PaymentPlan | None:
    return session.exec(
        select(PaymentPlan).where(PaymentPlan.loan_id == loan_id, PaymentPlan.status == PlanStatus.CONFIRMED.value)
    ).first()


def apply_payment(session: Session, loan: Loan, amount_cents: int) -> dict:
    """Apply one posted payment. Returns a small summary. Commits."""
    if amount_cents <= 0:
        raise ValueError("amount must be positive")

    plan = _confirmed_plan(session, loan.id)
    paid_numbers: list[int] = []

    if plan is not None:
        remaining = amount_cents
        scheduled = session.exec(
            select(Installment).where(Installment.plan_id == plan.id,
                                      Installment.status == InstallmentStatus.SCHEDULED.value)
            .order_by(Installment.installment_number)
        ).all()
        for it in scheduled:
            if remaining >= it.amount_cents:
                it.status = InstallmentStatus.PAID.value
                it.paid_at = now_utc()
                session.add(it)
                remaining -= it.amount_cents
                paid_numbers.append(it.installment_number)
            else:
                break  # partial coverage: installment stays SCHEDULED

    loan.amount_due_cents = max(0, loan.amount_due_cents - amount_cents)
    loan.updated_at = now_utc()

    if plan is not None:
        all_insts = session.exec(select(Installment).where(Installment.plan_id == plan.id)).all()
        if all(i.status == InstallmentStatus.PAID.value for i in all_insts):
            loan.status = "resolved"
    elif loan.amount_due_cents == 0:
        loan.status = "resolved"

    session.add(loan)
    session.commit()
    return {"loan_id": loan.id, "installments_paid": paid_numbers,
            "loan_balance_cents": loan.amount_due_cents, "loan_status": loan.status}


def import_csv(session: Session, csv_text: str) -> dict:
    """Import rows of `external_loan_ref,amount_cents,posted_date`."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    results, errors = [], []
    for i, row in enumerate(reader, start=1):
        try:
            ref = (row["external_loan_ref"] or "").strip()
            amount = int(row["amount_cents"])
        except (KeyError, ValueError, TypeError):
            errors.append({"row": i, "error": "bad columns (need external_loan_ref, amount_cents, posted_date)"})
            continue
        loan = session.exec(select(Loan).where(Loan.external_loan_ref == ref)).first()
        if loan is None:
            errors.append({"row": i, "error": f"no loan with external_loan_ref {ref!r}"})
            continue
        results.append(apply_payment(session, loan, amount))
    return {"applied": results, "errors": errors}


def mark_past_due(session: Session, today: date | None = None) -> dict:
    """Flag SCHEDULED installments whose due date has passed (nightly job stub)."""
    today = today or date.today()
    rows = session.exec(
        select(Installment).where(Installment.status == InstallmentStatus.SCHEDULED.value,
                                  Installment.due_date < today)
    ).all()
    for it in rows:
        it.status = InstallmentStatus.PAST_DUE.value
        session.add(it)
    session.commit()
    return {"marked_past_due": len(rows)}
