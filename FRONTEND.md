# CloveFi — Frontend / UI

The operator-facing web app: a CloveFi homepage, a **Loans-due** list, a chat
where the operator works an account **as the member**, and a read-only **Staff**
view. Richie drives the conversation; the member taps structured chips/cards.

- **Stack:** Vite + React + TypeScript. One source file: `frontend/src/App.tsx`;
  all styling in `frontend/src/index.css`.
- **Dev:** `npm run dev` → http://localhost:5173; Vite proxies `/api` → `:8000`.
- The frontend **never builds a payment plan** — it renders what the backend
  returns and posts the member's choices.

## Screens (`App`, `screen: 'landing' | 'loans' | 'newloan' | 'chat' | 'staff'`)

### Landing (`<Landing>`)
The CloveFi homepage (hero + chat preview, "How Richie works", compliance cards,
footer). **Initiate collections** → the Loans-due list.

### Loans due (`<LoansDue>`)
`GET /api/loans` → a table of members with a past-due balance: name, masked
phone, amount, due date, last-outcome badge, "Plan set" badge. Per row, **Chat**
opens a new session (`POST /api/sessions`) or **Resume** loads the open
conversation (`GET /api/conversations/{id}`). Header: **Staff** and **New collection**.

### New collection (`<NewLoan>`)
`POST /api/loans` with name, phone, amount (decimal), due date — creates a loan
**without** opening a chat (how test data gets in). Back → Loans due.

### Chat (`<Chat>`)
Holds one `conversation_detail` in state; every action replaces it with the
backend's response. Renders messages by **kind**:
- **text** → bubble (agent left with avatar, borrower right).
- **reason_picker** → the question + a row of **chips** (one per reason, plain-English
  labels); tapping posts `/api/reason`. For **Other**, an optional note field (`reason_note`).
- **options_card** → one **card per option** (plan type + each installment's amount & date);
  tapping posts `/api/choose`.
- **plan_summary** → the proposed schedule with **Confirm plan** (`/api/confirm`) and a
  "Pick a different option" link that re-enables the option cards.

**Identity gate:** while `verified_at` is null, the composer posts to
`/api/verify` with the placeholder "Enter the last 4 digits of the phone on
file…"; after verifying, it posts to `/api/reply`. Chips/options/confirm are
disabled once used (the backend also rejects a repeat with 409). When the chat
ends, the composer is replaced by a notice (plan confirmed, or the FDCPA reason).

### Staff (`<Staff>`)
Read-only, two tabs: **Escalations** (`GET /api/escalations` — member, amount,
reason, summary) and **Confirmed plans** (`GET /api/plans` — member, plan type,
total, schedule with installment statuses).

## Status badges (`OUTCOMES`)
Maps a conversation `outcome` to a label + tone (neutral/good/warn/stop). The
`stop`-tone outcomes (dispute, opt-out, attorney, wrong person) also end the chat
and show the FDCPA note from `ENDED_NOTE`.

## Data flow
The server owns the transcript; the browser keeps only the current
`conversation_detail` and replaces it after each call. Amounts arrive as
**integer cents** and are formatted on the client (`usd(cents)`); the API never
sends floats, and the new-loan form sends the amount as a decimal string.
Types mirror the backend at the top of `App.tsx` (`Detail`, `Msg`, `Option`,
`Installment`, `LoanRow`, …).

## Design system
CSS custom properties on `:root` (light theme): Berkeley Blue (`--blue #003262`),
California Gold (`--gold #fdb515`), plus surfaces/tints. Font: Inter. The CloveFi
mark is inline SVG in `Wordmark` (tan boll + brown calyx/stem). Rounded cards,
pill buttons, chat bubbles with one squared corner; responsive down to phone
width (nav links hide, grids collapse, chat card near-full-height).

## Run
```bash
cd frontend
npm install
npm run dev        # :5173, proxies /api → :8000
npm run build      # type-check + production build
```
The backend must be on `:8000` for the list, chat and staff view to work; the
landing page renders without it.
