"""The only allowed values for the domain's string columns and tool arguments.

Defined once and imported everywhere (models, agent tools, API validation,
mirrored by hand in the frontend types). Each enum is a `str` enum, so its
members compare equal to their wire string and store directly in the DB.
"""

from enum import Enum


class ReasonCode(str, Enum):
    NONE = "NONE"
    JOB_LOSS = "JOB_LOSS"
    REDUCED_INCOME = "REDUCED_INCOME"
    MEDICAL_EXPENSE = "MEDICAL_EXPENSE"
    DEATH_IN_FAMILY = "DEATH_IN_FAMILY"
    UNEXPECTED_EXPENSE = "UNEXPECTED_EXPENSE"
    BANKRUPTCY = "BANKRUPTCY"
    OTHER = "OTHER"


class PlanType(str, Enum):
    FULL = "FULL"
    SPLIT = "SPLIT"


class PlanStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class PaymentChoice(str, Enum):
    UNDECIDED = "UNDECIDED"
    FULL = "FULL"
    SPLIT = "SPLIT"


class Outcome(str, Enum):
    IN_PROGRESS = "in_progress"
    PROMISE_TO_PAY = "promise_to_pay"
    PAYMENT_PLAN = "payment_plan"
    EXTENSION = "extension"
    HARDSHIP_REFERRAL = "hardship_referral"
    DISPUTE = "dispute"
    STOP_REQUEST = "stop_request"
    ATTORNEY = "attorney"
    WRONG_PERSON = "wrong_person"
    ESCALATED = "escalated"


# Outcomes where the law (or a hand-off) requires the conversation to end.
ENDING_OUTCOMES = frozenset({
    Outcome.DISPUTE,
    Outcome.STOP_REQUEST,
    Outcome.ATTORNEY,
    Outcome.WRONG_PERSON,
    Outcome.ESCALATED,
})

# Ending outcomes the `end_conversation` tool may set (escalate() handles ESCALATED).
END_CONVERSATION_OUTCOMES = frozenset({
    Outcome.DISPUTE,
    Outcome.STOP_REQUEST,
    Outcome.ATTORNEY,
    Outcome.WRONG_PERSON,
})


def values(enum_cls) -> list[str]:
    """The wire strings of an enum, e.g. for a JSON-schema `enum` list."""
    return [m.value for m in enum_cls]
