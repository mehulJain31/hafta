"""Clovefi API. The server owns state: chats persist in the database (see store.py)."""

from contextlib import asynccontextmanager
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # must run before agent.py creates the Anthropic client

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402
from sqlmodel import Session  # noqa: E402

import agent  # noqa: E402
import db  # noqa: E402
import store  # noqa: E402
from models import Conversation  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.create_db_and_tables()
    yield


app = FastAPI(title="Clovefi", lifespan=lifespan)


class StartRequest(BaseModel):
    name: str
    phone: str
    amount_due: float = Field(gt=0)
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


class ReplyRequest(BaseModel):
    conversation_id: int
    text: str = Field(min_length=1, max_length=2000)


@app.get("/api/config")
def config():
    return {"lender_name": agent.LENDER_NAME, "agent_name": agent.AGENT_NAME}


@app.post("/api/start")
def start(req: StartRequest, session: Session = Depends(db.get_session)):
    try:
        return store.start_conversation(session, req.name, req.phone, req.amount_due, req.due_date)
    except store.ContactBlocked as e:
        raise HTTPException(409, e.reason)


@app.post("/api/reply")
def reply(req: ReplyRequest, session: Session = Depends(db.get_session)):
    convo = session.get(Conversation, req.conversation_id)
    if convo is None:
        raise HTTPException(404, "Conversation not found.")
    if convo.status == "ended":
        raise HTTPException(409, "This conversation has ended.")
    try:
        turn = store.record_turn(session, convo, req.text)
    except agent.ClovefiError as e:
        raise HTTPException(502, str(e))
    return {
        "message": {"role": "agent", "text": turn["reply"]},
        "outcome": turn["outcome"],
        "payments": turn["payments"],
        "missed_payment_reason": turn["missed_payment_reason"],
        "ended": turn["ended"],
        "policy_issues": turn["policy_issues"],
    }


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int, session: Session = Depends(db.get_session)):
    detail = store.conversation_detail(session, conversation_id)
    if detail is None:
        raise HTTPException(404, "Conversation not found.")
    return detail
