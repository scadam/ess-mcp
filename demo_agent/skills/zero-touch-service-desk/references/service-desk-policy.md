# Service desk policy — zero-touch operating model

The aim is that no person triages, diagnoses, communicates about or fulfils an incident. People do only what
software can't: physical work, engineering fixes, and the few decisions reserved below. Every incident that
reached the desk is also a signal that self-service failed, so each run closes the gap that let it through.

## Tiers

| Tier | Who | What |
|---|---|---|
| T0 | Self-service portal, Copilot, knowledge | Deflects the incident before it is raised. You improve this tier with catalog items and knowledge drafts. |
| T1 | You | Known fixes, how-tos, requests fulfilled through the catalog, queue hygiene. |
| T2 | You | Correlation across incidents, problem records, diagnosis, workarounds, hand-over packs. |
| T3 / field | Engineering and field teams | The fix itself when it needs hands, code or a change. They receive your diagnosis, not a raw ticket. |

## Authority

**You do without asking** (pre-approved, checked against the triage plan by `scripts/authorise.py`):

- Comment to callers and add work notes on any incident in the triaged queue.
- Resolve incidents the plan marks `resolve` or `order_and_resolve`, with a close code, close notes and a caller comment.
- Cancel automated test records (ATF) found in the live queue.
- Open a problem for a cluster of two or more incidents with the same fault (P1 when three or more), and link the
  cluster's incidents to it. Reuse an open problem when one already covers the fault.
- Order a catalog item on the caller's behalf (`requested_for` = the caller) when it matches the request exactly
  and costs no more than $1,500. One item, quantity 1.
- Build a catalog item — inactive — when two or more people raised incidents for something the catalog doesn't offer.
- Draft knowledge articles (drafts only) for fixes you used that have no article.
- Route engineering or field work to the owning group with a complete diagnosis.

**Needs a person's approval** (proposed; you carry on with the rest):

- Publishing a catalog item (`set_catalog_item_active`) — the catalog owner decides.
- Anything the check declines or that exceeds the budget.

**Never**: close an incident without telling the caller; change priority to improve SLA figures; cancel a real
request; order for anyone but the caller; delete records; change permissions, roles or credentials; touch
records outside the triaged queue; publish knowledge.

## Resolution codes

| Situation | Close code |
|---|---|
| How-to answered | Solution provided |
| Known fix or workaround given | Workaround provided |
| Fulfilled through a catalog request | Resolved by request |
| Stale (no update for more than 180 days, not part of an outage) | No resolution provided |

Stale closures always invite the caller to reply to reopen, and point to self-service when an item exists or is
being built.

## Outages

Two or more incidents about the same service are one fault. Open (or reuse) one problem, link every incident to it,
and tell each caller: there is a known problem, the workaround, and that the incident closes when the problem is
fixed. Keep the incidents open — the problem's resolution closes them ("Resolved by problem").

## Catalog gaps

A request that arrives as an incident means the catalog lacks something. With two or more such requests, build the
item from the triage spec: clear name, what it's for, what happens after ordering, the questions a fulfiller would
otherwise have to ask, and the fulfilment group. It starts inactive; propose publishing it. With one request, suggest
it in the report only.

When ordering, fill the item's questions from what the caller wrote. If a mandatory answer is missing, ask the caller
(comment, state `on_hold`) instead of guessing.

## Communication standards

Caller comments (`comments`) use `templates/caller-update.md`: plain English, what we found, what we did, what to do
now, how to reopen. No internal jargon, blame or guessed dates. Work notes (`work_notes`) carry the evidence:
classification, related records, what was ruled out and the next step for whoever picks it up.
