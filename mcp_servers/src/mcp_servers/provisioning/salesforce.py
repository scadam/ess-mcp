"""Idempotent provisioning for the case desk in the configured Salesforce org.

Modes (python -m mcp_servers.provisioning.salesforce <mode>):
  setup  deploy (Metadata API) a protected custom setting, a remote site for the Autopilot host, an Apex trigger on
         Case and CaseComment and a Queueable that signs and posts each change as a doorbell, with its test class;
         then store the webhook URL and secret in the setting's org defaults.
  demo   raise the demo compliance cases (gifts and hospitality, personal account dealing).
  reset  close the open demo cases so the next demo raises fresh ones.
Needs the Salesforce MCP server's settings plus AUTOPILOT_HOST_URL and AUTOPILOT_WEBHOOK_SECRET. Prints no secrets.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import uuid
import zipfile
from typing import Any, Dict

from ..auth import resolve_salesforce_token
from ..http import create_async_client
from ..salesforce.tools import _COMPLIANCE_TYPES

API = "59.0"
DOMAIN = "Caldova74201480.OnMicrosoft.com"
_META = '<?xml version="1.0" encoding="UTF-8"?>\n'
_NS = 'xmlns="http://soap.sforce.com/2006/04/metadata"'


def _apex_types() -> str:
    return ", ".join("'" + value.replace("'", "\\'") + "'" for value in _COMPLIANCE_TYPES)


WEBHOOK_CLASS = """public without sharing class AutopilotWebhook implements Queueable, Database.AllowsCallouts {
    private static final Set<String> TYPES = new Set<String>{ %TYPES% };
    private final List<String> bodies;

    public AutopilotWebhook(List<String> bodies) {
        this.bodies = bodies;
    }

    public static void onCases(List<Case> cases, Boolean inserted) {
        Set<Id> ids = new Set<Id>();
        for (Case item : cases) {
            if (item.Type != null && TYPES.contains(item.Type) && item.Origin != 'Email') {
                ids.add(item.Id);
            }
        }
        if (!ids.isEmpty()) {
            enqueue(build(ids, inserted ? 'insert' : 'update', new Map<Id, CaseComment>()));
        }
    }

    public static void onComments(List<CaseComment> comments) {
        Map<Id, CaseComment> latest = new Map<Id, CaseComment>();
        for (CaseComment comment : comments) {
            latest.put(comment.ParentId, comment);
        }
        enqueue(build(latest.keySet(), 'update', latest));
    }

    private static List<String> build(Set<Id> ids, String operation, Map<Id, CaseComment> comments) {
        Map<Id, String> authors = new Map<Id, String>();
        Set<Id> authorIds = new Set<Id>();
        for (CaseComment comment : comments.values()) {
            authorIds.add(comment.CreatedById);
        }
        for (User author : [SELECT Id, Username FROM User WHERE Id IN :authorIds]) {
            authors.put(author.Id, author.Username);
        }
        List<String> bodies = new List<String>();
        for (Case item : [SELECT Id, CaseNumber, Subject, Type, Origin, SystemModstamp, LastModifiedBy.Username,
                                 SuppliedName, SuppliedEmail, Contact.Name, Contact.Email
                          FROM Case WHERE Id IN :ids]) {
            if (item.Type == null || !TYPES.contains(item.Type) || item.Origin == 'Email') {
                continue;
            }
            Map<String, Object> payload = new Map<String, Object>{
                'event_id' => item.Id + ':' + item.SystemModstamp.getTime(),
                'case_id' => item.Id, 'case_number' => item.CaseNumber, 'operation' => operation,
                'subject' => item.Subject, 'last_modified_by' => item.LastModifiedBy.Username,
                'supplied_email' => item.SuppliedEmail,
                'contact' => new Map<String, Object>{
                    'name' => item.Contact != null ? item.Contact.Name : item.SuppliedName,
                    'email' => item.Contact != null ? item.Contact.Email : item.SuppliedEmail
                }
            };
            CaseComment comment = comments.get(item.Id);
            if (comment != null) {
                payload.put('event_id', 'comment:' + comment.Id);
                payload.put('comment', new Map<String, Object>{
                    'by' => authors.get(comment.CreatedById),
                    'text' => comment.CommentBody == null ? '' : comment.CommentBody.left(4000),
                    'public' => comment.IsPublished
                });
            }
            bodies.add(JSON.serialize(payload));
        }
        return bodies;
    }

    private static void enqueue(List<String> bodies) {
        if (!bodies.isEmpty() && Limits.getQueueableJobs() < Limits.getLimitQueueableJobs()) {
            System.enqueueJob(new AutopilotWebhook(bodies));
        }
    }

    public void execute(QueueableContext context) {
        Autopilot_Settings__c settings = Autopilot_Settings__c.getOrgDefaults();
        if (settings == null || String.isBlank(settings.Webhook_Url__c) || String.isBlank(settings.Webhook_Secret__c)) {
            return;
        }
        Http http = new Http();
        for (String body : bodies) {
            String stamp = String.valueOf(Datetime.now().getTime() / 1000);
            Blob mac = Crypto.generateMac('HmacSHA256', Blob.valueOf(stamp + '.' + body), Blob.valueOf(settings.Webhook_Secret__c));
            HttpRequest request = new HttpRequest();
            request.setEndpoint(settings.Webhook_Url__c);
            request.setMethod('POST');
            request.setTimeout(15000);
            request.setHeader('Content-Type', 'application/json');
            request.setHeader('X-Autopilot-Timestamp', stamp);
            request.setHeader('X-Autopilot-Signature', 'v1=' + EncodingUtil.convertToHex(mac));
            request.setBody(body);
            try {
                HttpResponse response = http.send(request);
                if (response.getStatusCode() >= 300) {
                    System.debug(LoggingLevel.WARN, 'Autopilot webhook returned ' + response.getStatusCode());
                }
            } catch (CalloutException error) {
                System.debug(LoggingLevel.WARN, 'Autopilot webhook failed: ' + error.getMessage());
            }
        }
    }
}
"""

TEST_CLASS = """@IsTest
private class AutopilotWebhookTest {
    private class Recorder implements HttpCalloutMock {
        public List<HttpRequest> requests = new List<HttpRequest>();
        public HttpResponse respond(HttpRequest request) {
            requests.add(request);
            HttpResponse response = new HttpResponse();
            response.setStatusCode(202);
            response.setBody('{"accepted":true}');
            return response;
        }
    }

    @TestSetup
    static void settings() {
        insert new Autopilot_Settings__c(SetupOwnerId = UserInfo.getOrganizationId(),
            Webhook_Url__c = 'https://autopilot.example.com/api/events/salesforce',
            Webhook_Secret__c = 'abcdefghijklmnopqrstuvwxyz0123456789ABCD');
    }

    @IsTest
    static void signsAndPostsComplianceCases() {
        Recorder recorder = new Recorder();
        Test.setMock(HttpCalloutMock.class, recorder);
        Test.startTest();
        Case item = new Case(Subject = 'Gift pre-approval', Type = 'Gifts & Entertainment', Origin = 'Web',
                             SuppliedName = 'Test Person', SuppliedEmail = 'person@example.com');
        insert item;
        Test.stopTest();
        System.assertEquals(1, recorder.requests.size());
        HttpRequest request = recorder.requests[0];
        String stamp = request.getHeader('X-Autopilot-Timestamp');
        Blob mac = Crypto.generateMac('HmacSHA256', Blob.valueOf(stamp + '.' + request.getBody()),
                                      Blob.valueOf('abcdefghijklmnopqrstuvwxyz0123456789ABCD'));
        System.assertEquals('v1=' + EncodingUtil.convertToHex(mac), request.getHeader('X-Autopilot-Signature'));
        Map<String, Object> payload = (Map<String, Object>) JSON.deserializeUntyped(request.getBody());
        System.assertEquals('insert', payload.get('operation'));
        System.assertEquals(item.Id, (Id) payload.get('case_id'));
    }

    @IsTest
    static void commentsCarryTheAuthorAndText() {
        Recorder recorder = new Recorder();
        Test.setMock(HttpCalloutMock.class, recorder);
        Test.startTest();
        Case item = new Case(Subject = 'PAD pre-clearance', Type = 'Market Abuse / Insider Trading', Origin = 'Web');
        insert item;
        insert new CaseComment(ParentId = item.Id, CommentBody = 'Adding the broker', IsPublished = true);
        Test.stopTest();
        Map<String, Object> comment;
        for (HttpRequest request : recorder.requests) {
            Map<String, Object> payload = (Map<String, Object>) JSON.deserializeUntyped(request.getBody());
            if (payload.containsKey('comment')) {
                comment = (Map<String, Object>) payload.get('comment');
            }
        }
        System.assertNotEquals(null, comment);
        System.assertEquals('Adding the broker', comment.get('text'));
        System.assertEquals(UserInfo.getUserName(), comment.get('by'));
    }

    @IsTest
    static void ignoresOtherCases() {
        Recorder recorder = new Recorder();
        Test.setMock(HttpCalloutMock.class, recorder);
        Test.startTest();
        insert new Case(Subject = 'Printer jam', Origin = 'Email', Type = 'Gifts & Entertainment');
        insert new Case(Subject = 'No type', Origin = 'Web');
        Test.stopTest();
        System.assertEquals(0, recorder.requests.size());
    }
}
"""

CASE_TRIGGER = """trigger AutopilotCaseTrigger on Case (after insert, after update) {
    AutopilotWebhook.onCases(Trigger.new, Trigger.isInsert);
}
"""
COMMENT_TRIGGER = """trigger AutopilotCaseCommentTrigger on CaseComment (after insert) {
    AutopilotWebhook.onComments(Trigger.new);
}
"""
SETTING = f"""{_META}<CustomObject {_NS}>
    <customSettingsType>Hierarchy</customSettingsType>
    <label>Autopilot Settings</label>
    <visibility>Protected</visibility>
    <fields>
        <fullName>Webhook_Url__c</fullName>
        <label>Webhook URL</label>
        <length>255</length>
        <required>false</required>
        <type>Text</type>
    </fields>
    <fields>
        <fullName>Webhook_Secret__c</fullName>
        <label>Webhook Secret</label>
        <length>255</length>
        <required>false</required>
        <type>Text</type>
    </fields>
</CustomObject>
"""


def _remote_site(host: str) -> str:
    return (f"{_META}<RemoteSiteSetting {_NS}>\n    <description>Group Functions Autopilot case desk webhook</description>\n"
            f"    <disableProtocolSecurity>false</disableProtocolSecurity>\n    <isActive>true</isActive>\n"
            f"    <url>{host}</url>\n</RemoteSiteSetting>\n")


def _meta(kind: str) -> str:
    return f"{_META}<{kind} {_NS}>\n    <apiVersion>{API}</apiVersion>\n    <status>Active</status>\n</{kind}>\n"


def package_zip(host: str) -> bytes:
    files = {
        "package.xml": (f"{_META}<Package {_NS}>\n"
                        "    <types><members>AutopilotWebhook</members><members>AutopilotWebhookTest</members><name>ApexClass</name></types>\n"
                        "    <types><members>AutopilotCaseTrigger</members><members>AutopilotCaseCommentTrigger</members><name>ApexTrigger</name></types>\n"
                        "    <types><members>Autopilot_Settings__c</members><name>CustomObject</name></types>\n"
                        "    <types><members>Autopilot_Host</members><name>RemoteSiteSetting</name></types>\n"
                        f"    <version>{API}</version>\n</Package>\n"),
        "objects/Autopilot_Settings__c.object": SETTING,
        "remoteSiteSettings/Autopilot_Host.remoteSite": _remote_site(host),
        "classes/AutopilotWebhook.cls": WEBHOOK_CLASS.replace("%TYPES%", _apex_types()),
        "classes/AutopilotWebhook.cls-meta.xml": _meta("ApexClass"),
        "classes/AutopilotWebhookTest.cls": TEST_CLASS,
        "classes/AutopilotWebhookTest.cls-meta.xml": _meta("ApexClass"),
        "triggers/AutopilotCaseTrigger.trigger": CASE_TRIGGER,
        "triggers/AutopilotCaseTrigger.trigger-meta.xml": _meta("ApexTrigger"),
        "triggers/AutopilotCaseCommentTrigger.trigger": COMMENT_TRIGGER,
        "triggers/AutopilotCaseCommentTrigger.trigger-meta.xml": _meta("ApexTrigger"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _report(step: str, **values: Any) -> None:
    print(json.dumps({"step": step, **values}), flush=True)


class Org:
    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await resolve_salesforce_token(None)
        async with create_async_client(timeout=120.0) as client:
            response = await client.request(method, f"{token.instance_url}{path}", headers={
                "Authorization": f"Bearer {token.access_token}", "Accept": "application/json",
                **kwargs.pop("headers", {})}, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path.split('?')[0]} failed: HTTP {response.status_code} {response.text[:600]}")
        return response.json() if response.content else {}

    async def query(self, soql: str) -> list[Dict[str, Any]]:
        return (await self.request("GET", f"/services/data/v{API}/query", params={"q": soql})).get("records", [])


async def setup(org: Org) -> None:
    host = os.environ["AUTOPILOT_HOST_URL"].rstrip("/")
    secret = os.environ["AUTOPILOT_WEBHOOK_SECRET"]
    if len(secret) < 32:
        raise RuntimeError("The webhook secret is too short.")
    who = await org.request("GET", "/services/oauth2/userinfo")
    _report("integration_user", username=who.get("preferred_username"), organization=who.get("organization_id"))
    boundary = "autopilot-" + uuid.uuid4().hex
    options = {"deployOptions": {"singlePackage": True, "rollbackOnError": True, "testLevel": "RunSpecifiedTests",
                                 "runTests": ["AutopilotWebhookTest"]}}
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"json\"\r\nContent-Type: application/json\r\n\r\n"
            f"{json.dumps(options)}\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"autopilot.zip\"\r\nContent-Type: application/zip\r\n\r\n").encode() + package_zip(host) + \
        f"\r\n--{boundary}--\r\n".encode()
    started = await org.request("POST", f"/services/data/v{API}/metadata/deployRequest", content=body,
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    deploy_id = started["id"]
    _report("deploy_started", id=deploy_id)
    result: Dict[str, Any] = {}
    for _ in range(90):
        await asyncio.sleep(10)
        result = (await org.request("GET", f"/services/data/v{API}/metadata/deployRequest/{deploy_id}",
                                    params={"includeDetails": "true"})).get("deployResult", {})
        if result.get("done"):
            break
    details = result.get("details") or {}
    failures = [{"component": item.get("fullName"), "problem": item.get("problem")}
                for item in details.get("componentFailures") or [] if item.get("problem")]
    tests = (details.get("runTestResult") or {})
    test_failures = [{"test": f"{item.get('name')}.{item.get('methodName')}", "message": item.get("message")}
                     for item in tests.get("failures") or []]
    _report("deploy_finished", status=result.get("status"), failures=failures[:10], test_failures=test_failures[:10],
            tests_run=tests.get("numTestsRun"))
    if result.get("status") != "Succeeded":
        raise RuntimeError("The Salesforce deployment did not succeed.")
    organization = who.get("organization_id")
    existing = await org.query(f"SELECT Id FROM Autopilot_Settings__c WHERE SetupOwnerId = '{organization}'")
    values = {"Webhook_Url__c": f"{host}/api/events/salesforce", "Webhook_Secret__c": secret}
    if existing:
        await org.request("PATCH", f"/services/data/v{API}/sobjects/Autopilot_Settings__c/{existing[0]['Id']}", json=values)
        _report("settings", state="updated")
    else:
        await org.request("POST", f"/services/data/v{API}/sobjects/Autopilot_Settings__c",
                          json={"SetupOwnerId": organization, **values})
        _report("settings", state="created")


DEMO_CASES = [
    {"Subject": "Pre-approval: Wimbledon debenture seats from TechDirect", "Type": "Gifts & Entertainment",
     "SuppliedName": "Colin Ballinger", "SuppliedEmail": f"ColinB@{DOMAIN}", "Priority": "Medium", "Origin": "Web",
     "Description": ("TechDirect's account director has offered me two Centre Court debenture seats with lunch on "
                     "3 July (about £420 per person). I manage the TechDirect relationship and approve their invoices. "
                     "Can I accept, and do I need to register it?")},
    {"Subject": "Pre-clearance: buy 500 Northbridge Renewables shares", "Type": "Market Abuse / Insider Trading",
     "SuppliedName": "Aisha West", "SuppliedEmail": f"AishaW@{DOMAIN}", "Priority": "Medium", "Origin": "Web",
     "Description": ("I'd like to buy 500 Northbridge Renewables (NBR) shares in my personal ISA this week, roughly "
                     "£6,200. Please confirm I'm cleared to trade.")},
]


async def demo(org: Org) -> None:
    for case in DEMO_CASES:
        subject = case["Subject"].replace("'", "\\'")
        existing = await org.query(f"SELECT Id, CaseNumber FROM Case WHERE Subject = '{subject}' AND IsClosed = false")
        if existing:
            _report("case", number=existing[0]["CaseNumber"], state="exists")
            continue
        created = await org.request("POST", f"/services/data/v{API}/sobjects/Case", json=case)
        number = (await org.query(f"SELECT CaseNumber FROM Case WHERE Id = '{created['id']}'"))[0]["CaseNumber"]
        _report("case", number=number, type=case["Type"], state="created")


async def reset(org: Org) -> None:
    """Closed by the integration user, so the host ignores the trigger's echo."""
    for case in DEMO_CASES:
        subject = case["Subject"].replace("'", "\\'")
        for row in await org.query(f"SELECT Id, CaseNumber FROM Case WHERE Subject = '{subject}' AND IsClosed = false"):
            await org.request("PATCH", f"/services/data/v{API}/sobjects/Case/{row['Id']}", json={"Status": "Closed"})
            _report("case", number=row["CaseNumber"], state="closed")


async def main(mode: str) -> None:
    org = Org()
    if mode == "setup":
        await setup(org)
    elif mode == "demo":
        await demo(org)
    elif mode == "reset":
        await reset(org)
    else:
        raise SystemExit("usage: python -m mcp_servers.provisioning.salesforce setup|demo|reset")
    _report("done", mode=mode)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
