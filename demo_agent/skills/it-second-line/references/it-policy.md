# IT second-line policy (Caldova Group Technology)

## Identity and ownership
- The caller is the person in the incident's Caller field; their verified work email is the identity anchor.
- An account may be reset or unlocked only for its owner: the account's registered email must equal the caller's.
- Requests on behalf of someone else: refuse politely; the account owner or their line manager must raise it.
- Never ask for, accept, store or repeat a password, one-time code or security answer, in any channel.
- Signs of compromise (many failed sign-ins in a short time, sign-ins from an unexpected country, the caller did
  not trigger the lock-out): do not reset; escalate to **Security Operations** as a possible account compromise.

## Account types
| Account | Examples | Who resets |
|---|---|---|
| Directory (SSO) | Windows, Microsoft 365, Teams, VPN | The caller, through self-service password reset (aka.ms/sspr) |
| Local application accounts held in ServiceNow | TreasuryWorks (legacy treasury), TradeSupport Console, Branch Teller Admin | Second line, with `it__reset_app_password` |
| Privileged (admin, security_admin, user_admin, impersonator) | Any | Privileged Access Management only |

## Hardware
| Situation | Action |
|---|---|
| Fault confirmed by diagnostics, device under warranty | Warranty claim task (Hardware Support); loaner if the caller cannot work |
| Out of warranty, battery capacity below 60%, disk failing, or repair cost > 40% of replacement | Replace: order the standard device for the role; deskside swap task with data transfer |
| No diagnostic report | Ask the caller to run the vendor diagnostic and attach the report |
| Physical damage from misuse | Replace, and note it for the asset owner; no warranty claim |

- Standard devices: **Standard Laptop** for most roles; **Developer Laptop** for engineering, data and quant roles.
- Loaner: catalog item **Loaner Laptop (up to 10 working days)**.
- Vendor diagnostics: Dell SupportAssist or ePSA (F12 at start-up), Lenovo Vantage, `powercfg /batteryreport` on
  Windows for batteries. Ask the caller to attach the report file to the incident.

## Service levels
| Priority | Respond | Resolve |
|---|---|---|
| P1 (many people or a critical business service) | 15 min | 4 h |
| P2 (one person cannot work) | 1 h | 1 working day |
| P3 (degraded, workaround exists) | 4 h | 3 working days |
| P4 (request, question) | 1 working day | 5 working days |

## Escalation groups
Security Operations · Privileged Access Management · Network Operations · Hardware Support · Deskside Support ·
Application Support (Treasury) · End User Computing.

## Closing
Resolve with close code **Solution provided** (or **Workaround provided**) and notes a technician could reuse.
The case closes when the caller confirms or the confirmation window passes.
