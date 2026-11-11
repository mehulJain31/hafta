"""Database tables (SQLModel) for CloveFi.

credit_unions ─1:N─> cu_policies
customers ─1:N─> loans ─1:N─> conversations ─1:N─> messages
                   │                 │
                   │                 └─1:N─> payment_plans ─1:N─> installments
                   │
                   └─1:N─> contact_attempts   (ledger; kept for future outbound)

Money is **integer cents** everywhere — never a float. Timestamps are tz-aware
UTC. String columns hold values from `enums.py`.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from db import now_utc
from enums import InstallmentStatus, Outcome, PaymentChoice, PlanStatus


class CreditUnion(SQLModel, table=True):
    __tablename__ = "credit_unions"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    timezone: str = "America/Los_Angeles"  # IANA; borrower-local for FDCPA hours
    pay_portal_url: Optional[str] = None
    created_at: datetime = Field(default_factory=now_utc)


class CuPolicy(SQLModel, table=True):
    """One row per credit union (later: per loan product). The only arrangements
    the backend may build come from here — see plans.get_options."""

    __tablename__ = "cu_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    credit_union_id: int = Field(foreign_key="credit_unions.id", index=True)
    allowed_plan_types: list = Field(sa_column=Column(JSON))        # e.g. ["FULL","SPLIT"]
    max_installments: int = 4
    installment_interval: str = "monthly"                          # only value for now
    max_extension_days: int = 0                                    # 0 = extensions off
    min_installment_cents: int = 2500
    auto_escalate_reasons: list = Field(sa_column=Column(JSON))    # e.g. ["BANKRUPTCY"]
    first_payment_rule: str = "on_due_date"


class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone_number: str = Field(unique=True, index=True)  # normalized to digits
    email: Optional[str] = None
    timezone: str = "America/Los_Angeles"  # IANA name, for display / FDCPA hours
    created_at: datetime = Field(default_factory=now_utc)


class Loan(SQLModel, table=True):
    __tablename__ = "loans"

    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customers.id", index=True)
    credit_union_id: int = Field(default=1, foreign_key="credit_unions.id", index=True)
    amount_due_cents: int                       # current balance due, in cents
    due_date: date
    external_loan_ref: Optional[str] = None     # the CU core's loan number (payments feed)
    # in_collections | disputed | do_not_contact | resolved | escalated
    status: str = Field(default="in_collections", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    loan_id: int = Field(foreign_key="loans.id", index=True)
    channel: str = "web_chat"
    status: str = "open"  # open | ended
    outcome: str = Field(default=Outcome.IN_PROGRESS.value, index=True)
    summary: str = ""                                  # for staff; not fed into the next prompt
    reason_code: Optional[str] = None                  # ReasonCode, once captured
    reason_note: Optional[str] = None                  # free text (OTHER); never used for logic
    payment_choice: str = PaymentChoice.UNDECIDED.value  # set only by confirm_plan
    verified_at: Optional[datetime] = None             # identity verification (stub in MVP)
    verify_attempts: int = 0                            # failed identity attempts (lock at 2)
    started_at: datetime = Field(default_factory=now_utc)
    ended_at: Optional[datetime] = None


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # agent | borrower
    text: str
    kind: str = "text"  # text | reason_picker | options_card | plan_summary
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=now_utc)


class PaymentPlan(SQLModel, table=True):
    """Replaces promised_payments. Rows are never deleted or rewritten; a new
    confirmed plan supersedes the prior one."""

    __tablename__ = "payment_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    loan_id: int = Field(foreign_key="loans.id", index=True)
    plan_type: str                                     # FULL | SPLIT
    installment_count: int                             # 1 for FULL
    total_cents: int                                   # must equal loan.amount_due_cents at creation
    status: str = Field(default=PlanStatus.PROPOSED.value, index=True)  # proposed|confirmed|superseded|cancelled
    idempotency_key: str = Field(unique=True, index=True)
    proposed_at: datetime = Field(default_factory=now_utc)
    confirmed_at: Optional[datetime] = None


class Installment(SQLModel, table=True):
    """Immutable once the parent plan is confirmed."""

    __tablename__ = "installments"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="payment_plans.id", index=True)
    installment_number: int                            # 1-based
    amount_cents: int
    due_date: date = Field(index=True)
    status: str = Field(default=InstallmentStatus.SCHEDULED.value, index=True)  # SCHEDULED|PAID|PAST_DUE
    paid_at: Optional[datetime] = None


class ContactAttempt(SQLModel, table=True):
    """One outreach attempt — the ledger for Regulation F frequency limits.
    Kept intact for future outbound SMS/voice; nothing blocks on it today."""

    __tablename__ = "contact_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    loan_id: int = Field(foreign_key="loans.id", index=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversations.id")
    channel: str = "web_chat"           # web_chat | phone_call | sms | email
    attempted_at: datetime = Field(default_factory=now_utc, index=True)
    had_conversation: bool = False
    result: str = "opened"              # opened | connected | no_answer | voicemail | delivered
    created_at: datetime = Field(default_factory=now_utc)
