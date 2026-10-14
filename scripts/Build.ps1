param([ValidateSet('Windows','Linux','Both')][string]$Target = 'Windows', [switch]$Release)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskBuildRoot = Join-Path $taskProjectRoot 'build'
New-Item -ItemType Directory -Path $taskBuildRoot -Force | Out-Null
$taskNasm = (Get-Command nasm -ErrorAction SilentlyContinue).Source
if (-not $taskNasm) {
    $taskNasm = Join-Path $env:LOCALAPPDATA 'bin\NASM\nasm.exe'
}
if (-not (Test-Path -LiteralPath $taskNasm)) { throw 'Install NASM and add it to PATH.' }
$taskIncludes = (Join-Path $taskProjectRoot 'helper\include').Replace('\','/') + '/'
$taskSha = (Join-Path $taskProjectRoot 'linux').Replace('\','/') + '/'   # sha256.inc is shared with the helper
if ($Target -in @('Windows','Both')) {
    $taskVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $taskVsRoot = & $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $taskVsRoot) { throw 'Install the Desktop development with C++ workload.' }
    $taskMsvcRoot = Join-Path $taskVsRoot 'VC\Tools\MSVC'
    $taskToolset = Get-ChildItem -LiteralPath $taskMsvcRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $taskLinker = Join-Path $taskToolset.FullName 'bin\Hostx64\x64\link.exe'
    $taskSdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Lib'
    $taskSdk = Get-ChildItem -LiteralPath $taskSdkRoot -Directory | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName 'um\x64\ws2_32.lib')
    } | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $taskSdk) { throw 'Install a Windows SDK.' }
    $taskObject = Join-Path $taskBuildRoot 'helper-win.obj'
    $taskDebugFlags = if ($Release) { @() } else { @('-g','-F','cv8') }
    & $taskNasm -f win64 @taskDebugFlags -I $taskIncludes -I $taskSha (Join-Path $taskProjectRoot 'helper\windows.asm') -o $taskObject
    if ($LASTEXITCODE -ne 0) { throw 'NASM Windows assembly failed.' }
    $taskExecutable = Join-Path $taskBuildRoot 'mistrimulti-helper.exe'
    $taskLibraries = Join-Path $taskSdk.FullName 'um\x64'
    $taskArguments = @('/nologo','/machine:x64','/subsystem:console','/entry:mistria_main','/nodefaultlib','/incremental:no',
        "/out:$taskExecutable", $taskObject, "/libpath:$taskLibraries", 'kernel32.lib','ws2_32.lib','shell32.lib','bcrypt.lib')
    if (-not $Release) { $taskArguments += '/debug' }
    & $taskLinker @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Windows linking failed.' }
    Write-Host 'Windows helper built.'
    $taskSteamObject = Join-Path $taskBuildRoot 'steam-win.obj'
    $taskDebugFlags = if ($Release) { @() } else { @('-g','-F','cv8') }
    & $taskNasm -f win64 @taskDebugFlags -I $taskIncludes (Join-Path $taskProjectRoot 'helper\steam_windows.asm') -o $taskSteamObject
    if ($LASTEXITCODE -ne 0) { throw 'Steam identity assembly failed.' }
    $taskSteamExe = Join-Path $taskBuildRoot 'mistrimulti-steam-id.exe'
    $taskSteamArgs = @('/nologo','/machine:x64','/subsystem:console','/entry:steam_identity_main','/nodefaultlib','/incremental:no',
        "/out:$taskSteamExe", $taskSteamObject, "/libpath:$taskLibraries", 'kernel32.lib','shell32.lib')
    if (-not $Release) { $taskSteamArgs += '/debug' }
    & $taskLinker @taskSteamArgs
    if ($LASTEXITCODE -ne 0) { throw 'Steam identity linking failed.' }
    Write-Host 'Windows Steam identity probe built.'
    $taskUpdaterObject = Join-Path $taskBuildRoot 'updater-win.obj'
    & $taskNasm -f win64 @taskDebugFlags -I $taskIncludes -I ((Join-Path $taskProjectRoot 'common').Replace('\','/') + '/') -I ((Join-Path $taskProjectRoot 'updater').Replace('\','/') + '/') (Join-Path $taskProjectRoot 'updater\updater.asm') -o $taskUpdaterObject
    if ($LASTEXITCODE -ne 0) { throw 'Updater assembly failed.' }
    $taskUpdaterExe = Join-Path $taskBuildRoot 'MistriMulti.exe'
    $taskUpdaterArgs = @('/nologo','/machine:x64','/subsystem:windows','/entry:start','/nodefaultlib','/incremental:no',
        "/out:$taskUpdaterExe", $taskUpdaterObject, "/libpath:$taskLibraries",
        'kernel32.lib','user32.lib','shell32.lib','gdi32.lib','ole32.lib','winhttp.lib','bcrypt.lib','ws2_32.lib','iphlpapi.lib','comdlg32.lib')
    if (-not $Release) { $taskUpdaterArgs += '/debug' }
    & $taskLinker @taskUpdaterArgs
    if ($LASTEXITCODE -ne 0) { throw 'Updater linking failed.' }
    Write-Host 'Windows updater built.'
    $taskLauncherObject = Join-Path $taskBuildRoot 'launcher-win.obj'
    & $taskNasm -f win64 @taskDebugFlags -I $taskIncludes -I ((Join-Path $taskProjectRoot 'common').Replace('\','/') + '/') (Join-Path $taskProjectRoot 'launcher\launcher.asm') -o $taskLauncherObject
    if ($LASTEXITCODE -ne 0) { throw 'Launcher assembly failed.' }
    $taskLauncherExe = Join-Path $taskBuildRoot 'MistriMultiLauncher.exe'
    $taskLauncherArgs = @('/nologo','/machine:x64','/subsystem:windows','/entry:start','/nodefaultlib','/incremental:no',
        "/out:$taskLauncherExe", $taskLauncherObject, "/libpath:$taskLibraries",
        'kernel32.lib','user32.lib','shell32.lib','ole32.lib','ws2_32.lib','bcrypt.lib')
    if (-not $Release) { $taskLauncherArgs += '/debug' }
    & $taskLinker @taskLauncherArgs
    if ($LASTEXITCODE -ne 0) { throw 'Launcher linking failed.' }
    Write-Host 'Windows launcher built.'
}
if ($Target -in @('Linux','Both')) {
    $taskObject = Join-Path $taskBuildRoot 'helper-linux.o'
    $taskDebugFlags = if ($Release) { @() } else { @('-g','-F','dwarf') }
    & $taskNasm -f elf64 @taskDebugFlags -I $taskIncludes -I $taskSha (Join-Path $taskProjectRoot 'helper\linux.asm') -o $taskObject
    if ($LASTEXITCODE -ne 0) { throw 'NASM Linux assembly failed.' }
    $taskWslObject = (& wsl -d Ubuntu -- wslpath -a $taskObject.Replace('\','/')).Trim()
    $taskLinuxOutput = (Join-Path $taskBuildRoot 'mistrimulti-helper-linux').Replace('\','/')
    $taskWslOutput = (& wsl -d Ubuntu -- wslpath -a $taskLinuxOutput).Trim()
    $taskStripFlags = @(if ($Release) { '-s' })
    & wsl -d Ubuntu -- ld @taskStripFlags $taskWslObject -o $taskWslOutput
    if ($LASTEXITCODE -ne 0) { throw 'Linux linking failed. WSL Ubuntu with binutils is required.' }
    Write-Host 'Linux helper built.'
    foreach ($taskProgram in @('launcher','manager')) {
        $taskProgramObject = Join-Path $taskBuildRoot "$taskProgram-linux.o"
        & $taskNasm -f elf64 @taskDebugFlags -I $taskIncludes -I ((Join-Path $taskProjectRoot 'common').Replace('\','/') + '/') -I ((Join-Path $taskProjectRoot 'linux').Replace('\','/') + '/') (Join-Path $taskProjectRoot "linux\$taskProgram.asm") -o $taskProgramObject
        if ($LASTEXITCODE -ne 0) { throw "Linux $taskProgram assembly failed." }
        $taskWslProgramObject = (& wsl -d Ubuntu -- wslpath -a $taskProgramObject.Replace('\','/')).Trim()
        $taskProgramOutput = (Join-Path $taskBuildRoot "mistrimulti-$taskProgram").Replace('\','/')
        $taskWslProgramOutput = (& wsl -d Ubuntu -- wslpath -a $taskProgramOutput).Trim()
        & wsl -d Ubuntu -- ld @taskStripFlags $taskWslProgramObject -o $taskWslProgramOutput
        if ($LASTEXITCODE -ne 0) { throw "Linux $taskProgram linking failed." }
    }
    Write-Host 'Linux launcher and manager built.'
    $taskSteamObject = Join-Path $taskBuildRoot 'steam-linux.o'
    $taskDebugFlags = if ($Release) { @() } else { @('-g','-F','dwarf') }
    & $taskNasm -f elf64 @taskDebugFlags -I $taskIncludes (Join-Path $taskProjectRoot 'helper\steam_linux.asm') -o $taskSteamObject
    if ($LASTEXITCODE -ne 0) { throw 'Linux Steam identity assembly failed.' }
    $taskWslSteamObject = (& wsl -d Ubuntu -- wslpath -a $taskSteamObject.Replace('\','/')).Trim()
    $taskSteamOutput = (Join-Path $taskBuildRoot 'mistrimulti-steam-id-linux').Replace('\','/')
    $taskWslSteamOutput = (& wsl -d Ubuntu -- wslpath -a $taskSteamOutput).Trim()
    & wsl -d Ubuntu -- ld @taskStripFlags -e steam_identity_start -dynamic-linker /lib64/ld-linux-x86-64.so.2 $taskWslSteamObject -L /lib/x86_64-linux-gnu '-l:libdl.so.2' '-l:libc.so.6' -o $taskWslSteamOutput
    if ($LASTEXITCODE -ne 0) { throw 'Linux Steam identity linking failed.' }
    Write-Host 'Linux Steam identity probe built.'
}
