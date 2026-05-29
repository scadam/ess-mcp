<#
.SYNOPSIS
    Register the ESS demo tenant's custom Sensitive Information Types (SITs)
    in Microsoft Purview so they show up in DSPM for AI Activity Explorer.

.DESCRIPTION
    Creates a single Rule Package in the Security & Compliance Center that
    declares four custom SITs the hosted agent emits in its telemetry:

      * ESS Workday Employee ID    -> EMP-NNNNNN
      * ESS ServiceNow Case Number -> (INC|CHG|REQ|RITM|CASE)NNNNNNN
      * ESS Project Codename       -> "Wingtip Acquisition" / "Project Icarus"
      * ESS PIP Marker             -> "Performance Improvement Plan" / "PIP"

    Once the package is published, DSPM-for-AI's "Sensitive info type"
    column will populate with these names for runs whose captured prompt or
    response content matches.

    To remove: pass -Unregister.

.PARAMETER Unregister
    Remove the rule package from the tenant.

.EXAMPLE
    Connect-IPPSSession -UserPrincipalName admin@M365CPI81302533.onmicrosoft.com
    .\register-purview-sits.ps1

.NOTES
    Requires the ExchangeOnlineManagement PowerShell module (>= 3.x) and
    Global Admin or Compliance Administrator on the tenant. Cmdlets:
      - New-DlpSensitiveInformationTypeRulePackage
      - Set-DlpSensitiveInformationTypeRulePackage
      - Get-DlpSensitiveInformationTypeRulePackage
      - Remove-DlpSensitiveInformationTypeRulePackage
#>

[CmdletBinding()]
param(
    [switch] $Unregister
)

$ErrorActionPreference = 'Stop'

# Stable identifiers — DO NOT regenerate once published, otherwise Purview
# treats the SITs as new types and existing classifications detach.
$PackageId   = 'a7f3c401-2a3a-4d5e-9c8c-ab1cdef00001'
$EmployeeId  = 'b1e2c302-aaaa-4d5e-9c8c-ab1cdef00002'
$IncidentId  = 'b1e2c302-bbbb-4d5e-9c8c-ab1cdef00003'
$CodenameId  = 'b1e2c302-cccc-4d5e-9c8c-ab1cdef00004'
$PipId       = 'b1e2c302-dddd-4d5e-9c8c-ab1cdef00005'
$PublisherId = 'b1e2c302-9999-4d5e-9c8c-ab1cdef00006'

if (-not (Get-Command Connect-IPPSSession -ErrorAction SilentlyContinue)) {
    throw "ExchangeOnlineManagement module not installed. Run: Install-Module ExchangeOnlineManagement -Scope CurrentUser"
}

if (-not (Get-Command New-DlpSensitiveInformationTypeRulePackage -ErrorAction SilentlyContinue)) {
    throw "Compliance cmdlets not loaded. Run: Connect-IPPSSession -UserPrincipalName <admin-upn> first."
}

if ($Unregister) {
    Write-Host "Removing ESS demo SIT rule package $PackageId..."
    Remove-DlpSensitiveInformationTypeRulePackage -Identity $PackageId -Confirm:$false
    Write-Host "Removed."
    return
}

# Rule package XML — Microsoft Purview EDM/Custom SIT format
$ruleXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<RulePackage xmlns="http://schemas.microsoft.com/office/2011/mce">
  <RulePack id="$PackageId">
    <Version major="1" minor="0" build="0" revision="0" />
    <Publisher id="$PublisherId" />
    <Details defaultLangCode="en-us">
      <LocalizedDetails langcode="en-us">
        <PublisherName>ESS Hosted Agent Demo</PublisherName>
        <Name>ESS Hosted Agent Demo SITs</Name>
        <Description>Custom SITs that align with the ESS Workday + ServiceNow hosted agent's tenant data so DSPM for AI Activity Explorer can attribute runs to the right Sensitive Information Type.</Description>
      </LocalizedDetails>
    </Details>
  </RulePack>

  <Rules>
    <!-- Employee ID: EMP-200145 -->
    <Entity id="$EmployeeId" patternsProximity="300" recommendedConfidence="85">
      <Pattern confidenceLevel="85">
        <IdMatch idRef="Regex_ess_employee_id" />
      </Pattern>
    </Entity>

    <!-- ServiceNow case: INC0010023, CHG0001234, REQ0001234, RITM0001234, CASE0001234 -->
    <Entity id="$IncidentId" patternsProximity="300" recommendedConfidence="85">
      <Pattern confidenceLevel="85">
        <IdMatch idRef="Regex_ess_servicenow_case" />
      </Pattern>
    </Entity>

    <!-- Project codename keywords -->
    <Entity id="$CodenameId" patternsProximity="300" recommendedConfidence="90">
      <Pattern confidenceLevel="90">
        <IdMatch idRef="Keyword_ess_codename" />
      </Pattern>
    </Entity>

    <!-- Performance Improvement Plan / PIP marker -->
    <Entity id="$PipId" patternsProximity="300" recommendedConfidence="80">
      <Pattern confidenceLevel="80">
        <IdMatch idRef="Keyword_ess_pip" />
      </Pattern>
    </Entity>

    <Regex id="Regex_ess_employee_id">\bEMP-\d{6}\b</Regex>
    <Regex id="Regex_ess_servicenow_case">\b(INC|CHG|REQ|RITM|CASE)\d{7}\b</Regex>

    <Keyword id="Keyword_ess_codename">
      <Group matchStyle="word">
        <Term caseSensitive="false">Wingtip Acquisition</Term>
        <Term caseSensitive="false">Project Icarus</Term>
      </Group>
    </Keyword>

    <Keyword id="Keyword_ess_pip">
      <Group matchStyle="word">
        <Term caseSensitive="false">Performance Improvement Plan</Term>
        <Term caseSensitive="false">on a PIP</Term>
        <Term caseSensitive="false">placed on PIP</Term>
      </Group>
    </Keyword>

    <LocalizedStrings>
      <Resource idRef="$EmployeeId">
        <Name default="true" langcode="en-us">ESS Workday Employee ID</Name>
        <Description default="true" langcode="en-us">Workday employee identifier in the form EMP-NNNNNN used by the ESS hosted agent demo tenant.</Description>
      </Resource>
      <Resource idRef="$IncidentId">
        <Name default="true" langcode="en-us">ESS ServiceNow Case Number</Name>
        <Description default="true" langcode="en-us">ServiceNow record number (INC/CHG/REQ/RITM/CASE) used by the ESS hosted agent demo tenant.</Description>
      </Resource>
      <Resource idRef="$CodenameId">
        <Name default="true" langcode="en-us">ESS Project Codename</Name>
        <Description default="true" langcode="en-us">Confidential project codenames classified by ESS hosted agent label policy.</Description>
      </Resource>
      <Resource idRef="$PipId">
        <Name default="true" langcode="en-us">ESS Performance Improvement Plan Marker</Name>
        <Description default="true" langcode="en-us">Mentions of an active Performance Improvement Plan in HR conversational context.</Description>
      </Resource>
    </LocalizedStrings>
  </Rules>
</RulePackage>
"@

# New-DlpSensitiveInformationTypeRulePackage expects a byte[] in UTF-16
$bytes = [System.Text.Encoding]::Unicode.GetBytes($ruleXml)

$existing = $null
try {
    $existing = Get-DlpSensitiveInformationTypeRulePackage -Identity $PackageId -ErrorAction SilentlyContinue
} catch {
    $existing = $null
}

if ($existing) {
    Write-Host "Updating existing ESS demo SIT rule package $PackageId..."
    Set-DlpSensitiveInformationTypeRulePackage -Identity $PackageId -FileData $bytes | Out-Null
} else {
    Write-Host "Creating ESS demo SIT rule package $PackageId..."
    New-DlpSensitiveInformationTypeRulePackage -FileData $bytes | Out-Null
}

Write-Host ""
Write-Host "Done. Registered custom Sensitive Information Types:" -ForegroundColor Green
Write-Host "  - ESS Workday Employee ID            (EMP-NNNNNN)"
Write-Host "  - ESS ServiceNow Case Number         ((INC|CHG|REQ|RITM|CASE)NNNNNNN)"
Write-Host "  - ESS Project Codename               (Wingtip Acquisition / Project Icarus)"
Write-Host "  - ESS Performance Improvement Plan Marker"
Write-Host ""
Write-Host "Verify with:"
Write-Host "  Get-DlpSensitiveInformationType | Where-Object { `$_.Name -like 'ESS *' }"
Write-Host ""
Write-Host "It can take a few minutes for the new SITs to appear in DSPM for AI Activity Explorer."
