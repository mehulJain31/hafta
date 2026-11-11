"""Persistence + the deterministic handlers behind Richie's tools.

The server owns the transcript (rebuilt from `messages`, never trusted from the
client) and builds every payment plan itself. Claude only explains, classifies
the reason, and confirms — it never emits an amount or a date.

Mutating operations return `conversation_detail(...)` so the frontend re-renders
the whole conversation (text + structured cards) from one response.
"""

from datetime import date

from sqlmodel import Session, select

import agent
import frequency
import plans
import policies
from db import now_utc
from enums import (
    END_CONVERSATION_OUTCOMES,
    InstallmentStatus,
    Outcome,
    PaymentChoice,
    PlanStatus,
    PlanType,
    ReasonCode,
)
from models import (
    Conversation,
    CuPolicy,
    Customer,
    Installment,
    Loan,
    Message,
    PaymentPlan,
)

# Reason chips shown to the member (NONE is never offered).
REASON_LABELS = {
    ReasonCode.JOB_LOSS: "Lost my job",
    ReasonCode.REDUCED_INCOME: "Income went down",
    ReasonCode.MEDICAL_EXPENSE: "Medical costs",
    ReasonCode.DEATH_IN_FAMILY: "Death in the family",
    ReasonCode.UNEXPECTED_EXPENSE: "Unexpected expense",
    ReasonCode.BANKRUPTCY: "Bankruptcy",
    ReasonCode.OTHER: "Other",
}

_PLAN_OUTCOME = {PlanType.FULL.value: Outcome.PROMISE_TO_PAY.value, PlanType.SPLIT.value: Outcome.PAYMENT_PLAN.value}


class ContactBlocked(Exception):
    """Raised when a loan must not be contacted again (opt-out or attorney)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class NotFound(Exception):
    pass


class Conflict(Exception):
    """A step that can't be repeated (e.g. a second reason or confirm)."""


# --- lookups ------------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """Canonical digits so the same number entered differently matches (US demo:
    a leading country-code '1' on 11 digits is dropped)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def get_policy(session: Session, credit_union_id: int) -> CuPolicy:
    policy = session.exec(select(CuPolicy).where(CuPolicy.credit_union_id == credit_union_id)).first()
    if policy is None:
        raise NotFound("No policy configured for this credit union.")
    return policy


def _open_loan(session: Session, customer_id: int) -> Loan | None:
    return session.exec(
        select(Loan).where(Loan.customer_id == customer_id, Loan.status != "resolved")
        .order_by(Loan.created_at.desc())
    ).first()


def _confirmed_plan(session: Session, loan_id: int) -> PaymentPlan | None:
    return session.exec(
        select(PaymentPlan).where(PaymentPlan.loan_id == loan_id, PaymentPlan.status == PlanStatus.CONFIRMED.value)
    ).first()


# --- loans (Phase 3: operator creates test data, no chat) ---------------------

def create_loan(session: Session, name: str, phone: str, amount_due_cents: int, due_date: date) -> Loan:
    """Upsert the customer by phone and create/refresh their open loan. No chat."""
    digits = normalize_phone(phone)
    customer = session.exec(select(Customer).where(Customer.phone_number == digits)).first()
    if customer is None:
        customer = Customer(name=name, phone_number=digits, timezone=_default_tz())
        session.add(customer)
        session.commit()
        session.refresh(customer)
    elif customer.name != name:
        customer.name = name
        session.add(customer)

    loan = _open_loan(session, customer.id)
    if loan is None:
        loan = Loan(customer_id=customer.id, amount_due_cents=amount_due_cents, due_date=due_date)
    else:
        loan.amount_due_cents = amount_due_cents
        loan.due_date = due_date
        loan.updated_at = now_utc()
    session.add(loan)
    session.commit()
    session.refresh(loan)
    return loan


def _default_tz() -> str:
    import os
    return os.getenv("DEFAULT_TIMEZONE", "America/Los_Angeles")


def loans_due(session: Session, status: str = "in_collections") -> list[dict]:
    rows = session.exec(select(Loan).where(Loan.status == status).order_by(Loan.due_date)).all()
    out = []
    for loan in rows:
        customer = session.get(Customer, loan.customer_id)
        last = session.exec(
            select(Conversation).where(Conversation.loan_id == loan.id).order_by(Conversation.started_at.desc())
        ).first()
        open_convo = session.exec(
            select(Conversation).where(Conversation.loan_id == loan.id, Conversation.status == "open")
            .order_by(Conversation.started_at.desc())
        ).first()
        out.append({
            "loan_id": loan.id,
            "customer_name": customer.name,
            "phone_last4": customer.phone_number[-4:],
            "amount_due_cents": loan.amount_due_cents,
            "due_date": loan.due_date.isoformat(),
            "status": loan.status,
            "last_outcome": last.outcome if last else None,
            "has_confirmed_plan": _confirmed_plan(session, loan.id) is not None,
            "open_conversation_id": open_convo.id if open_convo else None,
        })
    return out


# --- sessions / conversations -------------------------------------------------

def open_session(session: Session, loan_id: int) -> dict:
    """Open a member-initiated chat for a loan. Runs the do-not-contact gate (but
    NOT the Reg F frequency gate — that's for outbound, not member-initiated)."""
    loan = session.get(Loan, loan_id)
    if loan is None:
        raise NotFound("Loan not found.")
    if loan.status == "do_not_contact":
        raise ContactBlocked("This member has asked not to be contacted, or is represented by an attorney.")
    customer = session.get(Customer, loan.customer_id)

    convo = Conversation(loan_id=loan.id)
    session.add(convo)
    session.commit()
    session.refresh(convo)

    opener = agent.opening_message(customer.name)
    session.add(Message(conversation_id=convo.id, role="agent", text=opener))
    frequency.log_attempt(session, loan.id, convo.id)  # ledger stays complete
    session.commit()
    return conversation_detail(session, convo.id)


def _require_open(session: Session, conversation_id: int) -> Conversation:
    convo = session.get(Conversation, conversation_id)
    if convo is None:
        raise NotFound("Conversation not found.")
    if convo.status == "ended":
        raise Conflict("This conversation has ended.")
    return convo


def _require_verified(convo: Conversation):
    if convo.verified_at is None:
        raise Conflict("Verify the member's identity first.")


def _history(session: Session, conversation_id: int) -> list[dict]:
    rows = session.exec(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at, Message.id)
    ).all()
    return [{"role": m.role, "text": m.text} for m in rows]


def _add_msg(session: Session, convo_id: int, role: str, text: str, kind: str = "text", payload: dict | None = None):
    session.add(Message(conversation_id=convo_id, role=role, text=text, kind=kind, payload=payload))


def prior_context(session: Session, loan: Loan, exclude_conversation_id: int | None = None) -> dict | None:
    """Structured recall of the loan's most recent *other* conversation."""
    q = select(Conversation).where(Conversation.loan_id == loan.id)
    if exclude_conversation_id is not None:
        q = q.where(Conversation.id != exclude_conversation_id)
    prev = session.exec(q.order_by(Conversation.started_at.desc())).first()
    if prev is None:
        return None
    ctx = {"last_outcome": prev.outcome, "last_reason_code": prev.reason_code,
           "last_payment_choice": prev.payment_choice}
    plan = _confirmed_plan(session, loan.id)
    if plan:
        insts = session.exec(select(Installment).where(Installment.plan_id == plan.id)
                             .order_by(Installment.installment_number)).all()
        ctx["confirmed_plan"] = {
            "plan_type": plan.plan_type,
            "installments": [{"n": i.installment_number, "due_date": i.due_date.isoformat(), "status": i.status}
                             for i in insts],
        }
    return ctx


# --- identity verification (Phase 4; stub — replace with OTP/SSO) --------------

def _is_stop(text: str) -> bool:
    return text.strip().lower().strip(".!") in policies.STOP_WORDS


def verify(session: Session, conversation_id: int, answer: str) -> dict:
    """Stub identity check: last four digits of the phone on file. Nothing about
    the account (not even the amount) is shared until this passes."""
    convo = _require_open(session, conversation_id)
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    if convo.verified_at is not None:
        return conversation_detail(session, convo.id)

    _add_msg(session, convo.id, "borrower", answer)
    if _is_stop(answer):
        _end_conversation(session, convo, loan, Outcome.STOP_REQUEST.value,
                          f"You've been opted out. {agent.LENDER_NAME} won't send you any more messages here.")
        session.commit()
        return conversation_detail(session, convo.id)

    given = "".join(c for c in answer if c.isdigit())
    if len(given) >= 4 and given[-4:] == customer.phone_number[-4:]:
        convo.verified_at = now_utc()
        session.add(convo)
        when = loan.due_date.strftime("%B %-d, %Y")
        _add_msg(session, convo.id, "agent",
                 f"Thanks, {agent.first_name(customer.name)}, you're verified. Your balance is "
                 f"{agent.money(loan.amount_due_cents)}, due {when}. When will you be able to pay?")
    else:
        convo.verify_attempts += 1
        session.add(convo)
        if convo.verify_attempts >= 2:
            _end_conversation(session, convo, loan, Outcome.WRONG_PERSON.value,
                              "I'm sorry, I can't verify your identity, so I can't share any account details. "
                              f"If you believe this is an error, please contact {agent.LENDER_NAME}.")
        else:
            _add_msg(session, convo.id, "agent",
                     "That doesn't match what we have on file. Please reply with the last four digits of the "
                     "phone number on the account.")
    session.commit()
    return conversation_detail(session, convo.id)


# --- the member free-text turn ------------------------------------------------

def reply(session: Session, conversation_id: int, borrower_text: str) -> dict:
    convo = _require_open(session, conversation_id)
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)

    # Pre-verification, the only allowed input is a STOP keyword; everything else
    # routes to /api/verify. Guard in case a client posts here anyway.
    if convo.verified_at is None and not _is_stop(borrower_text):
        raise Conflict("Verify the member's identity first.")

    _add_msg(session, convo.id, "borrower", borrower_text)
    frequency.mark_conversation(session, convo.id)
    session.commit()

    # Opt-out keyword shortcut — deterministic, no Claude (FDCPA 805(c)).
    if _is_stop(borrower_text):
        _end_conversation(session, convo, loan, Outcome.STOP_REQUEST.value,
                          f"You've been opted out. {agent.LENDER_NAME} won't send you any more messages here.")
        session.commit()
        return conversation_detail(session, convo.id)

    context = prior_context(session, loan, exclude_conversation_id=convo.id)
    turn = agent.run_turn(customer.name, loan.amount_due_cents, loan.due_date, _history(session, convo.id), context)

    if turn.get("summary"):
        convo.summary = turn["summary"]
        session.add(convo)
    if turn.get("text"):
        _add_msg(session, convo.id, "agent", turn["text"])

    tool = turn.get("tool")
    args = turn.get("tool_args") or {}
    if tool == "show_reason_picker":
        _write_reason_picker(session, convo)
    elif tool == "get_options":
        _write_options_card(session, convo, loan)
    elif tool == "escalate":
        _escalate(session, convo, loan, args.get("reason", "OTHER"),
                  turn.get("text") or f"Thanks for letting me know. A member of {agent.LENDER_NAME}'s team will reach out.")
    elif tool == "end_conversation":
        outcome = args.get("outcome", Outcome.ESCALATED.value)
        if outcome in {o.value for o in END_CONVERSATION_OUTCOMES}:
            _end_conversation(session, convo, loan, outcome,
                              turn.get("text") or "Thanks — I'll close this out here.")

    session.commit()
    return conversation_detail(session, convo.id)


# --- structured selections (do NOT go through Claude for the data) ------------

def pick_reason(session: Session, conversation_id: int, reason_code: str, note: str | None = None) -> dict:
    convo = _require_open(session, conversation_id)
    _require_verified(convo)
    if reason_code not in {r.value for r in ReasonCode} or reason_code == ReasonCode.NONE.value:
        raise ValueError("unknown reason code")
    if convo.reason_code:
        raise Conflict("A reason was already recorded.")
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    policy = get_policy(session, loan.credit_union_id)

    convo.reason_code = reason_code
    convo.reason_note = note if reason_code == ReasonCode.OTHER.value else None
    session.add(convo)
    _add_msg(session, convo.id, "borrower", f"Reason: {REASON_LABELS.get(ReasonCode(reason_code), reason_code)}")

    if reason_code in (policy.auto_escalate_reasons or []):
        _escalate(session, convo, loan, reason_code,
                  f"Thank you for letting me know. A member of {agent.LENDER_NAME}'s team will reach out about your options.")
        session.commit()
        return conversation_detail(session, convo.id)

    session.commit()
    context = prior_context(session, loan, exclude_conversation_id=convo.id)
    turn = agent.run_turn(customer.name, loan.amount_due_cents, loan.due_date, _history(session, convo.id), context)
    if turn.get("summary"):
        convo.summary = turn["summary"]; session.add(convo)
    if turn.get("text"):
        _add_msg(session, convo.id, "agent", turn["text"])
    if turn.get("tool") == "get_options":
        _write_options_card(session, convo, loan)
    elif turn.get("tool") == "escalate":
        _escalate(session, convo, loan, (turn.get("tool_args") or {}).get("reason", "OTHER"),
                  turn.get("text") or "A member of the team will reach out.")
    session.commit()
    return conversation_detail(session, convo.id)


def choose_option(session: Session, conversation_id: int, plan_type: str) -> dict:
    convo = _require_open(session, conversation_id)
    _require_verified(convo)
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    plan = propose_plan(session, convo, loan, plan_type)  # server-side; writes the plan_summary card
    _add_msg(session, convo.id, "borrower", f"I'll take the {plan_type} plan.")
    session.commit()

    try:
        text = agent.say(customer.name, loan.amount_due_cents, loan.due_date, _history(session, convo.id),
                         "Say the plan is set up and ask them to tap Confirm to lock it in. "
                         "Do not restate the amounts or dates — the card shows them. One or two sentences.")
    except agent.ClovefiError:
        text = "Great — I've set that up. Tap Confirm below to lock it in."
    _add_msg(session, convo.id, "agent", text)
    session.commit()
    return conversation_detail(session, convo.id)


def confirm(session: Session, conversation_id: int, plan_id: int) -> dict:
    convo = _require_open(session, conversation_id)
    _require_verified(convo)
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    confirm_plan(session, convo, loan, plan_id)
    _add_msg(session, convo.id, "borrower", "Confirmed.")
    session.commit()

    try:
        text = agent.say(customer.name, loan.amount_due_cents, loan.due_date, _history(session, convo.id),
                         f"Confirm the plan is locked in, thank them, and say {agent.LENDER_NAME} will send payment "
                         "instructions. One or two sentences; don't restate amounts or dates.")
    except agent.ClovefiError:
        text = f"You're all set — thank you. {agent.LENDER_NAME} will send payment instructions."
    _add_msg(session, convo.id, "agent", text)
    session.commit()
    return conversation_detail(session, convo.id)


# --- tool handlers (deterministic) --------------------------------------------

def _write_reason_picker(session: Session, convo: Conversation):
    options = [{"code": code.value, "label": label} for code, label in REASON_LABELS.items()]
    _add_msg(session, convo.id, "agent", "What's making it hard to pay the full amount right now?",
             kind="reason_picker", payload={"options": options})


def _write_options_card(session: Session, convo: Conversation, loan: Loan):
    policy = get_policy(session, loan.credit_union_id)
    options = plans.get_options(loan, policy)
    for o in options:
        o["label"] = "Pay in full" if o["plan_type"] == PlanType.FULL.value else f"Split into {len(o['installments'])} payments"
    _add_msg(session, convo.id, "agent", "Here are the options that fit — tap the one that works for you.",
             kind="options_card", payload={"options": options})


def propose_plan(session: Session, convo: Conversation, loan: Loan, plan_type: str) -> PaymentPlan:
    if plan_type not in {t.value for t in PlanType}:
        raise ValueError("unknown plan type")
    key = f"{convo.id}:{plan_type}"
    existing = session.exec(select(PaymentPlan).where(PaymentPlan.idempotency_key == key)).first()
    if existing is not None:
        return existing  # repeated propose returns the same proposed row

    policy = get_policy(session, loan.credit_union_id)
    schedule = plans.generate_schedule(loan.amount_due_cents, loan.due_date, plan_type, policy)
    plan = PaymentPlan(conversation_id=convo.id, loan_id=loan.id, plan_type=plan_type,
                       installment_count=len(schedule), total_cents=loan.amount_due_cents,
                       status=PlanStatus.PROPOSED.value, idempotency_key=key)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    for it in schedule:
        session.add(Installment(plan_id=plan.id, installment_number=it.installment_number,
                                amount_cents=it.amount_cents, due_date=it.due_date))
    payload = {"plan_id": plan.id, "plan_type": plan_type,
               "installments": [{"n": it.installment_number, "amount_cents": it.amount_cents,
                                 "due_date": it.due_date.isoformat()} for it in schedule]}
    _add_msg(session, convo.id, "agent",
             f"Proposed {plan_type} plan: {len(schedule)} payment(s).", kind="plan_summary", payload=payload)
    session.commit()
    return plan


def confirm_plan(session: Session, convo: Conversation, loan: Loan, plan_id: int) -> PaymentPlan:
    plan = session.get(PaymentPlan, plan_id)
    if plan is None or plan.conversation_id != convo.id:
        raise NotFound("Plan not found for this conversation.")
    if plan.status == PlanStatus.CONFIRMED.value:
        return plan  # idempotent
    # One confirmed plan per loan: supersede any other.
    for other in session.exec(select(PaymentPlan).where(PaymentPlan.loan_id == loan.id,
                                                        PaymentPlan.status == PlanStatus.CONFIRMED.value)).all():
        other.status = PlanStatus.SUPERSEDED.value
        session.add(other)
    plan.status = PlanStatus.CONFIRMED.value
    plan.confirmed_at = now_utc()
    session.add(plan)
    convo.payment_choice = PaymentChoice(plan.plan_type).value
    convo.outcome = _PLAN_OUTCOME[plan.plan_type]
    convo.status = "ended"
    convo.ended_at = now_utc()
    session.add(convo)
    session.commit()
    return plan


def _escalate(session: Session, convo: Conversation, loan: Loan, reason: str, closing: str):
    convo.outcome = Outcome.ESCALATED.value
    convo.status = "ended"
    convo.ended_at = now_utc()
    convo.reason_note = convo.reason_note or reason  # keep the escalation reason for staff
    session.add(convo)
    loan.status = "escalated"
    loan.updated_at = now_utc()
    session.add(loan)
    _add_msg(session, convo.id, "agent", closing)


def _end_conversation(session: Session, convo: Conversation, loan: Loan, outcome: str, closing: str):
    convo.outcome = outcome
    convo.status = "ended"
    convo.ended_at = now_utc()
    session.add(convo)
    if outcome == Outcome.DISPUTE.value:
        loan.status = "disputed"
    elif outcome in {Outcome.STOP_REQUEST.value, Outcome.ATTORNEY.value}:
        loan.status = "do_not_contact"
    loan.updated_at = now_utc()
    session.add(loan)
    _add_msg(session, convo.id, "agent", closing)


# --- staff reads (Phase 5) ----------------------------------------------------

def escalations(session: Session) -> list[dict]:
    rows = session.exec(
        select(Conversation).where(Conversation.outcome == Outcome.ESCALATED.value)
        .order_by(Conversation.ended_at.desc())
    ).all()
    out = []
    for convo in rows:
        loan = session.get(Loan, convo.loan_id)
        customer = session.get(Customer, loan.customer_id)
        out.append({
            "conversation_id": convo.id,
            "customer_name": customer.name,
            "amount_due_cents": loan.amount_due_cents,
            "reason": convo.reason_note or convo.reason_code,
            "summary": convo.summary,
            "ended_at": convo.ended_at.isoformat() if convo.ended_at else None,
        })
    return out


def confirmed_plans(session: Session, status: str = "confirmed") -> list[dict]:
    rows = session.exec(select(PaymentPlan).where(PaymentPlan.status == status)
                        .order_by(PaymentPlan.confirmed_at.desc())).all()
    out = []
    for plan in rows:
        loan = session.get(Loan, plan.loan_id)
        customer = session.get(Customer, loan.customer_id)
        insts = session.exec(select(Installment).where(Installment.plan_id == plan.id)
                            .order_by(Installment.installment_number)).all()
        out.append({
            "plan_id": plan.id,
            "customer_name": customer.name,
            "plan_type": plan.plan_type,
            "total_cents": plan.total_cents,
            "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
            "installments": [{"n": i.installment_number, "amount_cents": i.amount_cents,
                              "due_date": i.due_date.isoformat(), "status": i.status} for i in insts],
        })
    return out


# --- reads --------------------------------------------------------------------

def conversation_detail(session: Session, conversation_id: int) -> dict | None:
    convo = session.get(Conversation, conversation_id)
    if convo is None:
        return None
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    rows = session.exec(
        select(Message).where(Message.conversation_id == convo.id).order_by(Message.created_at, Message.id)
    ).all()
    plan = _confirmed_plan(session, loan.id)
    plan_out = None
    if plan:
        insts = session.exec(select(Installment).where(Installment.plan_id == plan.id)
                             .order_by(Installment.installment_number)).all()
        plan_out = {"plan_id": plan.id, "plan_type": plan.plan_type, "status": plan.status,
                    "installments": [{"n": i.installment_number, "amount_cents": i.amount_cents,
                                      "due_date": i.due_date.isoformat(), "status": i.status} for i in insts]}
    return {
        "conversation_id": convo.id,
        "loan": {"loan_id": loan.id, "name": customer.name, "amount_due_cents": loan.amount_due_cents,
                 "due_date": loan.due_date.isoformat(), "status": loan.status},
        "status": convo.status,
        "outcome": convo.outcome,
        "ended": convo.status == "ended",
        "summary": convo.summary,
        "reason_code": convo.reason_code,
        "payment_choice": convo.payment_choice,
        "verified_at": convo.verified_at.isoformat() if convo.verified_at else None,
        "messages": [{"id": m.id, "role": m.role, "text": m.text, "kind": m.kind, "payload": m.payload} for m in rows],
        "confirmed_plan": plan_out,
    }
