"""Phase 2 — the tool-driven flow, with Claude mocked."""

from datetime import date

import pytest
from sqlmodel import select

import agent
import store
from enums import Outcome, PaymentChoice, PlanStatus
from models import Conversation, PaymentPlan


def _run_turn(tool=None, text="ok", args=None, summary=None):
    def fake(*a, **k):
        return {"text": text, "tool": tool, "tool_args": args or {}, "summary": summary}
    return fake


def _loan_and_session(session, cents=100_000, due=date(2026, 1, 15), verify=True):
    loan = store.create_loan(session, "Jordan Lee", "555-123-4567", cents, due)
    cid = store.open_session(session, loan.id)["conversation_id"]
    if verify:
        store.verify(session, cid, "4567")  # last 4 of 5551234567
    return loan, cid


def _kinds(detail):
    return [m["kind"] for m in detail["messages"]]


def test_full_split_flow(session, monkeypatch):
    loan, cid = _loan_and_session(session)

    monkeypatch.setattr(agent, "run_turn", _run_turn(tool="show_reason_picker", text="Sorry to hear that."))
    d = store.reply(session, cid, "I can't pay all of it")
    assert "reason_picker" in _kinds(d)

    monkeypatch.setattr(agent, "run_turn", _run_turn(tool="get_options", text="Here's what I can offer."))
    d = store.pick_reason(session, cid, "REDUCED_INCOME")
    assert "options_card" in _kinds(d)
    opts = next(m["payload"]["options"] for m in d["messages"] if m["kind"] == "options_card")
    assert {o["plan_type"] for o in opts} == {"FULL", "SPLIT"}

    monkeypatch.setattr(agent, "say", lambda *a, **k: "Tap Confirm to lock it in.")
    d = store.choose_option(session, cid, "SPLIT")
    plan = session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid)).first()
    assert plan.status == PlanStatus.PROPOSED.value
    assert "plan_summary" in _kinds(d)

    d = store.confirm(session, cid, plan.id)
    session.refresh(plan)
    assert plan.status == PlanStatus.CONFIRMED.value
    assert d["ended"] is True
    assert d["payment_choice"] == PaymentChoice.SPLIT.value
    assert d["confirmed_plan"]["plan_type"] == "SPLIT"
    assert len(d["confirmed_plan"]["installments"]) == 4
    assert sum(i["amount_cents"] for i in d["confirmed_plan"]["installments"]) == 100_000


def test_bankruptcy_escalates_without_plan(session, monkeypatch):
    # run_turn must not even be called for an auto-escalate reason.
    monkeypatch.setattr(agent, "run_turn", _run_turn(tool="get_options"))
    loan, cid = _loan_and_session(session)
    d = store.pick_reason(session, cid, "BANKRUPTCY")
    assert d["outcome"] == Outcome.ESCALATED.value
    assert d["ended"] is True
    assert session.get(Conversation, cid).loan_id == loan.id
    assert session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid)).first() is None
    session.refresh(loan)
    assert loan.status == "escalated"


def test_confirm_is_idempotent(session, monkeypatch):
    monkeypatch.setattr(agent, "say", lambda *a, **k: "ok")
    loan, cid = _loan_and_session(session)
    store.choose_option(session, cid, "SPLIT")
    plan = session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid)).first()
    store.confirm(session, cid, plan.id)
    # second confirm (convo is ended now) still must not create a second plan
    store.confirm_plan(session, session.get(Conversation, cid), loan, plan.id)
    confirmed = session.exec(select(PaymentPlan).where(PaymentPlan.loan_id == loan.id,
                             PaymentPlan.status == PlanStatus.CONFIRMED.value)).all()
    assert len(confirmed) == 1


def test_repeated_propose_returns_same_row(session, monkeypatch):
    monkeypatch.setattr(agent, "say", lambda *a, **k: "ok")
    loan, cid = _loan_and_session(session)
    convo = session.get(Conversation, cid)
    p1 = store.propose_plan(session, convo, loan, "SPLIT")
    p2 = store.propose_plan(session, convo, loan, "SPLIT")
    assert p1.id == p2.id


def test_second_confirmed_plan_supersedes(session, monkeypatch):
    monkeypatch.setattr(agent, "say", lambda *a, **k: "ok")
    loan, cid = _loan_and_session(session)
    store.choose_option(session, cid, "SPLIT")
    plan_a = session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid)).first()
    store.confirm(session, cid, plan_a.id)

    # New conversation on the same loan confirms a new plan.
    cid2 = store.open_session(session, loan.id)["conversation_id"]
    store.verify(session, cid2, "4567")
    store.choose_option(session, cid2, "FULL")
    plan_b = session.exec(select(PaymentPlan).where(PaymentPlan.conversation_id == cid2)).first()
    store.confirm(session, cid2, plan_b.id)

    session.refresh(plan_a)
    assert plan_a.status == PlanStatus.SUPERSEDED.value
    confirmed = session.exec(select(PaymentPlan).where(PaymentPlan.loan_id == loan.id,
                             PaymentPlan.status == PlanStatus.CONFIRMED.value)).all()
    assert len(confirmed) == 1 and confirmed[0].id == plan_b.id


def test_bad_reason_code_raises(session):
    loan, cid = _loan_and_session(session)
    with pytest.raises(ValueError):
        store.pick_reason(session, cid, "NOPE")


def test_verify_success_reveals_amount(session):
    loan, cid = _loan_and_session(session, verify=False)
    d = store.verify(session, cid, "4567")
    assert d["verified_at"] is not None
    last_agent = [m["text"] for m in d["messages"] if m["role"] == "agent"][-1]
    assert "$1,000.00" in last_agent  # amount shared only after verifying


def test_unverified_blocks_options(session):
    loan, cid = _loan_and_session(session, verify=False)
    with pytest.raises(store.Conflict):
        store.pick_reason(session, cid, "REDUCED_INCOME")


def test_two_bad_verifications_lock(session):
    loan, cid = _loan_and_session(session, verify=False)
    store.verify(session, cid, "0000")
    d = store.verify(session, cid, "1111")
    assert d["outcome"] == Outcome.WRONG_PERSON.value and d["ended"] is True


def test_stop_keyword_ends_without_claude(session, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Claude must not be called for a STOP keyword")
    monkeypatch.setattr(agent, "run_turn", boom)
    loan, cid = _loan_and_session(session)
    d = store.reply(session, cid, "STOP")
    assert d["outcome"] == Outcome.STOP_REQUEST.value and d["ended"] is True
    session.refresh(loan)
    assert loan.status == "do_not_contact"
