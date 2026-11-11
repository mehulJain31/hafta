"""Phase 6 — posted-payments feed."""

from datetime import date, timedelta

import agent
import payments
import store
from enums import InstallmentStatus, PlanStatus
from models import Installment, Loan, PaymentPlan
from sqlmodel import select


def _confirmed_split(session, monkeypatch, cents=100_000):
    """A loan with a confirmed 4×split plan. Returns (loan, plan)."""
    monkeypatch.setattr(agent, "say", lambda *a, **k: "ok")
    loan = store.create_loan(session, "Jordan Lee", "555-123-4567", cents, date(2026, 1, 15))
    cid = store.open_session(session, loan.id)["conversation_id"]
    store.verify(session, cid, "4567")
    store.choose_option(session, cid, "SPLIT")
    plan = session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid)).first()
    store.confirm(session, cid, plan.id)
    session.refresh(loan)
    return loan, plan


def _installments(session, plan_id):
    return session.exec(select(Installment).where(Installment.plan_id == plan_id)
                        .order_by(Installment.installment_number)).all()


def test_full_installment_payment(session, monkeypatch):
    loan, plan = _confirmed_split(session, monkeypatch)
    r = payments.apply_payment(session, loan, 25_000)  # exactly installment 1
    insts = _installments(session, plan.id)
    assert insts[0].status == InstallmentStatus.PAID.value
    assert insts[1].status == InstallmentStatus.SCHEDULED.value
    assert r["loan_balance_cents"] == 75_000


def test_partial_payment_leaves_installment_scheduled(session, monkeypatch):
    loan, plan = _confirmed_split(session, monkeypatch)
    r = payments.apply_payment(session, loan, 30_000)  # covers inst 1, 5000 toward inst 2
    insts = _installments(session, plan.id)
    assert insts[0].status == InstallmentStatus.PAID.value
    assert insts[1].status == InstallmentStatus.SCHEDULED.value
    assert r["loan_balance_cents"] == 70_000


def test_overpayment_resolves_loan(session, monkeypatch):
    loan, plan = _confirmed_split(session, monkeypatch)
    r = payments.apply_payment(session, loan, 120_000)  # more than the total
    assert all(i.status == InstallmentStatus.PAID.value for i in _installments(session, plan.id))
    assert r["loan_balance_cents"] == 0 and r["loan_status"] == "resolved"


def test_payment_without_plan_reduces_balance(session):
    loan = store.create_loan(session, "No Plan", "555-999-0000", 50_000, date(2026, 1, 15))
    r = payments.apply_payment(session, loan, 20_000)
    assert r["loan_balance_cents"] == 30_000
    assert session.exec(select(PaymentPlan).where(PaymentPlan.loan_id == loan.id)).first() is None


def test_mark_past_due(session, monkeypatch):
    loan, plan = _confirmed_split(session, monkeypatch)
    # due dates are Jan–Apr 2026; "today" well after them.
    out = payments.mark_past_due(session, today=date(2026, 6, 1))
    assert out["marked_past_due"] == 4
    assert all(i.status == InstallmentStatus.PAST_DUE.value for i in _installments(session, plan.id))


def test_import_csv_matches_external_ref(session, monkeypatch):
    loan, plan = _confirmed_split(session, monkeypatch)
    loan.external_loan_ref = "CORE-123"
    session.add(loan)
    session.commit()
    csv_text = "external_loan_ref,amount_cents,posted_date\nCORE-123,25000,2026-01-16\nNOPE,100,2026-01-16\n"
    out = payments.import_csv(session, csv_text)
    assert len(out["applied"]) == 1 and len(out["errors"]) == 1
    assert _installments(session, plan.id)[0].status == InstallmentStatus.PAID.value
