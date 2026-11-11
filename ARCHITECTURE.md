# CloveFi — Architecture

A React frontend, a FastAPI backend that owns all state and builds every payment
plan itself, SQLite, and Claude (Richie) used only to explain, classify the
reason, and confirm.

See also: [`FRONTEND.md`](FRONTEND.md) · [`SCHEMA.md`](SCHEMA.md) · [`COMPLIANCE.md`](COMPLIANCE.md) · [`AGENTS.md`](AGENTS.md).

## The design principle

**Code builds the plan; Claude explains, classifies and confirms.** Richie never
emits a dollar amount or a date. It calls tools; deterministic backend functions
compute the only arrangements the credit union allows (`plans.py`), the member
picks one in the UI, and the backend persists it once, idempotently.

## The shape

```
┌──────────────┐   /api (Vite proxy)   ┌────────────────────────────────────┐
│   Browser    │ ────────────────────▶ │          Backend (FastAPI)          │
│  React SPA   │                        │  main.py   endpoints (money→cents)  │
│  App.tsx     │ ◀──────────────────── │  store.py  persistence + tool       │
│  5 screens   │   conversation_detail  │            handlers                 │
└──────────────┘                        │  agent.py ─┐  plans.py   frequency  │
                                        │  policies  │  enums.py   payments.py │
                                        └────────────┼────────────────────────┘
                                          ┌──────────▼───┐   ┌────────────────┐
                                          │  Claude API   │   │ SQLite         │
                                          │ (Opus 5.5,    │   │ clovefi.db     │
                                          │  tool use)    │   │                │
                                          └───────────────┘   └────────────────┘
```

- **Frontend** holds only the current conversation in React state and re-renders
  from the `conversation_detail` the backend returns on every action. It never
  holds the API key and never builds a payment plan.
- **Backend** owns all state and all money math. Claude is called only from here
  (key stays server-side) and returns **tool calls**, not amounts.
- **SQLite** persists everything (`SCHEMA.md`).

## Backend modules

| File | Responsibility |
|---|---|
| `main.py` | FastAPI endpoints; converts money to cents at the boundary; maps store exceptions → HTTP. |
| `db.py` | Engine, `create_db_and_tables()` (+ seeds one credit union & policy), `now_utc()`. |
| `enums.py` | The allowed string values (ReasonCode, PlanType, PlanStatus, InstallmentStatus, PaymentChoice, Outcome) + `ENDING_OUTCOMES`. |
| `models.py` | The nine SQLModel tables. |
| `plans.py` | `generate_schedule` (pure, integer cents) + `get_options`. **The only source of installment amounts/dates.** |
| `agent.py` | Richie: the system prompt, the Claude tool loop (`run_turn`) and a plain-text `say()`. Tools: `show_reason_picker`, `get_options`, `escalate`, `end_conversation`, `set_summary`. |
| `store.py` | All DB reads/writes + the deterministic tool handlers (reason picker, options card, propose/confirm plan with idempotency, escalate/end, verification). |
| `policies.py` | FDCPA prompt text, STOP words, Reg F frequency constants. Plan limits live in the `cu_policies` table, not here. |
| `frequency.py` | Reg F gate (ledger kept; not a blocker for member-initiated sessions). |
| `payments.py` | Posted-payments feed: apply payments to installments, mark past due. |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/config` | `{lender_name, agent_name}` |
| `GET /api/loans?status=` · `POST /api/loans` | List loans due · create a loan (no chat; money as decimal → cents) |
| `POST /api/sessions {loan_id}` | Open a member chat (do-not-contact gate; logs a `contact_attempt`). Returns `conversation_detail`. |
| `POST /api/verify {conversation_id, answer}` | Identity stub (last 4 of phone). Nothing about the account is shared until this passes. |
| `POST /api/reply {conversation_id, text}` | Free-text member turn → Richie tool loop. |
| `POST /api/reason {conversation_id, reason_code, note?}` | Record the reason (chip); auto-escalates for `BANKRUPTCY`; else Richie shows options. |
| `POST /api/choose {conversation_id, plan_type}` | Propose a plan server-side (idempotent) + Richie asks to confirm. |
| `POST /api/confirm {conversation_id, plan_id}` | Confirm (idempotent; supersedes prior); sets `payment_choice`; ends the chat. |
| `GET /api/conversations/{id}` | Full structured transcript (for reload/resume). |
| `GET /api/escalations` · `GET /api/plans?status=` | Staff reads. |
| `POST /api/payments/import` · `POST /api/installments/mark-past-due` | Payments feed. |

Every mutating endpoint returns the whole `conversation_detail`, so the frontend
re-renders text + structured cards from one response.

## Conversation flow

```
open_session → opener asks for last 4 of phone (NO amount yet)
  POST /api/verify  ──(stub: last4)──▶ verified_at set → Richie states the balance & due date
  POST /api/reply "I can't pay it all" → Richie calls show_reason_picker  → reason chips
  POST /api/reason REDUCED_INCOME     → Richie calls get_options          → option cards
        (BANKRUPTCY → auto-escalate, no Claude, chat locked)
  POST /api/choose SPLIT              → propose_plan (code) + Richie asks to confirm
  POST /api/confirm <plan_id>         → confirm_plan (code) → payment_choice=SPLIT, chat ends
```
A member message of exactly `STOP` short-circuits to opt-out without calling Claude.

## Trust & compliance (enforced in code, not the prompt)
- **Server owns the transcript** (rebuilt from `messages`).
- **No amount or date from Claude** — all from `plans.generate_schedule`; the
  prompt only *forbids* inventing them.
- **Identity before account details** — `verified_at` gates reason/options/confirm (409 until set).
- **Idempotency** — `propose_plan`/`confirm_plan` can't create a second confirmed plan.
- **Must-stop outcomes** (dispute/opt-out/attorney/wrong person) lock the chat; `STOP` bypasses the model.

## Deployment & scope
- **Dev:** Vite (`:5173`, proxies `/api`) + Uvicorn (`:8000`), SQLite file.
- **Out of scope (MVP):** payment rails, outbound SMS/voice (and the Reg F
  blocker), real identity verification (OTP/SSO), written validation-notice
  generation, PII encryption / Postgres, multi-tenant auth. One seeded credit union.
