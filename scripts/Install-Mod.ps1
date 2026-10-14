param([string]$GameDirectory = '')
. (Join-Path $PSScriptRoot 'Find-Game.ps1')
$GameDirectory = Find-MistriMultiGame $GameDirectory
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $GameDirectory 'Maybe.toml'))) { throw 'Choose the game directory containing Maybe.toml.' }
if (Get-Process -Name FieldsOfMistria -ErrorAction SilentlyContinue) { throw 'Close the game before copying the mod.' }
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskSource = Join-Path $taskProjectRoot 'mod\mistrimulti'
$taskMods = Join-Path $GameDirectory 'mods'
$taskDestination = Join-Path $taskMods 'mistrimulti'
New-Item -ItemType Directory -Path $taskMods -Force | Out-Null
if (Test-Path -LiteralPath $taskDestination) {
    $taskExisting = Get-Content -LiteralPath (Join-Path $taskDestination 'manifest.toml') -Raw
    if ($taskExisting -notmatch 'name = "Mistria?Multi"' -or $taskExisting -notmatch 'requires_hooks = .*game.save_guard') { throw 'Another mod already occupies the destination.' }
}
New-Item -ItemType Directory -Path $taskDestination -Force | Out-Null
Copy-Item -Path (Join-Path $taskSource '*') -Destination $taskDestination -Recurse -Force
foreach ($taskNotice in @('LICENSE','CONTACT.md')) {
    Copy-Item -LiteralPath (Join-Path $taskProjectRoot $taskNotice) -Destination $taskDestination -Force
}
Write-Host "Copied MistriaMulti to $taskDestination"
Write-Host 'Open MOMI, select MistriaMulti, and click Install.'
