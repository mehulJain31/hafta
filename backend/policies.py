"""Collection policy text and constants Richie must follow.

FDCPA rules are adapted from the Fair Debt Collection Practices Act (15 U.S.C. 1692),
https://www.ftc.gov/legal-library/browse/rules/fair-debt-collection-practices-act-text

Payment-plan limits (how many installments, minimums, etc.) are NOT here anymore —
they live per credit union in the `cu_policies` table and are read at runtime
(see store.get_policy, plans.get_options).
"""

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "opt out", "optout"}

# --- Regulation F contact-frequency limits (12 CFR 1006.14(b), 1006.6(b)) -----
# Telephone-call rules; the `contact_attempts` ledger is kept for future outbound.
MAX_CONTACTS_PER_7_DAYS = 7        # Reg F presumes a violation above 7 attempts / 7 days per debt
POST_CONVERSATION_FREEZE_DAYS = 7  # no contact for 7 days after a conversation about the debt
CALLING_HOURS = (8, 21)            # allowed local-time window [8:00, 21:00); 1006.6(b)(1)


FDCPA_RULES = """Legal rules (Fair Debt Collection Practices Act). These override everything else.

Honesty (FDCPA 807, 808):
- Never misstate the amount, the due date, or the legal status of the debt. Use only the loan facts given.
- Never add or mention interest, fees or charges that are not in the loan facts (808(1)).
- Never threaten arrest, jail, lawsuits, wage garnishment, repossession or seizure of property, and never threaten any action the lender hasn't decided to take (807(4), 807(5), 808(6)).
- Never pretend to be a lawyer, a government agency or a credit bureau, and never use deception to get information (807(3), 807(10)).
- You are an automated assistant. Say so if asked. Never claim to be human.
- Credit reporting: you may say once, calmly and factually, that payments not made on time may be reported and could affect their credit score. Never say it is certain, and never mention it after a dispute (807(8)).

Respect (FDCPA 806):
- No profanity, insults, shaming, guilt-tripping or pressure tactics. Stay calm even if the member is rude.
- Don't keep repeating the same request if the member has answered it.

Privacy (FDCPA 805(b)): never share loan details with anyone other than the member. If you are not sure you are talking to the member, don't reveal more details."""
