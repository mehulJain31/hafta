# CloveFi — Database Schema

The database behind CloveFi's AI-powered collections. It persists credit-union
policy, borrowers, debts, conversations, the **code-built payment plans**, and
the outreach ledger — so the server owns the transcript, Richie never invents an
amount or date, and staff can act on structured outcomes.

- **Engine:** SQLite in dev (`backend/clovefi.db`), via SQLModel/SQLAlchemy;
  portable to PostgreSQL.
- **Source of truth:** `backend/models.py` + `backend/enums.py`. If this doc and
  the code disagree, the code wins.
- **Money is integer cents everywhere — never a float.** Timestamps are
  timezone-aware UTC. String columns hold values from `enums.py`.

## Entity relationships

```
credit_unions ─1:N─> cu_policies
customers ─1:N─> loans ─1:N─> conversations ─1:N─> messages
                   │                 │
                   │                 └─1:N─> payment_plans ─1:N─> installments
                   │
                   └─1:N─> contact_attempts   (Reg F ledger; future outbound)
```

- A **credit union** has one **policy** (the only plan types / limits allowed).
- A **customer** (keyed by phone) has **loans**; a loan belongs to a credit union.
- A **loan** has **conversations** (chats over time) and the **payment_plans** agreed on it.
- A **conversation** has **messages** (the transcript, including structured cards).
- A **payment_plan** has **installments** (the schedule). One plan per loan may be `confirmed`.

## Enums (`enums.py`)

| Enum | Values |
|---|---|
| `ReasonCode` | NONE · JOB_LOSS · REDUCED_INCOME · MEDICAL_EXPENSE · DEATH_IN_FAMILY · UNEXPECTED_EXPENSE · BANKRUPTCY · OTHER |
| `PlanType` | FULL · SPLIT |
| `PlanStatus` | proposed · confirmed · superseded · cancelled |
| `InstallmentStatus` | SCHEDULED · PAID · PAST_DUE |
| `PaymentChoice` | UNDECIDED · FULL · SPLIT |
| `Outcome` | in_progress · promise_to_pay · payment_plan · extension · hardship_referral · **dispute · stop_request · attorney · wrong_person · escalated** (the last five end the chat) |

## Tables

### `credit_unions`
`id` · `name` · `timezone` (IANA) · `pay_portal_url` (nullable) · `created_at`.
Seeded with one row on startup (`db._seed`).

### `cu_policies` — the allowed arrangements (read at runtime, not hardcoded)
`id` · `credit_union_id`→credit_unions · `allowed_plan_types` (JSON, e.g. `["FULL","SPLIT"]`) ·
`max_installments` (4) · `installment_interval` (`monthly`) · `max_extension_days` (0 = off) ·
`min_installment_cents` (2500) · `auto_escalate_reasons` (JSON, `["BANKRUPTCY"]`) · `first_payment_rule` (`on_due_date`).
`plans.get_options` reads this; a SPLIT whose installment would fall below `min_installment_cents` is simply not offered.

### `customers`
`id` · `name` · `phone_number` (**unique**, normalized to digits — the identity key) ·
`email` (nullable) · `timezone` (IANA, for FDCPA hours) · `created_at`. **PII — plaintext in dev only.**

### `loans`
`id` · `customer_id`→customers · `credit_union_id`→credit_unions · **`amount_due_cents`** (current balance) ·
`due_date` · `external_loan_ref` (nullable; the CU core's loan number, used by the payments feed) ·
`status` (`in_collections · disputed · do_not_contact · resolved · escalated`) · `created_at` · `updated_at`.
Identity is never the amount; `amount_due_cents` is mutable data.

### `conversations`
`id` · `loan_id`→loans · `channel` (`web_chat`) · `status` (`open`/`ended`) · `outcome` (Outcome enum) ·
`summary` (for staff; **not** fed into the next prompt) · `reason_code` (ReasonCode, once captured) ·
`reason_note` (free text for OTHER / the escalation reason; never used for logic) ·
`payment_choice` (**set only by `confirm_plan`**) · `verified_at` (identity verification; null until passed) ·
`verify_attempts` (locks at 2) · `started_at` · `ended_at`.

### `messages` — the transcript, incl. structured cards
`id` · `conversation_id`→conversations · `role` (`agent`/`borrower`) · `text` ·
**`kind`** (`text · reason_picker · options_card · plan_summary`) · **`payload`** (JSON, nullable — chips/options/plan data) · `created_at`.
The server rebuilds Claude's history from `text`; the frontend re-renders cards from `kind` + `payload`.

### `payment_plans` — replaces the old promised_payments (never deleted/rewritten)
`id` · `conversation_id`→conversations · `loan_id`→loans · `plan_type` (FULL/SPLIT) ·
`installment_count` · `total_cents` (= `loans.amount_due_cents` at creation) · `status` (PlanStatus) ·
**`idempotency_key`** (unique; `"<conversation_id>:<plan_type>"` — a repeated propose returns the same row) ·
`proposed_at` · `confirmed_at` (nullable). A new confirmed plan supersedes any prior confirmed plan on the loan; at most one `confirmed` per loan.

### `installments` — immutable once the plan is confirmed
`id` · `plan_id`→payment_plans · `installment_number` (1-based) · `amount_cents` · `due_date` ·
`status` (SCHEDULED/PAID/PAST_DUE) · `paid_at` (nullable). Index `(due_date, status)`.

### `contact_attempts` — Regulation F ledger (kept for future outbound)
`id` · `loan_id`→loans · `conversation_id` (nullable) · `channel` · `attempted_at` · `had_conversation` · `result` · `created_at`.
Logged on every session open; **nothing blocks on it today** (member-initiated sessions aren't outbound calls).

## Where values are set
- **`amount_due_cents`**: converted from a decimal at the API boundary (`main._cents`, `Decimal`, `ROUND_HALF_UP`) — never from a float.
- **Installment amounts/dates**: only from `plans.generate_schedule` (equal splits, last absorbs the remainder; monthly dates clamp to month-end from the original due date).
- **`payment_choice`**: only by `confirm_plan`. **`verified_at`**: only by `store.verify`.
- **Plan `status`**: `proposed` by `propose_plan`, `confirmed`/`superseded` by `confirm_plan`.
- **Installment `status`**: `PAID` by the payments feed, `PAST_DUE` by `mark_past_due`; loan → `resolved` when all installments are PAID.

## Security & PII
`customers.name/phone_number/email` and message bodies are personal data —
plaintext in the dev SQLite file, **not for real borrower data**. Production:
encrypt PII columns with a KMS key (AES-GCM / envelope encryption — not hashing,
since we read it back) + a keyed HMAC blind index on phone for lookups; encrypt
at rest; add a retention policy. `clovefi.db` is git-ignored.

## Production notes (SQLite → PostgreSQL)
| Dev (SQLite) | Production (Postgres) |
|---|---|
| `DATETIME` (UTC) | `TIMESTAMPTZ` |
| `JSON` columns | `JSONB` |
| string enums (app-enforced) | `CHECK` constraints or native `ENUM` |
| single-column indexes | add composites: `loans(customer_id, status)`, `conversations(loan_id, started_at)`, `installments(due_date, status)` |
| one-confirmed-plan rule (app-enforced) | partial unique index `payment_plans(loan_id) WHERE status='confirmed'` |

Money is already integer cents, so no numeric change is needed.

## Appendix — current DDL (SQLite)

Exactly what `db.create_db_and_tables()` creates:

```sql
CREATE TABLE credit_unions (
	id INTEGER NOT NULL, name VARCHAR NOT NULL, timezone VARCHAR NOT NULL,
	pay_portal_url VARCHAR, created_at DATETIME NOT NULL, PRIMARY KEY (id)
);

CREATE TABLE cu_policies (
	id INTEGER NOT NULL, credit_union_id INTEGER NOT NULL, allowed_plan_types JSON,
	max_installments INTEGER NOT NULL, installment_interval VARCHAR NOT NULL,
	max_extension_days INTEGER NOT NULL, min_installment_cents INTEGER NOT NULL,
	auto_escalate_reasons JSON, first_payment_rule VARCHAR NOT NULL,
	PRIMARY KEY (id), FOREIGN KEY(credit_union_id) REFERENCES credit_unions (id)
);
CREATE INDEX ix_cu_policies_credit_union_id ON cu_policies (credit_union_id);

CREATE TABLE customers (
	id INTEGER NOT NULL, name VARCHAR NOT NULL, phone_number VARCHAR NOT NULL,
	email VARCHAR, timezone VARCHAR NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_customers_phone_number ON customers (phone_number);

CREATE TABLE loans (
	id INTEGER NOT NULL, customer_id INTEGER NOT NULL, credit_union_id INTEGER NOT NULL,
	amount_due_cents INTEGER NOT NULL, due_date DATE NOT NULL, external_loan_ref VARCHAR,
	status VARCHAR NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
	PRIMARY KEY (id), FOREIGN KEY(customer_id) REFERENCES customers (id),
	FOREIGN KEY(credit_union_id) REFERENCES credit_unions (id)
);
CREATE INDEX ix_loans_customer_id ON loans (customer_id);
CREATE INDEX ix_loans_credit_union_id ON loans (credit_union_id);
CREATE INDEX ix_loans_status ON loans (status);

CREATE TABLE conversations (
	id INTEGER NOT NULL, loan_id INTEGER NOT NULL, channel VARCHAR NOT NULL,
	status VARCHAR NOT NULL, outcome VARCHAR NOT NULL, summary VARCHAR NOT NULL,
	reason_code VARCHAR, reason_note VARCHAR, payment_choice VARCHAR NOT NULL,
	verified_at DATETIME, verify_attempts INTEGER NOT NULL,
	started_at DATETIME NOT NULL, ended_at DATETIME,
	PRIMARY KEY (id), FOREIGN KEY(loan_id) REFERENCES loans (id)
);
CREATE INDEX ix_conversations_loan_id ON conversations (loan_id);
CREATE INDEX ix_conversations_outcome ON conversations (outcome);

CREATE TABLE messages (
	id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, role VARCHAR NOT NULL,
	text VARCHAR NOT NULL, kind VARCHAR NOT NULL, payload JSON, created_at DATETIME NOT NULL,
	PRIMARY KEY (id), FOREIGN KEY(conversation_id) REFERENCES conversations (id)
);
CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE TABLE payment_plans (
	id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, loan_id INTEGER NOT NULL,
	plan_type VARCHAR NOT NULL, installment_count INTEGER NOT NULL, total_cents INTEGER NOT NULL,
	status VARCHAR NOT NULL, idempotency_key VARCHAR NOT NULL,
	proposed_at DATETIME NOT NULL, confirmed_at DATETIME,
	PRIMARY KEY (id), FOREIGN KEY(conversation_id) REFERENCES conversations (id),
	FOREIGN KEY(loan_id) REFERENCES loans (id)
);
CREATE INDEX ix_payment_plans_loan_id ON payment_plans (loan_id);
CREATE UNIQUE INDEX ix_payment_plans_idempotency_key ON payment_plans (idempotency_key);
CREATE INDEX ix_payment_plans_conversation_id ON payment_plans (conversation_id);
CREATE INDEX ix_payment_plans_status ON payment_plans (status);

CREATE TABLE installments (
	id INTEGER NOT NULL, plan_id INTEGER NOT NULL, installment_number INTEGER NOT NULL,
	amount_cents INTEGER NOT NULL, due_date DATE NOT NULL, status VARCHAR NOT NULL, paid_at DATETIME,
	PRIMARY KEY (id), FOREIGN KEY(plan_id) REFERENCES payment_plans (id)
);
CREATE INDEX ix_installments_plan_id ON installments (plan_id);
CREATE INDEX ix_installments_status ON installments (status);
CREATE INDEX ix_installments_due_date ON installments (due_date);

CREATE TABLE contact_attempts (
	id INTEGER NOT NULL, loan_id INTEGER NOT NULL, conversation_id INTEGER,
	channel VARCHAR NOT NULL, attempted_at DATETIME NOT NULL, had_conversation BOOLEAN NOT NULL,
	result VARCHAR NOT NULL, created_at DATETIME NOT NULL,
	PRIMARY KEY (id), FOREIGN KEY(loan_id) REFERENCES loans (id),
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
);
CREATE INDEX ix_contact_attempts_loan_id ON contact_attempts (loan_id);
CREATE INDEX ix_contact_attempts_attempted_at ON contact_attempts (attempted_at);
```
