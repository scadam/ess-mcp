# ATK includes every file under agentSkills; Copilot rejects nested ZIP archives.
# Filter only the generated package. Source skill folders and archives stay intact.
# Requires PowerShell 7 (pwsh), used by the Coupa ATK lifecycle.
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PackagePath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression

function Get-EntryHash([System.IO.Compression.ZipArchiveEntry]$Entry) {
    $stream = $Entry.Open()
    try {
        [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream))
    }
    finally {
        $stream.Dispose()
    }
}

$package = Get-Item -LiteralPath $PackagePath
if ($package.Extension -ine '.zip' -or $package.LinkType) {
    throw 'Expected a regular generated ZIP package.'
}
$temporary = Join-Path $package.DirectoryName ('.atk-package-' + [guid]::NewGuid() + '.zip')
$archive = $null
try {
    Copy-Item -LiteralPath $package.FullName -Destination $temporary
    $archive = [IO.Compression.ZipFile]::Open($temporary, [IO.Compression.ZipArchiveMode]::Update)
    $manifestEntry = $archive.GetEntry('manifest.json')
    if (-not $manifestEntry) { throw 'Package has no root manifest.' }
    $reader = [IO.StreamReader]::new($manifestEntry.Open())
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json }
    finally { $reader.Dispose() }

    $prefixes = @($manifest.agentSkills | ForEach-Object {
        $folder = $_.folder.Replace('\', '/') -replace '^(\./)+', ''
        if (-not $folder -or $folder.StartsWith('/') -or $folder -match '(^|/)\.\.(/|$)') {
            throw 'Invalid agent skill folder in package manifest.'
        }
        $folder.TrimEnd('/') + '/'
    })
    $removed = @($archive.Entries | Where-Object {
        $entryName = $_.FullName
        $entryName.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase) -and
            @($prefixes | Where-Object { $entryName.StartsWith($_, [StringComparison]::Ordinal) }).Count -gt 0
    })
    $removedNames = @($removed | ForEach-Object FullName)
    $retained = @{}
    foreach ($entry in $archive.Entries) {
        if ($entry.FullName -notin $removedNames) {
            if ($retained.ContainsKey($entry.FullName)) { throw 'Duplicate package entry.' }
            $retained[$entry.FullName] = Get-EntryHash $entry
        }
    }
    foreach ($entry in $removed) { $entry.Delete() }
    $archive.Dispose()
    $archive = $null

    if ($removed.Count -gt 0) {
        $archive = [IO.Compression.ZipFile]::OpenRead($temporary)
        if ($archive.Entries.Count -ne $retained.Count) { throw 'Package entry count changed unexpectedly.' }
        foreach ($entry in $archive.Entries) {
            if ($retained[$entry.FullName] -ne (Get-EntryHash $entry)) {
                throw 'Retained package content changed unexpectedly.'
            }
        }
        $archive.Dispose()
        $archive = $null
        [IO.File]::Move($temporary, $package.FullName, $true)
    }
    [pscustomobject]@{ Package = $package.Name; ExcludedSkillArchives = $removedNames } | ConvertTo-Json -Compress
}
finally {
    if ($archive) { $archive.Dispose() }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}