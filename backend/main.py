"""CloveFi API. The server owns state and builds every payment plan; Claude only
explains, classifies the reason, and confirms. Money crosses the boundary as a
decimal and is stored as integer cents."""

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # must run before agent.py creates the Anthropic client

from fastapi import Body, Depends, FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402
from sqlmodel import Session  # noqa: E402

import agent  # noqa: E402
import db  # noqa: E402
import payments  # noqa: E402
import store  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.create_db_and_tables()
    yield


app = FastAPI(title="CloveFi", lifespan=lifespan)


def _cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class LoanRequest(BaseModel):
    name: str
    phone: str
    amount_due: Decimal = Field(gt=0)  # dollars; converted to cents at the boundary
    due_date: date

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 100:
            raise ValueError("Enter the borrower's name")
        return v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if not 7 <= len(digits) <= 15:
            raise ValueError("Enter a valid phone number")
        return v.strip()


class SessionRequest(BaseModel):
    loan_id: int


class VerifyRequest(BaseModel):
    conversation_id: int
    answer: str = Field(min_length=1, max_length=100)


class ReplyRequest(BaseModel):
    conversation_id: int
    text: str = Field(min_length=1, max_length=2000)


class ReasonRequest(BaseModel):
    conversation_id: int
    reason_code: str
    note: Optional[str] = Field(default=None, max_length=500)


class ChooseRequest(BaseModel):
    conversation_id: int
    plan_type: str


class ConfirmRequest(BaseModel):
    conversation_id: int
    plan_id: int


def _handle(fn, *args):
    """Run a store call, mapping its exceptions to HTTP."""
    try:
        return fn(*args)
    except store.ContactBlocked as e:
        raise HTTPException(409, e.reason)
    except store.Conflict as e:
        raise HTTPException(409, str(e))
    except store.NotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except agent.ClovefiError as e:
        raise HTTPException(502, str(e))


@app.get("/api/config")
def config():
    return {"lender_name": agent.LENDER_NAME, "agent_name": agent.AGENT_NAME}


@app.get("/api/loans")
def list_loans(status: str = "in_collections", session: Session = Depends(db.get_session)):
    return {"loans": store.loans_due(session, status)}


@app.post("/api/loans")
def create_loan(req: LoanRequest, session: Session = Depends(db.get_session)):
    loan = store.create_loan(session, req.name, req.phone, _cents(req.amount_due), req.due_date)
    return {"loan_id": loan.id}


@app.post("/api/sessions")
def open_session(req: SessionRequest, session: Session = Depends(db.get_session)):
    return _handle(store.open_session, session, req.loan_id)


@app.post("/api/verify")
def verify(req: VerifyRequest, session: Session = Depends(db.get_session)):
    return _handle(store.verify, session, req.conversation_id, req.answer)


@app.post("/api/reply")
def reply(req: ReplyRequest, session: Session = Depends(db.get_session)):
    return _handle(store.reply, session, req.conversation_id, req.text)


@app.post("/api/reason")
def reason(req: ReasonRequest, session: Session = Depends(db.get_session)):
    return _handle(store.pick_reason, session, req.conversation_id, req.reason_code, req.note)


@app.post("/api/choose")
def choose(req: ChooseRequest, session: Session = Depends(db.get_session)):
    return _handle(store.choose_option, session, req.conversation_id, req.plan_type)


@app.post("/api/confirm")
def confirm(req: ConfirmRequest, session: Session = Depends(db.get_session)):
    return _handle(store.confirm, session, req.conversation_id, req.plan_id)


@app.get("/api/escalations")
def escalations(session: Session = Depends(db.get_session)):
    return {"escalations": store.escalations(session)}


@app.get("/api/plans")
def plans_list(status: str = "confirmed", session: Session = Depends(db.get_session)):
    return {"plans": store.confirmed_plans(session, status)}


@app.post("/api/payments/import")
def import_payments(csv: str = Body(..., embed=True), session: Session = Depends(db.get_session)):
    return payments.import_csv(session, csv)


@app.post("/api/installments/mark-past-due")
def mark_past_due(session: Session = Depends(db.get_session)):
    return payments.mark_past_due(session)


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int, session: Session = Depends(db.get_session)):
    detail = store.conversation_detail(session, conversation_id)
    if detail is None:
        raise HTTPException(404, "Conversation not found.")
    return detail
