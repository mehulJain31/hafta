# CloveFi: agent instructions

CloveFi is AI-powered collections. The operator opens the **CloveFi** homepage →
**Loans due** list → **Chat** on a row → works the account **as the member**.
**Code builds the plan; Richie (Claude) explains, classifies the reason, and
confirms** — Richie never emits a dollar amount or a date. Chats persist; the
server owns the transcript.

## Layout
- `backend/` — Python 3.12, FastAPI.
  - `main.py` = endpoints (money → cents at the boundary). `db.py` = engine + seed + `now_utc`.
  - `enums.py` = allowed string values. `models.py` = the nine tables.
  - `plans.py` = `generate_schedule` / `get_options` — the ONLY source of installment amounts/dates (integer cents).
  - `agent.py` = Richie's prompt + the Claude tool loop (`run_turn`) + `say()`. Tools: show_reason_picker, get_options, escalate, end_conversation, set_summary.
  - `store.py` = persistence + deterministic tool handlers (reason picker, options, propose/confirm plan w/ idempotency, escalate/end, verification).
  - `policies.py` = FDCPA prompt text, STOP words, Reg F constants. `frequency.py` = Reg F ledger. `payments.py` = posted-payments feed.
  - `tests/` = pytest (`plans`, `flow` [Claude mocked], `payments`).
- `frontend/` — Vite + React + TS; `src/App.tsx` = 5 screens (landing, loans, newloan, chat, staff). Vite proxies `/api` → `:8000`.

See `SCHEMA.md`, `ARCHITECTURE.md`, `COMPLIANCE.md`, `FRONTEND.md`.

## Prerequisites
- `backend/.env`: `ANTHROPIC_API_KEY=...`, `LENDER_NAME=State Bank of Elytra`, `DEFAULT_TIMEZONE=America/Los_Angeles` (optional `CLOVEFI_MODEL`, default `claude-opus-5-5`; `CLOVEFI_DB` to move the DB file). Never print or commit `.env`.
- Dev DB is `backend/clovefi.db` (git-ignored, SQLite). No migrations — it seeds one credit union + policy on startup. Since there's no real data, **delete and recreate** to reset.

## Setup / run
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install
# run (two terminals):
cd backend && .venv/bin/uvicorn main:app --reload --port 8000     # http://localhost:8000
cd frontend && npm run dev -- --port 5173 --strictPort            # http://localhost:5173
```
Note: the first `import anthropic` can take ~45s in a cold/sandboxed environment (bytecode compile); it's fast afterward.

## API
- `GET /api/config`; `GET/POST /api/loans`; `POST /api/sessions {loan_id}`.
- `POST /api/verify {conversation_id, answer}` (last-4 stub — nothing is shared until it passes).
- `POST /api/reply {conversation_id, text}`; `POST /api/reason {conversation_id, reason_code, note?}`; `POST /api/choose {conversation_id, plan_type}`; `POST /api/confirm {conversation_id, plan_id}`.
- `GET /api/conversations/{id}`; `GET /api/escalations`; `GET /api/plans?status=`.
- `POST /api/payments/import {csv}`; `POST /api/installments/mark-past-due`.

Mutating endpoints return the full `conversation_detail`. Errors: 404 not found, 409 conflict / contact-blocked / unverified, 422 bad value, 502 Claude error.

## Smoke test (after start)
```bash
LID=$(curl -s -XPOST localhost:8000/api/loans -H 'content-type: application/json' \
  -d '{"name":"Jordan Lee","phone":"5551234567","amount_due":"1000.00","due_date":"2026-01-15"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["loan_id"])')
CID=$(curl -s -XPOST localhost:8000/api/sessions -H 'content-type: application/json' -d "{\"loan_id\":$LID}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["conversation_id"])')
curl -s -XPOST localhost:8000/api/verify -H 'content-type: application/json' -d "{\"conversation_id\":$CID,\"answer\":\"4567\"}"
curl -s -XPOST localhost:8000/api/reply  -H 'content-type: application/json' -d "{\"conversation_id\":$CID,\"text\":\"I can't pay all of it\"}"
```

## Tests / build (Definition of Done)
```bash
cd backend && .venv/bin/python -m pytest -q      # all green
cd frontend && npm run build                     # no TS errors
grep -rniE '\bfloat\b' backend/*.py              # nothing money-related
```
Guarantees to keep: every amount/date comes from the loan record or `plans.generate_schedule`; one `reason_code` per assistance chat; `payment_choice` set only by `confirm_plan`; FULL = 1 installment, SPLIT = `max_installments` summing exactly to the balance; repeated confirms never create a second confirmed plan; `BANKRUPTCY` → escalated with no plan; STOP shortcut + ending-outcome locks stay.
