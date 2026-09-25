# User access review standard (ServiceNow, privileged access)

## Frequency and scope
- Quarterly. Default scope: the groups and roles below. A manager's instruction may narrow or add to it.

| Group or role | Why it is privileged | Owner | Owner email |
|---|---|---|---|
| role: admin | Full platform administration | Elvia Atkins (VP, IT & Digital) | ElviaA@Caldova74201480.OnMicrosoft.com |
| role: security_admin | Security configuration, elevated roles | Kadji Bell (Security Operations Manager) | KadjiB@Caldova74201480.OnMicrosoft.com |
| group: CAB Approval | Approves production changes | Kadji Bell | KadjiB@Caldova74201480.OnMicrosoft.com |
| group: Change Management | Raises and implements changes | Elvia Atkins | ElviaA@Caldova74201480.OnMicrosoft.com |
| group: Database | Direct database administration | Kenvin Sturis (Data Governance & Analytics) | KenvinS@Caldova74201480.OnMicrosoft.com |

Service accounts (integration users such as `admin` used by integrations) are listed but decided by the platform
owner with the integration's name as the reason.

## Flags
- **Leaver**: the user is inactive but still holds the membership or role → remove unless the owner gives a reason.
- **Dormant**: no login in the last 90 days → remove unless the owner confirms a current need.
- **SoD conflict**: the same person in both **Change Management** and **CAB Approval** (can raise and approve their
  own change) → one must be removed, or a compensating control named.
- **Direct privileged grant**: admin or security_admin granted directly rather than through a group → review.

## Evidence an auditor expects
Population with the date and source, each owner's decision with timestamp, the removals with the approval and time
of removal, and any exceptions with the reason and who accepted them.
