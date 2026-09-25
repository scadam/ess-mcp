# Resolution playbooks

Fixes and caller wording by triage topic. Adapt the steps to what the caller actually wrote; keep them short and
numbered. Work notes record the diagnosis so a person never has to re-triage.

## T1 — known fixes (close code: Workaround provided unless stated)

**vpn-client** — VPN client won't start after a software update. The update usually breaks the client's service.
1. Restart the laptop. 2. Open Company Portal, find the VPN client and choose Reinstall. 3. If it still won't start,
Settings > Windows Update > Update history > Uninstall updates, remove the most recent update and restart.
Work note: note the update date; if a second caller reports it, it becomes a problem for the patch team.

**desk-phone** — No dial tone. 1. Check the cable runs from the wall to the phone's LAN port (not the PC port).
2. Unplug the phone for 10 seconds and plug it back in. 3. If the screen stays blank, try another wall port — the
port may have lost power. Reply if none of this works and the incident is dispatched to the field team.

**read-only-file** — Office file opens read-only. 1. Close the file and reopen it; if someone else has it open, it
opens read-only until they close it. 2. Look for an "Enable Editing" or "Checked out" bar and use it. 3. If the file
now says you have view access only, its owner can re-share it with edit rights (File > Share). Permission changes
are made by the file's owner, not the service desk.

**virtualization** — 64-bit VM won't start (close code: Solution provided). 64-bit guests need a 64-bit host and
hardware virtualisation. 1. Enable Intel VT-x / AMD-V in the BIOS/UEFI settings. 2. If Hyper-V is on, use Hyper-V
or turn it off for other hypervisors. 3. Windows 7 is out of support: use the current Windows developer VM image instead.

**weather** — WeatherBug icon gone (close code: Solution provided). WeatherBug is no longer supported. Use the
Weather widget on the Windows taskbar, or install MSN Weather from Company Portal.

**wiki-posting** — Can't edit a wiki page. Editing needs contributor rights on the space, and a page can be locked
while someone else edits it. 1. Check you are signed in. 2. If the Edit option is missing, ask the space owner
(shown in the page information) for contributor rights. 3. If it says the page is locked, try again later.

**software-removal** — Remove a hotfix. 1. Settings > Windows Update > Update history > Uninstall updates. 2. Select
the most recent update (note its KB number) and choose Uninstall, then restart. 3. Pause updates for 7 days while the
patch team checks it. Work note: record the KB number for the patch team.

## T1 — how-tos (close code: Solution provided)

**how-to (Outlook sub-folder)** — Right-click the Inbox itself (not a message) and choose New Folder. In the new
Outlook or Outlook on the web, select the three dots next to Inbox and choose Create subfolder.

## T1 — requests

**mobile-device** — Lost or broken phone. Order the matching phone for the caller. Work note: confirm the lost device
was wiped and the line suspended (from the caller's words), and ask device management to retire it. Close code
Resolved by request, with the REQ number in the close notes and the comment.

**new-service / new machine** — Ask which device from the catalog (Standard Laptop, Development Laptop (PC),
Developer Laptop (Mac)) and whether they need setup help; put the incident on hold awaiting the caller.

**file-share-access / database-access** — Access requests. Fulfil through the catalog; if no item fits, it is a
catalog gap (see the policy). Never change permissions yourself.

**laptop-memory** — A physical upgrade: dispatch to Hardware with the model, the software that needs the memory
and the caller's deadline.

## T2 — outages (keep open, linked to the problem)

**sap** — Several SAP modules failing at once points to the SAP application server, SSO or the SAP GUI release, not
the laptops. Workaround: SAP Fiori in the browser where available. Problem group: Software.

**email** — Exchange connection and performance reports together point to the mail service. Workaround: Outlook on
the web. Problem group: Software.

**network** — Wireless and network storage failures together point to the campus network. Workaround: a wired
connection; files synced to OneDrive stay available. Problem group: Network.

**web-defect** — A reproducible defect on a web page is a known error: open a problem with the page, browsers and
error, and give the caller a workaround (another browser or the direct link).

## T2 — diagnose and route

Write the work note as a hand-over: symptom in the caller's words, scope (one user or many), likely cause, what you
ruled out, related records, and the next step. The caller's comment gives them a workaround and says which team has it.

- **app-access** — Correct credentials but login fails: account lock-out, SSO or licence assignment. Workaround: sign
  in through the SSO portal after clearing cached credentials.
- **performance** — Slow pages for one user: check VPN, Wi-Fi and browser cache first; many users means a problem.
- **enhancement** — Requests to change a system's screens or fields are demand, not incidents: route to the owning
  platform team with the requirements summarised.
- **service-down** — A single report of a server down: route to the server's group, keep priority, and correlate any
  later reports to a problem.

## Field dispatch

**facilities** — Water, fire, smoke or power near equipment is a safety issue. Dispatch to Hardware with urgency 1,
tell the caller an engineer is on the way and not to touch powered equipment.
