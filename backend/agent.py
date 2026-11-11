"""Richie: the system prompt and the Claude tool-use loop.

Design principle: **code builds the plan; Claude explains, classifies and
confirms.** Richie never emits a dollar amount or a date for a payment plan —
installment numbers come only from `plans.generate_schedule`, surfaced as
structured cards. Richie drives the conversation by calling tools; deterministic
handlers (in `store.py`) do the work and persist it.
"""

import json
import os
from datetime import date

import anthropic

import policies
from enums import values, ReasonCode

MODEL = os.getenv("CLOVEFI_MODEL", "claude-opus-5-5")
LENDER_NAME = os.getenv("LENDER_NAME", "your lender")
AGENT_NAME = "Richie"

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


class ClovefiError(Exception):
    pass


def first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def opening_message(name: str) -> str:
    # FDCPA 807(11): the first message must say this is an attempt to collect a debt.
    # Reg F 1006.6(e): electronic messages need a simple way to opt out.
    # Identity is verified BEFORE any account detail (incl. the amount) is shared.
    return (
        f"Hi {first_name(name)}, this is {AGENT_NAME}, an automated assistant with {LENDER_NAME}. "
        "This is an attempt to collect a debt, and any information obtained will be used for that purpose. "
        "Before I share any account details, can you confirm the last four digits of the phone number on file? "
        "Reply STOP to opt out."
    )


# --- Tools Claude may call -----------------------------------------------------
TOOLS = [
    {
        "name": "show_reason_picker",
        "description": (
            "Show the borrower tappable chips to say why they can't pay in full. Call this as soon as the "
            "borrower indicates they can't pay the whole amount by the due date. Ends your turn; the app shows the chips."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_options",
        "description": (
            "Fetch and show the payment arrangements the credit union allows for this loan, as tappable cards. "
            "Call this only after a reason has been recorded. Ends your turn; the app shows the options."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "escalate",
        "description": "Hand the conversation to the lender's team for something you can't handle. Ends the conversation.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "enum": ["BANKRUPTCY", "DECEASED", "COMPLAINT", "OTHER"]}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "end_conversation",
        "description": (
            "End the conversation when the law requires stopping: a dispute, an opt-out, an attorney, or a wrong person."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"outcome": {"type": "string", "enum": ["dispute", "stop_request", "attorney", "wrong_person"]}},
            "required": ["outcome"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_summary",
        "description": "Record a one-line summary of the conversation for staff. Does not end your turn.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
]
TERMINAL_TOOLS = {"show_reason_picker", "get_options", "escalate", "end_conversation"}


def _system_prompt(name: str, amount_due_cents: int, due_date: date, context: dict | None) -> str:
    today = date.today()
    days = (today - due_date).days
    status = (f"{days} days past due" if days > 0 else "due today" if days == 0 else f"due in {-days} days")
    history_block = ""
    if context:
        history_block = (
            "\nWhat you know from past conversations with this borrower (JSON; reference it naturally, "
            "don't re-litigate a closed dispute):\n" + json.dumps(context) + "\n"
        )
    return f"""You are {AGENT_NAME}, an automated collections assistant for {LENDER_NAME}, a credit union, texting a member about a past-due loan.
{history_block}
Loan facts you may state (these come from the loan record — you may repeat them exactly):
- Member's name: {name} (use their first name, {first_name(name)}, now and then)
- Amount due: {money(amount_due_cents)}
- Due date: {due_date.isoformat()} ({status})
- Today: {today.isoformat()} ({today.strftime('%A')})

{policies.FDCPA_RULES}

How the conversation works — you do NOT make up any payment amounts or dates:
- The member has already been greeted and has verified their identity. State the amount owed and the due date (the facts above), and ask when they can pay.
- If the member says they can't pay the full amount by the due date, call show_reason_picker. Do not ask them to type a reason or propose a plan yourself.
- After a reason is on record, call get_options. The app computes and shows the only arrangements allowed; you never invent installment amounts or dates.
- The member taps an option and confirms in the app. You don't compute or state those numbers — the cards do.
- If they ask how to pay, say {LENDER_NAME} will send payment instructions. Never invent links, phone numbers or account numbers.

When you must stop (call the matching tool, send one short closing line, ask for nothing):
- Dispute (doesn't owe it / wrong amount / already paid / not theirs) → end_conversation outcome=dispute. Say the dispute is noted, {LENDER_NAME} will send written verification, and collection is paused.
- Asks to stop / refuses to pay → end_conversation outcome=stop_request.
- Has an attorney for this debt → end_conversation outcome=attorney.
- You're talking to someone who isn't the member → end_conversation outcome=wrong_person; reveal no details.
- Bankruptcy, a death, or a complaint, or anything you can't handle → escalate with the matching reason.

Style: short, plain text messages, one to three sentences, no markdown. Warm, calm, respectful, never pushy.
Before an ending or escalation, you may call set_summary with a one-line recap for staff.
Reason codes the app uses: {', '.join(values(ReasonCode))}."""


def _to_claude_messages(history: list[dict]) -> list[dict]:
    # Claude's history must start with a user turn.
    msgs = [{"role": "user", "content": f"[Conversation started. {AGENT_NAME} texts the member first.]"}]
    for m in history:
        msgs.append({"role": "assistant" if m["role"] == "agent" else "user", "content": m["text"]})
    return msgs


def _create(system: str, messages: list[dict], tools: list | None):
    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        messages=messages,
    )
    if tools:
        kwargs["tools"] = tools
    try:
        return _client.beta.messages.create(**kwargs)
    except TypeError as e:
        raise ClovefiError("No Anthropic API key found. Set ANTHROPIC_API_KEY in backend/.env.") from e
    except anthropic.AuthenticationError as e:
        raise ClovefiError("Anthropic API key is missing or invalid.") from e
    except anthropic.RateLimitError as e:
        raise ClovefiError("Rate limited by Anthropic. Try again shortly.") from e
    except anthropic.APIStatusError as e:
        raise ClovefiError(f"Claude API error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ClovefiError("Couldn't reach the Claude API.") from e


def run_turn(name: str, amount_due_cents: int, due_date: date, history: list[dict],
             context: dict | None = None) -> dict:
    """Richie's next turn. Returns {text, tool, tool_args, summary}.

    `text` is Richie's message (or None). `tool` is a terminal tool the caller
    must act on (show_reason_picker | get_options | escalate | end_conversation)
    or None. `summary` is the latest set_summary value, if any.
    """
    system = _system_prompt(name, amount_due_cents, due_date, context)
    messages = _to_claude_messages(history)
    narration: list[str] = []
    summary: str | None = None

    for _ in range(6):
        resp = _create(system, messages, TOOLS)
        if resp.stop_reason == "refusal":
            raise ClovefiError("Claude declined to reply to this message.")
        narration += [b.text for b in resp.content if b.type == "text" and b.text.strip()]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            return {"text": " ".join(narration).strip() or None, "tool": None, "tool_args": {}, "summary": summary}

        messages.append({"role": "assistant", "content": resp.content})
        terminal = None
        results = []
        for tu in tool_uses:
            if tu.name == "set_summary":
                summary = (tu.input or {}).get("summary", "")
            elif tu.name in TERMINAL_TOOLS:
                terminal = (tu.name, tu.input or {})
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "ok"})
        if terminal is not None:
            return {"text": " ".join(narration).strip() or None, "tool": terminal[0],
                    "tool_args": terminal[1], "summary": summary}
        messages.append({"role": "user", "content": results})

    return {"text": " ".join(narration).strip() or None, "tool": None, "tool_args": {}, "summary": summary}


def say(name: str, amount_due_cents: int, due_date: date, history: list[dict], directive: str,
        context: dict | None = None) -> str:
    """A single plain-text message from Richie (no tools) for a known next step,
    e.g. summarizing a proposed plan and asking to confirm, or the closing line."""
    system = _system_prompt(name, amount_due_cents, due_date, context) + (
        "\n\nRight now, do exactly this and nothing else (no tools): " + directive
    )
    resp = _create(system, _to_claude_messages(history), tools=None)
    if resp.stop_reason == "refusal":
        raise ClovefiError("Claude declined to reply to this message.")
    text = " ".join(b.text for b in resp.content if b.type == "text" and b.text.strip()).strip()
    if not text:
        raise ClovefiError("Claude returned an empty reply.")
    return text
