$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
. .\infra\demo\environment.ps1
Assert-DemoSubscription
# One-off diagnosis job: sign-in checks against the ServiceNow instance with the vault's credentials; prints statuses only.
$code = @'
import httpx, os
base = os.environ["SERVICENOW_INSTANCE_URL"].rstrip("/")
cid, csec = os.environ["SERVICENOW_OAUTH_CLIENT_ID"], os.environ["SERVICENOW_OAUTH_CLIENT_SECRET"]
admin_pw, demo_pw = os.environ["SERVICENOW_OAUTH_PASSWORD"], os.environ.get("AUTOPILOT_DEMO_USER_PASSWORD", "")
print("demo password present:", bool(demo_pw), "length:", len(demo_pw))
def basic(user, password):
    r = httpx.get(base + "/api/now/table/incident", params={"sysparm_limit": 1, "sysparm_fields": "sys_id"},
                  auth=(user, password), headers={"Accept": "application/json"}, timeout=60)
    return r.status_code
def grant(user, password):
    r = httpx.post(base + "/oauth_token.do", data={"grant_type": "password", "client_id": cid, "client_secret": csec,
                   "username": user, "password": password}, headers={"Accept": "application/json"}, timeout=60)
    return r.status_code, "access_token" in r.text
print("basic admin:", basic("admin", admin_pw))
print("grant admin:", grant("admin", admin_pw))
print("basic kian.lambert:", basic("kian.lambert", demo_pw))
print("grant kian.lambert:", grant("kian.lambert", demo_pw))
token = httpx.post(base + "/oauth_token.do", data={"grant_type": "password", "client_id": cid, "client_secret": csec,
                   "username": "admin", "password": admin_pw}, headers={"Accept": "application/json"}, timeout=60).json()["access_token"]
auth = {"Authorization": "Bearer " + token, "Accept": "application/json"}
fields = "user_name,active,locked_out,failed_attempts,password_needs_reset,web_service_access_only,internal_integration_user,last_login_time,source,sys_updated_on,sys_updated_by"
for name in ("kian.lambert", "colin.ballinger"):
    r = httpx.get(base + "/api/now/table/sys_user", params={"sysparm_query": "user_name=" + name, "sysparm_fields": fields}, headers=auth, timeout=60)
    print(name, r.json().get("result"))
for prop in ("glide.basicauth.required.api", "glide.user.max_failed_login_attempts", "glide.authenticate.multifactor"):
    r = httpx.get(base + "/api/now/table/sys_properties", params={"sysparm_query": "name=" + prop, "sysparm_fields": "name,value"}, headers=auth, timeout=60)
    print("property", prop, r.json().get("result"))
r = httpx.get(base + "/api/now/table/sys_api_access_policy", params={"sysparm_fields": "name,active,rest_api,apply_to_all_rest_api_paths", "sysparm_limit": 20}, headers=auth, timeout=60)
print("api access policies:", r.status_code, r.json().get("result") if r.status_code == 200 else r.text[:200])
kian = httpx.post(base + "/oauth_token.do", data={"grant_type": "password", "client_id": cid, "client_secret": csec,
                  "username": "kian.lambert", "password": demo_pw}, headers={"Accept": "application/json"}, timeout=60).json()["access_token"]
as_kian = {"Authorization": "Bearer " + kian, "Accept": "application/json"}
for table in ("incident", "problem", "change_request", "sc_req_item", "sysapproval_approver", "kb_knowledge", "sc_cat_item",
              "alm_hardware", "cmdb_ci_computer", "task_sla", "sys_user", "sys_user_group", "sys_user_grmember",
              "incident_task", "sys_attachment", "sys_user_has_role", "sc_category"):
    r = httpx.get(base + "/api/now/table/" + table, params={"sysparm_limit": 3, "sysparm_fields": "sys_id"}, headers=as_kian, timeout=60)
    print("as kian", table, r.status_code, len(r.json().get("result", [])) if r.status_code == 200 else r.text[:120])
for path in ("/api/sn_sc/servicecatalog/items", "/api/sn_sc/servicecatalog/categories", "/api/sn_km_api/knowledge/articles"):
    r = httpx.get(base + path, params={"sysparm_limit": 3}, headers=as_kian, timeout=60)
    print("as kian", path, r.status_code, r.text[:80] if r.status_code != 200 else "ok")
r = httpx.get(base + "/api/now/table/sys_user_has_role", params={"sysparm_query": "user.user_name=kian.lambert^state=active", "sysparm_fields": "role.name", "sysparm_limit": 40}, headers=auth, timeout=60)
print("kian roles:", sorted({row.get("role.name") for row in r.json().get("result", [])}))
r = httpx.get(base + "/api/now/table/sys_multifactor_criteria", params={"sysparm_fields": "name,active,roles,groups,users", "sysparm_limit": 10}, headers=auth, timeout=60)
print("mfa criteria:", r.status_code, r.json().get("result") if r.status_code == 200 else r.text[:150])
import sys, time
sys.stdout.flush()
time.sleep(90)
'@
$job = 'job-desk-snprobe'
$source = Get-DemoApp essmcp-caldova-servicenow
$identity = @($source.identity.userAssignedIdentities.PSObject.Properties.Name)[0]
$secrets = @($source.properties.configuration.secrets | ForEach-Object { @{ name = $_.name; keyVaultUrl = $_.keyVaultUrl; identity = $identity } })
$secrets += @{ name = 'demo-user-password'; keyVaultUrl = "https://$DemoVault.vault.azure.net/secrets/servicenow-demo-user-password"; identity = $identity }
$variables = @($source.properties.template.containers[0].env | ForEach-Object {
  if ($_.secretRef) { @{ name = $_.name; secretRef = $_.secretRef } } else { @{ name = $_.name; value = $_.value } } })
$variables += @{ name = 'AUTOPILOT_DEMO_USER_PASSWORD'; secretRef = 'demo-user-password' }
$definition = @{
  location = $source.location
  identity = @{ type = 'UserAssigned'; userAssignedIdentities = @{ $identity = @{} } }
  properties = @{
    environmentId = $source.properties.environmentId; workloadProfileName = 'Consumption'
    configuration = @{ triggerType = 'Manual'; replicaTimeout = 600; replicaRetryLimit = 0
      manualTriggerConfig = @{ parallelism = 1; replicaCompletionCount = 1 }; secrets = $secrets
      registries = @(@{ server = $DemoRegistry; identity = $identity }) }
    template = @{ containers = @(@{ name = 'probe'; image = $source.properties.template.containers[0].image
      command = @('python', '-u', '-c', $code); env = $variables; resources = @{ cpu = 0.5; memory = '1Gi' } }) }
  }
}
$execution = Start-DemoJob -Job $job -Definition $definition -Label 'sign-in probe'
"execution=$execution"
exit 0
