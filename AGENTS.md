# Hafta: agent instructions

Hafta v0 is a one-time collections chat. The operator enters a borrower name, amount due and due date. The agent, Richie (Claude), opens with a "payment is due" message and chats with the borrower. Nothing is stored: the browser holds the chat and sends the full history on each reply.

## Layout
- `backend/` — Python 3.12, FastAPI. `main.py` = endpoints, `agent.py` = system prompt + Claude call (structured JSON output), `policies.py` = FDCPA rules + lender payment options (split / extension limits). Change collection rules in `policies.py`.
- `frontend/` — Vite + React + TypeScript. `src/App.tsx` = form + chat. Vite proxies `/api` to `localhost:8000`.

## Prerequisites
- `backend/.env` must contain `ANTHROPIC_API_KEY=...` and `LENDER_NAME=State Bank of Elytra` (optional `HAFTA_MODEL`, default `claude-opus-5-5`).
  Never print or commit this file. `backend/.env.example` is the blank template.

## First-time setup (skip if `backend/.venv` and `frontend/node_modules` exist)
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install
```

## Start (run from repo root; both are long-running, start them in the background)
```bash
# Backend → http://localhost:8000  (API docs at /docs)
cd backend && .venv/bin/uvicorn main:app --reload --port 8000

# Frontend → http://localhost:5173
cd frontend && npm run dev -- --port 5173 --strictPort
```

Ready check: `curl -s localhost:8000/docs` and `curl -s localhost:5173` both succeed.

## Smoke test
```bash
# Opening message (no Claude call)
curl -s -XPOST localhost:8000/api/start -H 'content-type: application/json' \
  -d '{"name":"Jordan Lee","amount_due":450,"due_date":"2026-10-15"}'

# Claude reply (last message must be from the borrower)
curl -s -XPOST localhost:8000/api/reply -H 'content-type: application/json' \
  -d '{"loan":{"name":"Jordan Lee","amount_due":450,"due_date":"2026-10-15"},
       "messages":[{"role":"hafta","text":"Your $450 payment is overdue. When can you pay?"},
                   {"role":"borrower","text":"I can pay $200 Friday"}]}'
```
Expect `200` with `{"message":{"role":"hafta","text":...},"outcome":...,"payments":[...],"missed_payment_reason":...,"ended":bool,"policy_issues":[...]}`.
Outcomes: in_progress, promise_to_pay, payment_plan, extension, hardship_referral, and the ending ones (dispute, stop_request, attorney, wrong_person, escalated) which set `ended: true` and lock the chat. A borrower message of just "STOP" is handled without calling Claude. A `502` means a Claude problem; the `detail` field says what (e.g. missing key).

## Stop
```bash
lsof -ti tcp:8000 | xargs kill; lsof -ti tcp:5173 | xargs kill
```

## Build check
`cd frontend && npm run build` must pass with no TypeScript errors.
