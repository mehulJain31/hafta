"""Hafta v0 API. Stateless: the browser sends the whole chat on each reply."""

from datetime import date
from typing import Literal

from dotenv import load_dotenv

load_dotenv()  # must run before agent.py creates the Anthropic client

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

import agent  # noqa: E402

app = FastAPI(title="Hafta")


class Loan(BaseModel):
    name: str
    amount_due: float = Field(gt=0)
    due_date: date

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 100:
            raise ValueError("Enter the borrower's name")
        return v


class Message(BaseModel):
    role: Literal["hafta", "borrower"]
    text: str = Field(min_length=1, max_length=2000)


class ReplyRequest(BaseModel):
    loan: Loan
    messages: list[Message] = Field(min_length=2, max_length=100)


@app.get("/api/config")
def config():
    return {"lender_name": agent.LENDER_NAME, "agent_name": agent.AGENT_NAME}


@app.post("/api/start")
def start(loan: Loan):
    return {"message": {"role": "hafta", "text": agent.opening_message(loan.name, loan.amount_due, loan.due_date)}}


@app.post("/api/reply")
def reply(req: ReplyRequest):
    if req.messages[-1].role != "borrower":
        raise HTTPException(400, "The last message must be from the borrower.")
    try:
        turn = agent.reply(
            req.loan.name, req.loan.amount_due, req.loan.due_date,
            [m.model_dump() for m in req.messages],
        )
    except agent.HaftaError as e:
        raise HTTPException(502, str(e))
    return {
        "message": {"role": "hafta", "text": turn["reply"]},
        "outcome": turn["outcome"],
        "payments": turn["payments"],
        "missed_payment_reason": turn["missed_payment_reason"],
        "ended": turn["ended"],
        "policy_issues": turn["policy_issues"],
    }
