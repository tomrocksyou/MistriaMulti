param(
    [ValidateSet('','host','join')][string]$Mode = '',
    [string]$GameDirectory = '',
    [string]$HostAddress = '',
    [ValidateRange(1,65535)][int]$Port = 7777,
    [ValidateRange(0,65535)][int]$LocalPort = 0,
    [ValidateRange(0,7)][int]$PlayerId = 0,
    [string]$RoomCode = '',
    [switch]$FromSteam,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$GameCommand
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Find-Game.ps1')
. (Join-Path $PSScriptRoot 'SaveGuard.ps1')

# Steam's launch option runs "SteamLaunch.cmd %command%": this script then starts the helper and the game.
# -FromSteam must never stop the game from starting, so any failure falls back to a plain solo launch.
$script:taskGameLaunched = $false
function Start-GameDirect {
    param([string[]]$Command)
    $script:taskGameLaunched = $true
    $taskExe = $Command[0]
    $taskRest = @()
    if ($Command.Count -gt 1) { $taskRest = @($Command[1..($Command.Count - 1)] | Where-Object { $_ -ne '--mistrimulti-direct' }) }
    if ($taskRest.Count -gt 0) { Start-Process -FilePath $taskExe -ArgumentList $taskRest -WorkingDirectory (Split-Path -Parent $taskExe) -Wait }
    else { Start-Process -FilePath $taskExe -WorkingDirectory (Split-Path -Parent $taskExe) -Wait }
}
trap {
    if ($FromSteam -and -not $script:taskGameLaunched -and $GameCommand) {
        Write-Host ("MistriMulti could not start, launching the game without multiplayer: " + $_)
        Start-GameDirect $GameCommand
        exit 0
    }
    break
}
if ($FromSteam) {
    try { Start-Transcript -Path (Join-Path $env:LOCALAPPDATA 'FieldsOfMistria\mod_data\mistrimulti\launcher.log') -Force | Out-Null } catch {}
    if ($GameCommand -contains '--mistrimulti-direct') { Start-GameDirect $GameCommand; exit 0 }
}
$GameDirectory = Find-MistriMultiGame $GameDirectory
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskHelper = Join-Path $taskProjectRoot 'build\mistrimulti-helper.exe'
if (-not (Test-Path -LiteralPath $taskHelper)) { throw 'Build the helper first using scripts\Build.ps1.' }
if (-not (Test-Path -LiteralPath (Join-Path $GameDirectory 'FieldsOfMistria.exe'))) { throw 'Set -GameDirectory to your Fields of Mistria install.' }
if (-not (Test-Path -LiteralPath (Join-Path $GameDirectory 'mods\mistrimulti\manifest.toml'))) { throw 'Run scripts\Install-Mod.ps1, then install MistriMulti in MOMI.' }
if (Get-Process -Name FieldsOfMistria -ErrorAction SilentlyContinue) { throw 'Close Fields of Mistria before starting a multiplayer session.' }
# One launcher for everything: it asks host or join once, then remembers the details.
$taskConfigPath = Join-Path $env:LOCALAPPDATA 'FieldsOfMistria\mod_data\mistrimulti\launcher.json'
$taskSaved = $null
if (Test-Path -LiteralPath $taskConfigPath) {
    try { $taskSaved = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json } catch { $taskSaved = $null }
}
$taskReenter = $false
if ($FromSteam) {
    $taskValid = $false
    if ($taskSaved -and $taskSaved.mode -in @('host','join') -and ([string]$taskSaved.roomCode) -match '^[0-9a-fA-F]{8}$') {
        $taskAddr = $null
        if ($taskSaved.mode -eq 'host') { $taskValid = $true }
        elseif ([Net.IPAddress]::TryParse([string]$taskSaved.hostAddress,[ref]$taskAddr) -and [int]$taskSaved.playerId -ge 1 -and [int]$taskSaved.playerId -le 7) { $taskValid = $true }
    }
    if (-not $taskValid) {
        Write-Host 'Multiplayer is not set up yet (run Play.bat once). Starting the game normally.'
        Start-GameDirect $GameCommand
        exit 0
    }
    $Mode = $taskSaved.mode
}
if (-not $Mode) {
    if ($taskSaved -and $taskSaved.mode -in @('host','join')) {
        $taskLast = if ($taskSaved.mode -eq 'host') { 'host a game' } else { "join $($taskSaved.hostAddress)" }
        $taskPick = Read-Host "Last time: $taskLast. Press Enter to repeat, H to host, J to join a friend (re-enter details)"
    } else { $taskPick = Read-Host 'Host a game (H) or join a friend (J)?' }
    if ($taskPick -match '^[hH]') { $Mode = 'host' }
    elseif ($taskPick -match '^[jJ]') { $Mode = 'join'; $taskReenter = $true }
    elseif (-not $taskPick -and $taskSaved -and $taskSaved.mode -in @('host','join')) { $Mode = $taskSaved.mode }
    else { throw 'Type H to host or J to join.' }
}
if ($taskSaved -and $taskSaved.mode -eq $Mode -and -not $taskReenter) {
    if (-not $HostAddress -and $taskSaved.hostAddress) { $HostAddress = [string]$taskSaved.hostAddress }
    if (-not $RoomCode -and $taskSaved.roomCode) { $RoomCode = [string]$taskSaved.roomCode }
    if ($Mode -eq 'join' -and $PlayerId -eq 0 -and $taskSaved.playerId) { $PlayerId = [int]$taskSaved.playerId }
}
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
New-Item -ItemType Directory -Path (Split-Path -Parent $taskConfigPath) -Force | Out-Null
$taskRemember = @{ mode = $Mode; hostAddress = $HostAddress; port = $Port; playerId = $PlayerId; roomCode = $RoomCode }
[IO.File]::WriteAllText($taskConfigPath, ($taskRemember | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
if (-not $FromSteam) {
    Write-Host ('Tip: to start multiplayer from the Play button in Steam, set the game''s launch option to:  "' + (Join-Path (Split-Path -Parent $PSScriptRoot) 'SteamLaunch.cmd') + '" %command%')
}
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
# Snapshot solo saves before the game can touch them.
$taskSavesDir = Get-MistriMultiSavesDir
$taskBackup = New-SoloBackup -SavesDir $taskSavesDir -BackupRoot "$taskModData/solo_backups"
Write-Host "Solo saves backed up to $($taskBackup.Path)"
try {
    $taskHelperProcess = Start-Process -FilePath $taskHelper -ArgumentList $taskArgs -WindowStyle Hidden -PassThru
    $taskHelperProcess.Id | Set-Content -LiteralPath "$taskBridge/helper.pid"
    Write-Host "MistriMulti $Mode | player $PlayerId | room $RoomCode | UDP $LocalPort"
    if ($Mode -eq 'host') { Write-Host 'Give friends the room code above, your reachable IPv4 address, and port.' }
    Write-Host 'Load a save in the game. F8 shows multiplayer status. Keep this launcher open.'
    Start-Sleep -Milliseconds 400
    if ($taskHelperProcess.HasExited) { throw 'The helper could not start. Check the port and run the helper in a terminal for its error.' }
    if ($FromSteam) {
        Start-GameDirect $GameCommand
    } else {
        # The extra argument tells SteamLaunch.cmd (if installed) that this launcher already started the helper.
        Start-Process 'steam://rungameid/2142790//--mistrimulti-direct'
        $taskDeadline = (Get-Date).AddMinutes(2)
        do {
            Start-Sleep -Milliseconds 500
            $taskGame = Get-Process -Name FieldsOfMistria -ErrorAction SilentlyContinue
        } while (-not $taskGame -and (Get-Date) -lt $taskDeadline)
        if (-not $taskGame) { throw 'The game did not start.' }
        Wait-Process -Id $taskGame.Id
    }
} finally {
    $taskControl.enabled = $false
    [IO.File]::WriteAllText($taskControlPath, ($taskControl | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    if ($taskHelperProcess -and -not $taskHelperProcess.HasExited) {
        'stop' | Set-Content -LiteralPath "$taskBridge/stop.flag"
        if (-not $taskHelperProcess.WaitForExit(2500)) { Stop-Process -Id $taskHelperProcess.Id }
    }
    # Solo saves are never touched by multiplayer (it uses its own save folder), so they are never rolled back here.
    # The pre-launch copy in mod_data\mistrimulti\solo_backups is kept as a safety net.
}
