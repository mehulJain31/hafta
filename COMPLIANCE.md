# CloveFi — Compliance (FDCPA & Regulation F)

How CloveFi follows the **Fair Debt Collection Practices Act** (FDCPA, 15 U.S.C.
§1692) and the CFPB's **Regulation F** (12 CFR part 1006). Compliance is enforced
in **code**, not left to the model.

> **Not legal advice.** This documents what the demo implements and the rules it
> targets. Have counsel review before using with real members. Open items are in
> [Caveats](#caveats-before-production).

**Two layers:**
1. **Prompt** — rules in Richie's system prompt (`policies.FDCPA_RULES`). Guides what Richie *says*.
2. **Code gates** — deterministic checks that don't depend on Claude.

The design principle is itself a compliance control: **code builds the payment
plan; Claude never emits an amount or a date.** Every installment comes from
`plans.generate_schedule`, so nothing outside the credit union's policy can be
offered or agreed.

## Where each rule lives

| Rule | Prompt | Code gate |
|---|---|---|
| Debt-collection notice on first contact (§807(11)) | — | `agent.opening_message` (fixed template) |
| Identity before sharing account details | — | `store.verify` / `verified_at` gate |
| Honesty / no threats / no false fees (§807–808) | `FDCPA_RULES` | plan math is code-built; `plans.py` |
| No harassment / repetition (§806) | `FDCPA_RULES` | — |
| Stop on opt-out / attorney (§805) | `FDCPA_RULES` | ending outcome locks chat + `STOP` shortcut + loan `do_not_contact` |
| Right-party contact (§805(b)) | `FDCPA_RULES` | `wrong_person` outcome; verification lock |
| Dispute → pause (§809) | `FDCPA_RULES` | `dispute` outcome + loan `disputed` |
| Only policy-allowed terms | tool descriptions | `plans.get_options` from `cu_policies` |
| Reg F frequency / hours | — | `frequency.py` (ledger; see note) |

## FDCPA

- **§807(11) disclosure (“mini-Miranda”).** The opener is a **fixed template**
  (`agent.opening_message`), always correct, and now asks to verify identity
  **before any account detail (including the amount)** is shared:
  > "Hi {first name}, this is Richie, an automated assistant with {lender}. This
  > is an attempt to collect a debt, and any information obtained will be used for
  > that purpose. Before I share any account details, can you confirm the last
  > four digits of the phone number on file? Reply STOP to opt out."
- **§806 harassment.** No profanity, shaming or pressure; don't repeat an
  answered request. The Reg F caps below are the bright-line version.
- **§807 / §808 honesty.** Richie uses only the loan facts; it never threatens,
  never adds fees, never impersonates a lawyer/agency/bureau. Installment amounts
  and dates are **code-built**, so they can't be misstated. Credit reporting may
  be mentioned once, factually, never after a dispute (§807(8)).
- **§805 must-stop (the server locks the chat).** Outcome ∈ ending outcomes; the
  UI replaces the composer with a notice citing the section:

  | Situation | § | Outcome | Loan effect |
  |---|---|---|---|
  | Stop / refuses to pay | 805(c) | `stop_request` | `do_not_contact` |
  | Attorney | 805(a)(2) | `attorney` | `do_not_contact` |
  | Not the member | 805(b) | `wrong_person` | — (reveal nothing) |
  | Bankruptcy / death / complaint | — | `escalated` | `escalated` |

  **STOP keyword** is answered deterministically without Claude
  (`policies.STOP_WORDS` → `store` opt-out). A `do_not_contact` loan refuses a new
  session (409).
- **§809 disputes.** Richie notes the dispute, says written verification will be
  sent and collection is paused; outcome `dispute`, loan `disputed`.

## Identity verification (Phase 4 — stub)
The opener shares nothing about the account until the member passes a check.
`POST /api/verify` compares the answer to the last four digits of the phone on
file; `verified_at` then gates the reason picker, options, and confirm (409
until set). **Two failures → `wrong_person`, chat locked, nothing revealed.**
This is a **stub**: replace with OTP-to-phone or CU SSO before any real member.

## Regulation F — contact frequency & timing
Limits live in `policies.py` (`MAX_CONTACTS_PER_7_DAYS=7`,
`POST_CONVERSATION_FREEZE_DAYS=7`, `CALLING_HOURS=(8,21)`) and are implemented in
`frequency.py` against the `contact_attempts` ledger: **7-in-7**
(§1006.14(b)(2)(i)(A)), **7-day post-conversation freeze** (…(B)), and **8am–9pm
local time** (§1006.6(b)(1)). Every opener includes "Reply STOP to opt out"
(§1006.6(e)).

> **Scope note.** Reg F's numeric caps are *telephone* rules. CloveFi's chats are
> **member-initiated sessions**, not outbound calls, so the frequency gate is
> **not** a blocker today — the ledger is logged and ready for when outbound
> SMS/voice ships (then count `channel='phone_call'`).

## Changing the rules
- **Plan terms** (installments, minimum): the `cu_policies` row (seeded in `db._seed`).
- **Frequency limits:** `policies.py`.
- **Prompt rules:** `policies.FDCPA_RULES`.

## Caveats before production
- **Who the FDCPA covers.** It primarily governs *third-party* collectors; a
  creditor/CU collecting its own debts is often outside it. Applying it is a
  stricter-than-required posture — confirm with counsel.
- **Identity verification** is a stub (last-4). Replace with OTP/SSO.
- **Written validation notice (§1006.34).** Richie says verification will be
  sent, but the demo doesn't generate or send it. **Open item: who sends it —
  the credit union or CloveFi?**
- **Credit-reporting statement** — only say late payments may be reported if the CU actually reports.
- **Channel mapping.** Count `phone_call` attempts before relying on 7-in-7 legally; chats aren't calls.
- **Borrower timezone** comes from the seed default, not per-member data yet.
- **State law** (stricter frequency/hours/licensing) is not modeled.
- **Not legal advice** — get a compliance/legal review before live use.
