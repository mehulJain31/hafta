# Clovefi: agent instructions

Clovefi is AI-powered collections. On the **Clovefi** landing page an operator clicks "Initiate collections", enters a borrower (name, phone, amount due, due date), and Richie (Claude) opens the conversation. The operator replies as the borrower. Chats are **persisted in a database** and the **server owns the transcript** — Richie negotiates a payment within the lender's policy and the FDCPA, and recalls a borrower's last decision on a new chat.

## Layout
- `backend/` — Python 3.12, FastAPI.
  - `main.py` = endpoints (keyed by `conversation_id`; keeps the API key server-side).
  - `agent.py` = Richie's system prompt + Claude call (structured JSON: reply, outcome, payments, summary).
  - `policies.py` = FDCPA rules + lender payment options (split / extension limits). Change collection rules here.
  - `models.py` = SQLModel tables; `db.py` = engine + `now_utc()`; `store.py` = all DB reads/writes (customer upsert, open-loan reuse, contact-block, record turn, prior-context recall).
- `frontend/` — Vite + React + TS. `src/App.tsx` = three screens (landing → form → chat). Vite proxies `/api` to `localhost:8000`.

## Database (SQLite, `backend/clovefi.db`, git-ignored)
Five tables: `customers` (unique by normalized phone) → `loans` (one open loan per customer; `amount_due` is data, never identity) → `conversations` (outcome + summary) → `messages` (transcript) + `promised_payments` (agreed dates/amounts). Timestamps are tz-aware UTC; `customers.timezone` is an IANA name for future display / FDCPA calling-hours. **PII is not encrypted in the dev DB** — don't put real borrower data in it; production plan is column encryption via a KMS + a keyed HMAC blind index for lookups (no hashing of readable PII). Override the path with `CLOVEFI_DB=...`.

## Prerequisites
- `backend/.env`: `ANTHROPIC_API_KEY=...`, `LENDER_NAME=State Bank of Elytra`, `DEFAULT_TIMEZONE=America/Los_Angeles` (optional `CLOVEFI_MODEL`, default `claude-opus-5-5`).
  Never print or commit `.env`. `backend/.env.example` is the blank template.

## First-time setup (skip if `backend/.venv` and `frontend/node_modules` exist)
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install
```

## Start (run from repo root; both long-running, start in background)
```bash
cd backend && .venv/bin/uvicorn main:app --reload --port 8000   # http://localhost:8000  (docs at /docs)
cd frontend && npm run dev -- --port 5173 --strictPort          # http://localhost:5173
```
Ready check: `curl -s localhost:8000/openapi.json` and `curl -s localhost:5173` both succeed.

## API (server owns state)
- `POST /api/start` `{name, phone, amount_due, due_date}` → `{conversation_id, message, prior_context}`. Upserts the customer by phone, reuses/creates their open loan, opens a conversation, saves Richie's opener. **409** with a do-not-contact message if the loan's last outcome was `stop_request`/`attorney`.
- `POST /api/reply` `{conversation_id, text}` → `{message, outcome, payments, missed_payment_reason, ended, policy_issues}`. Rebuilds history from the DB, calls Richie, persists the turn. **409** if the conversation already ended; **404** if unknown; **502** on a Claude error (`detail` says why).
- `GET /api/conversations/{id}` → loan + full transcript + outcome/summary/payments (reload a chat).
- `GET /api/config` → `{lender_name, agent_name}`.

Outcomes: `in_progress`, `promise_to_pay`, `payment_plan`, `extension`, `hardship_referral`, and the ending ones (`dispute`, `stop_request`, `attorney`, `wrong_person`, `escalated`) which set `ended: true`, lock the chat, and update the loan status. A borrower message of just "STOP" is handled without calling Claude.

## Smoke test
```bash
R=$(curl -s -XPOST localhost:8000/api/start -H 'content-type: application/json' \
  -d '{"name":"Jordan Lee","phone":"+1 555 123 4567","amount_due":450,"due_date":"2027-02-02"}')
CID=$(echo "$R" | python3 -c 'import sys,json;print(json.load(sys.stdin)["conversation_id"])')
curl -s -XPOST localhost:8000/api/reply -H 'content-type: application/json' \
  -d "{\"conversation_id\":$CID,\"text\":\"I can pay 150 on Feb 2 and 300 on Feb 20\"}"
```

## Stop
```bash
lsof -ti tcp:8000 | xargs kill; lsof -ti tcp:5173 | xargs kill
```

## Build check
`cd frontend && npm run build` must pass with no TypeScript errors.
