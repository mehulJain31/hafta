"""Richie's instructions and the call to Claude."""

import json
import os
from datetime import date

import anthropic

import policies

MODEL = os.getenv("CLOVEFI_MODEL", "claude-opus-5-5")
LENDER_NAME = os.getenv("LENDER_NAME", "your lender")
AGENT_NAME = "Richie"

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

OUTCOMES = [
    "in_progress",        # still talking
    "promise_to_pay",     # full amount by the due date
    "payment_plan",       # split payments within policy
    "extension",          # one full payment within the extension window
    "hardship_referral",  # needs more than policy allows; lender's team follows up
    *sorted(policies.ENDING_OUTCOMES),
]

# Claude returns this JSON with every reply.
TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "The text message to send to the borrower."},
        "outcome": {"type": "string", "enum": OUTCOMES},
        "payments": {
            "type": "array",
            "description": "Payments the borrower has agreed to so far (date YYYY-MM-DD, amount in dollars). Empty if none.",
            "items": {
                "type": "object",
                "properties": {"date": {"type": "string"}, "amount": {"type": "number"}},
                "required": ["date", "amount"],
                "additionalProperties": False,
            },
        },
        "missed_payment_reason": {
            "type": ["string", "null"],
            "description": "Short summary of why the borrower can't pay on time, if they said. Null otherwise.",
        },
        "summary": {
            "type": "string",
            "description": "One short sentence summarizing where the conversation stands and what was decided, for a human reviewing later. E.g. 'Agreed to a plan: $150 on Feb 2 and $300 on Feb 20.' or 'Disputed the debt, says it was already paid.'",
        },
    },
    "required": ["reply", "outcome", "payments", "missed_payment_reason", "summary"],
    "additionalProperties": False,
}


def first_name(name: str) -> str:
    return name.split()[0]


def opening_message(name: str, amount_due: float, due_date: date) -> str:
    amount = f"${amount_due:,.2f}"
    when = due_date.strftime("%B %-d, %Y")
    if due_date < date.today():
        status = f"was due on {when} and is still outstanding"
    elif due_date == date.today():
        status = "is due today"
    else:
        status = f"is due on {when}"
    # FDCPA 807(11): the first message must say this is an attempt to collect a debt.
    # Reg F 1006.6(e): electronic messages need a simple way to opt out.
    return (
        f"Hi {first_name(name)}, this is {AGENT_NAME}, an automated assistant with {LENDER_NAME}. "
        "This is an attempt to collect a debt, and any information obtained will be used for that purpose. "
        f"Your payment of {amount} {status}. When will you be able to pay? Reply STOP to opt out."
    )


def _system_prompt(name: str, amount_due: float, due_date: date, prior_context: str | None = None) -> str:
    today = date.today()
    days_past_due = (today - due_date).days
    status = (
        f"{days_past_due} days past due" if days_past_due > 0
        else "due today" if days_past_due == 0
        else f"due in {-days_past_due} days"
    )
    history_block = ""
    if prior_context:
        history_block = (
            f"\nWhat happened last time you spoke with {first_name(name)} (reference it naturally if relevant, "
            f"e.g. a promise they made or missed; don't re-litigate a closed dispute):\n{prior_context}\n"
        )
    return f"""You are {AGENT_NAME}, an automated collections assistant texting a borrower for {LENDER_NAME}, their auto lender.
{history_block}

Loan facts (the only facts you know):
- Borrower name: {name} (use their first name, {first_name(name)}, now and then, not in every message)
- Lender: {LENDER_NAME}
- Amount due: ${amount_due:,.2f}
- Due date: {due_date.isoformat()} ({status})
- Today: {today.isoformat()} ({today.strftime('%A')})

{policies.FDCPA_RULES}

Your goal: agree on a specific plan to pay the full amount, then confirm it back with exact dates and amounts.

When the borrower can't pay on time (the loan is past due, or they offer a date after the due date):
1. Note that their date is after the due date, and kindly ask what's making it hard to pay on time. Show understanding for their reason; don't judge it.
2. Mention once that payments not made on time may be reported and could affect their credit score.
3. Ask whether they can pay some or all of it by the due date.
4. If they can't, offer the options below that fit their situation, and help them pick specific dates and amounts.

{policies.payment_options_text(amount_due, due_date, today)}

How to talk:
- Write like a text message: short and plain, one to three sentences. No markdown.
- Be warm, calm and respectful, and keep gently steering back to a payment plan.
- Turn vague answers ("next week", "soon", "when I get paid") into a specific date and amount by asking.
- Never invent payment links, phone numbers or account numbers. If they ask how to pay, say {LENDER_NAME} will send payment instructions.

Output: return JSON with your reply and the outcome so far.
- outcome is in_progress until a plan is agreed or the conversation must end.
- Use promise_to_pay, payment_plan or extension only once the borrower has agreed to specific dates and amounts that add up to the full amount and fit the policy above. List those payments in "payments".
- After an ending outcome (dispute, stop_request, attorney, wrong_person, escalated), the conversation is over."""


def check_payments(outcome: str, payments: list[dict], amount_due: float, due_date: date) -> list[str]:
    """Double-check an agreed plan against the lender's policy. Returns problems found."""
    if outcome not in {"promise_to_pay", "payment_plan", "extension"}:
        return []
    problems = []
    try:
        dates = [date.fromisoformat(p["date"]) for p in payments]
    except ValueError:
        return ["Agreed payment dates aren't valid dates."]
    total = sum(p["amount"] for p in payments)
    if not payments:
        problems.append("No payment dates were recorded.")
    elif abs(total - amount_due) > 0.01:
        problems.append(f"Agreed payments add up to ${total:,.2f}, not ${amount_due:,.2f}.")
    split_by, extend_by = policies.deadlines(due_date, date.today())
    latest = max(dates, default=due_date)
    if outcome == "promise_to_pay" and latest > max(due_date, date.today()):
        problems.append("Promise to pay is after the due date.")
    if outcome == "payment_plan":
        if len(payments) > policies.MAX_SPLIT_PAYMENTS:
            problems.append(f"Plan has {len(payments)} payments; the limit is {policies.MAX_SPLIT_PAYMENTS}.")
        if latest > split_by:
            problems.append(f"Last payment is after the plan deadline ({split_by.isoformat()}).")
    if outcome == "extension" and (len(payments) != 1 or latest > extend_by):
        problems.append(f"Extension must be one payment on or before {extend_by.isoformat()}.")
    return problems


class ClovefiError(Exception):
    pass


def _stop_turn() -> dict:
    """Deterministic reply to an opt-out keyword; Claude isn't called (FDCPA 805(c))."""
    return {
        "reply": f"You've been opted out. {LENDER_NAME} won't send you any more messages through this chat.",
        "outcome": "stop_request",
        "payments": [],
        "missed_payment_reason": None,
        "summary": "Borrower sent an opt-out keyword; no further contact through this chat.",
    }


def reply(name: str, amount_due: float, due_date: date, messages: list[dict],
          prior_context: str | None = None) -> dict:
    """messages: [{"role": "agent" | "borrower", "text": str}], starting with Richie's opener.

    Returns {"reply", "outcome", "payments", "missed_payment_reason", "summary", "ended", "policy_issues"}.
    """
    last = messages[-1]["text"].strip().lower().strip(".!")
    if last in policies.STOP_WORDS:
        turn = _stop_turn()
    else:
        turn = _ask_claude(name, amount_due, due_date, messages, prior_context)

    turn["ended"] = turn["outcome"] in policies.ENDING_OUTCOMES
    turn["policy_issues"] = check_payments(turn["outcome"], turn["payments"], amount_due, due_date)
    return turn


def _ask_claude(name: str, amount_due: float, due_date: date, messages: list[dict],
                prior_context: str | None = None) -> dict:
    # Claude's history must start with a user turn, so a placeholder comes before Richie's opener.
    history = [{"role": "user", "content": f"[Conversation started. {AGENT_NAME} texts the borrower first.]"}]
    for m in messages:
        history.append({
            "role": "assistant" if m["role"] == "agent" else "user",
            "content": m["text"],
        })

    try:
        response = _client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": TURN_SCHEMA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=_system_prompt(name, amount_due, due_date, prior_context),
            messages=history,
        )
    except TypeError as e:  # SDK raises this when no credentials are configured at all
        raise ClovefiError("No Anthropic API key found. Set ANTHROPIC_API_KEY in backend/.env.") from e
    except anthropic.AuthenticationError as e:
        raise ClovefiError("Anthropic API key is missing or invalid.") from e
    except anthropic.RateLimitError as e:
        raise ClovefiError("Rate limited by Anthropic. Try again shortly.") from e
    except anthropic.APIStatusError as e:
        raise ClovefiError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ClovefiError("Couldn't reach the Claude API.") from e

    if response.stop_reason == "refusal":
        raise ClovefiError("Claude declined to reply to this message.")
    if response.stop_reason == "max_tokens":
        raise ClovefiError("Claude's reply was cut off.")

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        turn = json.loads(text)
    except json.JSONDecodeError as e:
        raise ClovefiError("Claude returned a reply in an unexpected format.") from e
    if not turn.get("reply", "").strip():
        raise ClovefiError("Claude returned an empty reply.")
    return turn
