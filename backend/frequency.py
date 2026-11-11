"""Regulation F contact-frequency checks (12 CFR 1006.14(b), 1006.6(b)).

Reg F's numeric limits are telephone-call rules. In this demo every chat
'Initiate collections' counts as a contact attempt, so the 7-in-7 cap, the
7-day post-conversation freeze, and the 8am-9pm calling window all apply to
chats. When real phone/voice ships, filter attempts to channel == "phone_call"
for the legally-exact rule.

All timestamps are timezone-aware UTC (SQLModel stores and returns aware
datetimes); the only tz conversion is to the borrower's local time for the
calling-hours check.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

import policies
from models import ContactAttempt


class FrequencyBlock(Exception):
    """Contacting now would break a Reg F frequency/time rule."""

    def __init__(self, reason: str, retry_at: datetime | None = None):
        self.reason = reason
        self.retry_at = retry_at
        super().__init__(reason)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check(session: Session, loan, customer, now: datetime | None = None) -> None:
    """Raise FrequencyBlock if contacting this borrower right now breaks Reg F."""
    now = _aware(now) if now else datetime.now(timezone.utc)

    # 1006.6(b)(1): only between 8am and 9pm the borrower's local time.
    lo, hi = policies.CALLING_HOURS
    try:
        local = now.astimezone(ZoneInfo(customer.timezone))
    except Exception:
        local = now
    if not (lo <= local.hour < hi):
        raise FrequencyBlock(
            f"It's {local:%-I:%M %p} for the borrower ({customer.timezone}). "
            f"Collection contact is only allowed {lo}am–{hi - 12}pm their local time."
        )

    attempts = session.exec(
        select(ContactAttempt).where(ContactAttempt.loan_id == loan.id)
    ).all()

    # 1006.14(b)(2)(i)(B): no contact for 7 days after a conversation about the debt.
    conversations = [_aware(a.attempted_at) for a in attempts if a.had_conversation]
    if conversations:
        until = max(conversations) + timedelta(days=policies.POST_CONVERSATION_FREEZE_DAYS)
        if now < until:
            raise FrequencyBlock(
                f"You spoke with this borrower in the last {policies.POST_CONVERSATION_FREEZE_DAYS} days. "
                f"Regulation F bars another contact until {until:%b %-d}.",
                until,
            )

    # 1006.14(b)(2)(i)(A): no more than 7 attempts in a rolling 7-day window.
    window_start = now - timedelta(days=7)
    recent = [a for a in attempts if _aware(a.attempted_at) >= window_start]
    if len(recent) >= policies.MAX_CONTACTS_PER_7_DAYS:
        soonest = min(_aware(a.attempted_at) for a in recent) + timedelta(days=7)
        raise FrequencyBlock(
            f"This borrower has been contacted {len(recent)} times in the last 7 days. "
            f"Regulation F allows at most {policies.MAX_CONTACTS_PER_7_DAYS} (the 7-in-7 rule). "
            f"Next contact allowed {soonest:%b %-d}.",
            soonest,
        )


def log_attempt(session: Session, loan_id: int, conversation_id: int, channel: str = "web_chat") -> None:
    session.add(ContactAttempt(loan_id=loan_id, conversation_id=conversation_id, channel=channel))


def mark_conversation(session: Session, conversation_id: int) -> None:
    """Flag this chat's attempt as a real conversation (starts the 7-day freeze)."""
    att = session.exec(
        select(ContactAttempt).where(ContactAttempt.conversation_id == conversation_id)
    ).first()
    if att and not att.had_conversation:
        att.had_conversation = True
        session.add(att)
