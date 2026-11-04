"""Persistence logic for collections chats.

Keeps main.py thin: all reads/writes against the DB live here. The server owns
the transcript — history is rebuilt from the messages table, never trusted from
the client.
"""

import os
from datetime import date

from sqlmodel import Session, select

import agent
from db import now_utc
from models import Conversation, Customer, Loan, Message, PromisedPayment

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "America/Los_Angeles")

# Loan statuses that mean "don't start another chat".
_BLOCKED_LOAN_STATUS = {"do_not_contact"}
# Outcomes of a prior conversation that forbid re-contact (FDCPA 805).
_BLOCKING_OUTCOMES = {"stop_request", "attorney"}


class ContactBlocked(Exception):
    """Raised when a loan must not be contacted again (opt-out or attorney)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def normalize_phone(phone: str) -> str:
    """Canonical digits so the same number entered differently matches.

    US-focused for the demo: a leading country-code '1' on an 11-digit number is
    dropped so '+1 (555) 123-4567' and '555-123-4567' are one customer. A real
    system would store full E.164 and normalize per the borrower's country.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _open_loan(session: Session, customer_id: int) -> Loan | None:
    """The customer's current loan (one open loan per customer in the demo)."""
    return session.exec(
        select(Loan)
        .where(Loan.customer_id == customer_id, Loan.status != "resolved")
        .order_by(Loan.created_at.desc())
    ).first()


def _latest_conversation(session: Session, loan_id: int) -> Conversation | None:
    return session.exec(
        select(Conversation)
        .where(Conversation.loan_id == loan_id)
        .order_by(Conversation.started_at.desc())
    ).first()


def prior_context(session: Session, loan: Loan, exclude_conversation_id: int | None = None) -> str | None:
    """Summary + still-owed promises from the loan's most recent *other* conversation.

    None on first contact. Fed into Richie's prompt so he remembers last time. Any
    status counts — a conversation that ended in an agreed plan stays 'open', and
    it's still the borrower's last decision.
    """
    query = select(Conversation).where(Conversation.loan_id == loan.id)
    if exclude_conversation_id is not None:
        query = query.where(Conversation.id != exclude_conversation_id)
    prev = session.exec(query.order_by(Conversation.started_at.desc())).first()
    if prev is None:
        return None

    parts = []
    if prev.summary:
        parts.append(prev.summary)
    open_promises = session.exec(
        select(PromisedPayment)
        .where(PromisedPayment.loan_id == loan.id, PromisedPayment.status == "promised")
        .order_by(PromisedPayment.due_date)
    ).all()
    for p in open_promises:
        overdue = " (now overdue)" if p.due_date < date.today() else ""
        parts.append(f"Promised ${p.amount:,.2f} on {p.due_date.isoformat()}{overdue}, not yet recorded as paid.")
    return " ".join(parts) if parts else None


def start_conversation(session: Session, name: str, phone: str, amount_due: float, due_date: date) -> dict:
    """Upsert customer by phone, find/refresh the open loan, open a conversation.

    Returns {conversation_id, message, prior_context}. Raises ContactBlocked.
    """
    digits = normalize_phone(phone)
    customer = session.exec(select(Customer).where(Customer.phone_number == digits)).first()
    if customer is None:
        customer = Customer(name=name, phone_number=digits, timezone=DEFAULT_TIMEZONE)
        session.add(customer)
        session.commit()
        session.refresh(customer)
    elif customer.name != name:
        customer.name = name  # keep the latest spelling the operator entered
        session.add(customer)

    loan = _open_loan(session, customer.id)
    if loan is None:
        loan = Loan(customer_id=customer.id, amount_due=amount_due, due_date=due_date)
        session.add(loan)
        session.commit()
        session.refresh(loan)
    else:
        if loan.status in _BLOCKED_LOAN_STATUS:
            raise ContactBlocked("This borrower has asked not to be contacted, or is represented by an attorney.")
        last = _latest_conversation(session, loan.id)
        if last and last.outcome in _BLOCKING_OUTCOMES:
            raise ContactBlocked("This borrower has asked not to be contacted, or is represented by an attorney.")
        loan.amount_due = amount_due  # refresh to what the operator entered now
        loan.due_date = due_date
        loan.updated_at = now_utc()
        session.add(loan)

    context = prior_context(session, loan)

    convo = Conversation(loan_id=loan.id)
    session.add(convo)
    session.commit()
    session.refresh(convo)

    opener = agent.opening_message(customer.name, loan.amount_due, loan.due_date)
    session.add(Message(conversation_id=convo.id, role="agent", text=opener))
    session.commit()

    return {
        "conversation_id": convo.id,
        "message": {"role": "agent", "text": opener},
        "prior_context": context,
    }


def _history(session: Session, conversation_id: int) -> list[dict]:
    rows = session.exec(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at, Message.id)
    ).all()
    return [{"role": m.role, "text": m.text} for m in rows]


def record_turn(session: Session, convo: Conversation, borrower_text: str) -> dict:
    """Save the borrower message, get Richie's reply, persist outcome + promises."""
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)

    session.add(Message(conversation_id=convo.id, role="borrower", text=borrower_text))
    session.commit()

    history = _history(session, convo.id)
    context = prior_context(session, loan, exclude_conversation_id=convo.id)
    turn = agent.reply(customer.name, loan.amount_due, loan.due_date, history, context)

    session.add(Message(conversation_id=convo.id, role="agent", text=turn["reply"]))

    convo.outcome = turn["outcome"]
    convo.summary = turn.get("summary", "")
    convo.missed_payment_reason = turn.get("missed_payment_reason")
    if turn["ended"]:
        convo.status = "ended"
        convo.ended_at = now_utc()
    session.add(convo)

    # Replace this conversation's promised payments with the latest agreed set.
    for p in session.exec(select(PromisedPayment).where(PromisedPayment.conversation_id == convo.id)).all():
        session.delete(p)
    if turn["outcome"] in {"promise_to_pay", "payment_plan", "extension"} and not turn["policy_issues"]:
        for p in turn["payments"]:
            try:
                pay_date = date.fromisoformat(p["date"])
            except (ValueError, KeyError):
                continue
            session.add(PromisedPayment(
                conversation_id=convo.id, loan_id=loan.id, due_date=pay_date, amount=p["amount"],
            ))

    # Reflect the outcome on the loan so a future chat is blocked / routed correctly.
    if turn["outcome"] == "dispute":
        loan.status = "disputed"
    elif turn["outcome"] in _BLOCKING_OUTCOMES:
        loan.status = "do_not_contact"
    loan.updated_at = now_utc()
    session.add(loan)

    session.commit()
    return turn


def conversation_detail(session: Session, conversation_id: int) -> dict | None:
    convo = session.get(Conversation, conversation_id)
    if convo is None:
        return None
    loan = session.get(Loan, convo.loan_id)
    customer = session.get(Customer, loan.customer_id)
    messages = _history(session, convo.id)
    promises = session.exec(
        select(PromisedPayment).where(PromisedPayment.conversation_id == convo.id).order_by(PromisedPayment.due_date)
    ).all()
    return {
        "conversation_id": convo.id,
        "loan": {"name": customer.name, "amount_due": loan.amount_due, "due_date": loan.due_date.isoformat()},
        "status": convo.status,
        "outcome": convo.outcome,
        "summary": convo.summary,
        "missed_payment_reason": convo.missed_payment_reason,
        "ended": convo.status == "ended",
        "messages": messages,
        "payments": [{"date": p.due_date.isoformat(), "amount": p.amount} for p in promises],
    }
