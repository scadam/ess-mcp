# Microsoft 365 rejects a sensitivity_label when an agent has no embedded
# knowledge or skills. Retain the author's source; adapt only the Caldova ZIP.
# If embedded content is added later, its label is retained automatically.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackagePath,
    [Parameter(Mandatory)][string]$Environment,
    [Parameter(Mandatory)][string]$ExpectedAppId
)

$ErrorActionPreference = 'Stop'
if ($Environment -ne 'caldova') { return }
Add-Type -AssemblyName System.IO.Compression

function Read-ZipText([IO.Compression.ZipArchiveEntry]$Entry) {
    $reader = [IO.StreamReader]::new($Entry.Open())
    try { $reader.ReadToEnd() }
    finally { $reader.Dispose() }
}

function Get-ZipHash([IO.Compression.ZipArchiveEntry]$Entry) {
    $stream = $Entry.Open()
    try { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)) }
    finally { $stream.Dispose() }
}

$package = Get-Item -LiteralPath $PackagePath
if ($package.Extension -ine '.zip' -or $package.LinkType) {
    throw 'Expected a regular generated ZIP package.'
}
$temporary = Join-Path $package.DirectoryName ('.caldova-package-' + [guid]::NewGuid() + '.zip')
$archive = $null
try {
    Copy-Item -LiteralPath $package.FullName -Destination $temporary
    $archive = [IO.Compression.ZipFile]::Open($temporary, [IO.Compression.ZipArchiveMode]::Update)
    $manifest = Read-ZipText ($archive.GetEntry('manifest.json')) | ConvertFrom-Json -AsHashtable
    if ($manifest.id -ne $ExpectedAppId) { throw 'Generated app ID does not match the target environment.' }
    $agentFiles = @($manifest.copilotAgents.declarativeAgents)
    if ($agentFiles.Count -ne 1) { throw 'Expected exactly one declarative agent.' }
    $agentFile = $agentFiles[0].file
    $agentEntry = $archive.GetEntry($agentFile)
    $agent = Read-ZipText $agentEntry | ConvertFrom-Json -AsHashtable
    $hasEmbeddedKnowledge = @($agent.capabilities | Where-Object { $_.name -eq 'EmbeddedKnowledge' }).Count -gt 0
    $hasSkills = [bool]($agent.agent_skills -or $agent['x-agent_skills'] -or $manifest.agentSkills)
    if ($hasEmbeddedKnowledge -or $hasSkills -or -not $agent.ContainsKey('sensitivity_label')) {
        Write-Output 'Caldova package: no sensitivity-label adaptation required.'
        return
    }

    $retainedHashes = @{}
    foreach ($entry in $archive.Entries) {
        if ($retainedHashes.ContainsKey($entry.FullName)) { throw 'Duplicate package entry.' }
        $retainedHashes[$entry.FullName] = Get-ZipHash $entry
    }
    [void]$retainedHashes.Remove($agentFile)
    [void]$agent.Remove('sensitivity_label')
    $updatedText = ($agent | ConvertTo-Json -Depth 100) + "`n"
    $agentEntry.Delete()
    $writer = [IO.StreamWriter]::new($archive.CreateEntry($agentFile).Open(), [Text.UTF8Encoding]::new($false))
    try { $writer.Write($updatedText) }
    finally { $writer.Dispose() }
    $archive.Dispose()
    $archive = [IO.Compression.ZipFile]::OpenRead($temporary)
    if ($archive.Entries.Count -ne $retainedHashes.Count + 1) { throw 'Unexpected package entry count.' }
    foreach ($entry in $archive.Entries) {
        if ($entry.FullName -eq $agentFile) { continue }
        if ($retainedHashes[$entry.FullName] -ne (Get-ZipHash $entry)) {
            throw 'An unrelated package entry changed.'
        }
    }
    if ((Read-ZipText ($archive.GetEntry($agentFile))) -ne $updatedText) { throw 'Agent package write verification failed.' }
    $archive.Dispose()
    $archive = $null
    [IO.File]::Move($temporary, $package.FullName, $true)
    Write-Output 'Caldova ZIP only: omitted unused sensitivity_label because no embedded knowledge or skills are declared. Author source is unchanged.'
}
finally {
    if ($archive) { $archive.Dispose() }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}