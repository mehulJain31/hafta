"""Database tables (SQLModel) for persisted collections chats.

customers 1─* loans 1─* conversations 1─* messages
                                   └─* promised_payments

Identity: customers are keyed by normalized phone; a customer has one open loan
in the demo (see store.py). amount_due is mutable data, never part of identity.
"""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from db import now_utc


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
    amount_due: float
    due_date: date
    # in_collections | disputed | do_not_contact | resolved
    status: str = Field(default="in_collections", index=True)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    loan_id: int = Field(foreign_key="loans.id", index=True)
    channel: str = "web_chat"
    status: str = "open"  # open | ended
    outcome: str = Field(default="in_progress", index=True)
    summary: str = ""
    missed_payment_reason: Optional[str] = None
    started_at: datetime = Field(default_factory=now_utc)
    ended_at: Optional[datetime] = None


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # agent | borrower
    text: str
    created_at: datetime = Field(default_factory=now_utc)


class PromisedPayment(SQLModel, table=True):
    __tablename__ = "promised_payments"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    loan_id: int = Field(foreign_key="loans.id", index=True)
    due_date: date = Field(index=True)
    amount: float
    status: str = "promised"  # promised | paid | missed
    created_at: datetime = Field(default_factory=now_utc)
