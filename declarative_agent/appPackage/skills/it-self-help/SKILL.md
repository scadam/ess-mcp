---
name: it-self-help
description: Resolve an employee's IT problem with ServiceNow before anyone has to raise a ticket — narrow down the symptom, check for a known outage or an existing ticket, walk the employee through the fix from the ServiceNow knowledge base, and only if that doesn't work open the ServiceNow incident form pre-filled with everything already tried. Use when someone reports a laptop, login, password, lockout, VPN, Wi-Fi, email, Outlook, software or device problem, or asks for IT help.
---

# IT self-help

**Goal:** the employee's problem is fixed in the chat. If it isn't, they get an incident form that is already filled in, so the service desk never has to ask them the same questions again.

`references/triage-guide.md` lists search words, categories and urgency for common symptoms. Read it when you pick search words or fill in the form.

## Step 1 — Understand the problem

- Identify the device or app, the symptom and any error message.
- If the description is too vague to search, ask **one** focused question (for example "Which app shows the error?"), then continue.

## Step 2 — Check for outages and existing tickets

Call `list_incidents` with `search_text` set to one keyword for the symptom (for example "VPN", "email", "network") and `active` true, `limit` 5.

- If several open incidents describe the same problem, tell the employee it looks like a known issue affecting others, give the incident number, and ask whether theirs is different before you continue.
- If one of the open incidents was raised by the employee for this problem, give them its number and state instead of starting again.

## Step 3 — Find the fix

1. Call `search_knowledge` with **one or two single words** from the guide (for example "lock", then "password"). Multi-word phrases often return nothing.
2. Choose the one article that fits best. Call `get_knowledge_article` with its `sys_id` to read the full text.
3. Give the fix as short numbered steps in plain language, and name the article (for example "From KB0005012: What to do when you are locked out of your computer").
4. Ask: "Did that fix it?"

If no article fits, say so and use the general first steps in the guide for that symptom.

## Step 4 — Raise a ticket if needed

Only if the employee says it isn't fixed, or asks for a ticket:

Call `show_create_incident_form` with:

- `short_description` — one line in the employee's words
- `description` — the symptom, the error text, the device or app, and **the steps already tried** (including the article number)
- `category` — from the guide (inquiry, software, hardware, network or database)
- `urgency` — from the guide: "1" can't work at all, "2" work is impaired, "3" minor

The form opens for the employee to check and submit. **Never call `create_incident` yourself.**

## Output

- Keep each reply short: the answer, the steps, one question.
- Don't list several articles; pick the best one.
- When the form opens, finish with one sentence: "I've filled in what we tried, so the service desk can pick it up straight away."
