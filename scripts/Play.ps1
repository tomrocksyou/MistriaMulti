param(
    [ValidateSet('host','join')][string]$Mode = 'host',
    [string]$GameDirectory = '',
    [string]$HostAddress = '',
    [ValidateRange(1,65535)][int]$Port = 7777,
    [ValidateRange(0,65535)][int]$LocalPort = 0,
    [ValidateRange(0,7)][int]$PlayerId = 0,
    [string]$RoomCode = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Find-Game.ps1')
$GameDirectory = Find-MistriMultiGame $GameDirectory
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskHelper = Join-Path $taskProjectRoot 'build\mistrimulti-helper.exe'
if (-not (Test-Path -LiteralPath $taskHelper)) { throw 'Build the helper first using scripts\Build.ps1.' }
if (-not (Test-Path -LiteralPath (Join-Path $GameDirectory 'FieldsOfMistria.exe'))) { throw 'Set -GameDirectory to your Fields of Mistria install.' }
if (-not (Test-Path -LiteralPath (Join-Path $GameDirectory 'mods\mistrimulti\manifest.toml'))) { throw 'Run scripts\Install-Mod.ps1, then install MistriMulti in MOMI.' }
if (Get-Process -Name FieldsOfMistria -ErrorAction SilentlyContinue) { throw 'Close Fields of Mistria before starting a multiplayer session.' }
if ($Mode -eq 'host') { $PlayerId = 0; if ($LocalPort -eq 0) { $LocalPort = $Port }; if (-not $HostAddress) { $HostAddress = '127.0.0.1' } }
else {
    if ($PlayerId -eq 0) { $PlayerId = [int](Read-Host 'Your player number (1-7; different from each friend)') }
    if ($PlayerId -lt 1 -or $PlayerId -gt 7) { throw 'Joining players need a number from 1 to 7.' }
    if ($LocalPort -eq 0) { $LocalPort = $Port + $PlayerId }
    if ($LocalPort -gt 65535) { throw 'Choose -LocalPort within 1..65535.' }
    if (-not $HostAddress) {
        $taskAnswer = Read-Host 'Host IPv4 address (Enter for another instance on this PC)'
        $HostAddress = if ($taskAnswer) { $taskAnswer } else { '127.0.0.1' }
    }
}
$taskAddress = $null
if (-not [Net.IPAddress]::TryParse($HostAddress,[ref]$taskAddress) -or $taskAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'Use an IPv4 address.' }
if (-not $RoomCode) {
    if ($Mode -eq 'host') {
        $taskRandom = New-Object byte[] 4
        $taskRng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $taskRng.GetBytes($taskRandom)
        $taskRng.Dispose()
        $RoomCode = ([BitConverter]::ToString($taskRandom)).Replace('-','').ToLowerInvariant()
    } else { $RoomCode = Read-Host 'Eight-digit room code from the host' }
}
if ($RoomCode -notmatch '^[0-9a-fA-F]{8}$') { throw 'The room code must contain exactly eight hexadecimal digits.' }
$taskModData = (Join-Path $env:LOCALAPPDATA 'FieldsOfMistria\mod_data\mistrimulti').Replace('\','/')
$taskBridge = "$taskModData/bridge_$PlayerId"
New-Item -ItemType Directory -Path $taskBridge -Force | Out-Null
# Remove only this helper's known transient files, never game saves.
$taskResolvedBridge = (Resolve-Path -LiteralPath $taskBridge).Path
$taskResolvedRoot = [IO.Path]::GetFullPath($taskModData)
if (-not $taskResolvedBridge.StartsWith($taskResolvedRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected bridge path.' }
foreach ($taskName in @('stop.flag','status.json','tx.frame','tx.tmp','helper.pid')) {
    $taskFile = Join-Path $taskBridge $taskName
    if (Test-Path -LiteralPath $taskFile) { Remove-Item -LiteralPath $taskFile -Force }
}
for ($taskPeer = 0; $taskPeer -lt 8; $taskPeer++) {
    $taskFile = Join-Path $taskBridge "rx_$taskPeer.json"
    if (Test-Path -LiteralPath $taskFile) { Remove-Item -LiteralPath $taskFile -Force }
}
$taskControlPath = "$taskModData/control.json"
$taskUid = ''
$taskIdentityProbe = Join-Path $taskProjectRoot 'build\mistrimulti-steam-id.exe'
$taskSteamDll = Join-Path $GameDirectory 'steam_api64.dll'
if ((Test-Path -LiteralPath $taskIdentityProbe) -and (Test-Path -LiteralPath $taskSteamDll)) {
    $taskProbeInfo = New-Object Diagnostics.ProcessStartInfo
    $taskProbeInfo.FileName = $taskIdentityProbe
    $taskProbeInfo.Arguments = '"' + $taskSteamDll + '"'
    $taskProbeInfo.WorkingDirectory = $GameDirectory
    $taskProbeInfo.UseShellExecute = $false
    $taskProbeInfo.CreateNoWindow = $true
    $taskProbeInfo.RedirectStandardOutput = $true
    $taskProbeInfo.RedirectStandardError = $true
    $taskProbe = [Diagnostics.Process]::Start($taskProbeInfo)
    if ($taskProbe.WaitForExit(5000)) {
        $taskOutput = $taskProbe.StandardOutput.ReadToEnd()
        if ($taskProbe.ExitCode -eq 0) {
            $taskMatch = [regex]::Match($taskOutput, '(?m)^steam:[0-9]{17}\r?$')
            if ($taskMatch.Success) { $taskUid = $taskMatch.Value.Trim() }
        }
    } else { $taskProbe.Kill(); $taskProbe.WaitForExit() }
    $taskProbe.Dispose()
}
if (-not $taskUid) {
    $taskLocalIdentity = "$taskModData/local_identity.json"
    if (Test-Path -LiteralPath $taskLocalIdentity) {
        try { $taskSavedIdentity = Get-Content -LiteralPath $taskLocalIdentity -Raw | ConvertFrom-Json; if ($taskSavedIdentity.uid -match '^local:[0-9a-f]{32}$') { $taskUid = $taskSavedIdentity.uid } } catch {}
    }
    if (-not $taskUid) {
        $taskUid = 'local:' + [guid]::NewGuid().ToString('N')
        [IO.File]::WriteAllText($taskLocalIdentity, (@{uid=$taskUid}|ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    }
    Write-Host 'Steam identity is unavailable; using this device''s saved local identity.'
} else { Write-Host 'Steam account detected. Your character follows this account, regardless of player slot.' }
$taskControl = @{ enabled=$true; mode=$Mode; id=$PlayerId; uid=$taskUid; epoch=[guid]::NewGuid().ToString('N'); bridge=$taskBridge }
[IO.File]::WriteAllText($taskControlPath, ($taskControl | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
$taskArgs = @($Mode, "$LocalPort", "$PlayerId", $RoomCode, ('"' + $taskBridge + '"'))
if ($Mode -eq 'join') { $taskArgs += @($HostAddress, "$Port") }
$taskHelperProcess = $null
try {
    $taskHelperProcess = Start-Process -FilePath $taskHelper -ArgumentList $taskArgs -WindowStyle Hidden -PassThru
    $taskHelperProcess.Id | Set-Content -LiteralPath "$taskBridge/helper.pid"
    Write-Host "MistriMulti $Mode | player $PlayerId | room $RoomCode | UDP $LocalPort"
    if ($Mode -eq 'host') { Write-Host 'Give friends the room code above, your reachable IPv4 address, and port.' }
    Write-Host 'Load a save in the game. F8 shows multiplayer status. Keep this launcher open.'
    Start-Sleep -Milliseconds 400
    if ($taskHelperProcess.HasExited) { throw 'The helper could not start. Check the port and run the helper in a terminal for its error.' }
    Start-Process 'steam://rungameid/2142790'
    $taskDeadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Milliseconds 500
        $taskGame = Get-Process -Name FieldsOfMistria -ErrorAction SilentlyContinue
    } while (-not $taskGame -and (Get-Date) -lt $taskDeadline)
    if (-not $taskGame) { throw 'The game did not start.' }
    Wait-Process -Id $taskGame.Id
} finally {
    $taskControl.enabled = $false
    [IO.File]::WriteAllText($taskControlPath, ($taskControl | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    if ($taskHelperProcess -and -not $taskHelperProcess.HasExited) {
        'stop' | Set-Content -LiteralPath "$taskBridge/stop.flag"
        if (-not $taskHelperProcess.WaitForExit(2500)) { Stop-Process -Id $taskHelperProcess.Id }
    }
}
