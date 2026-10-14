#!/bin/sh
# Generates import libraries (no Windows SDK needed) so Windows assembly can be linked on Linux.
# Usage: winlibs.sh <outdir>   Entries are "dll fn fn ..." lines below.
set -eu
out=$1
mkdir -p "$out"
while read -r dll fns; do
    [ -z "$dll" ] && continue
    def="$out/$dll.def"
    { echo "LIBRARY $dll.dll"; echo EXPORTS; for f in $fns; do echo "$f"; done; } > "$def"
    llvm-dlltool -m i386:x86-64 -d "$def" -l "$out/$dll.lib"
done <<'LIBS'
kernel32 GetCommandLineW WideCharToMultiByte MultiByteToWideChar GetTickCount64 GetStdHandle CreateFileW ReadFile WriteFile CloseHandle MoveFileExW GetFileAttributesW ExitProcess LocalFree LoadLibraryExW GetProcAddress FreeLibrary SetEnvironmentVariableW GetModuleHandleW GetModuleFileNameW CreateProcessW WaitForSingleObject GetExitCodeProcess CopyFileW CreateDirectoryW FindFirstFileW FindNextFileW FindClose DeleteFileW GetEnvironmentVariableW GetLocalTime GetLastError lstrlenW lstrcpyW lstrcatW lstrcmpiW SetFileAttributesW RemoveDirectoryW GetCurrentDirectoryW ExpandEnvironmentStringsW
shell32 CommandLineToArgvW SHGetKnownFolderPath SHBrowseForFolderW SHGetPathFromIDListW ShellExecuteW
ole32 CoTaskMemFree CoInitialize
ws2_32 WSAStartup WSACleanup socket bind ioctlsocket closesocket recvfrom sendto WSAPoll
user32 wsprintfW RegisterClassExW CreateWindowExW DefWindowProcW ShowWindow UpdateWindow GetMessageW TranslateMessage DispatchMessageW PostQuitMessage SendMessageW SetWindowTextW MessageBoxW LoadCursorW EnableWindow DestroyWindow GetClientRect MoveWindow SetTimer KillTimer InvalidateRect
gdi32 GetStockObject
advapi32 RegOpenKeyExW RegQueryValueExW RegCloseKey
winhttp WinHttpOpen WinHttpConnect WinHttpOpenRequest WinHttpSendRequest WinHttpReceiveResponse WinHttpQueryHeaders WinHttpQueryDataAvailable WinHttpReadData WinHttpCloseHandle WinHttpSetOption
bcrypt BCryptOpenAlgorithmProvider BCryptHash BCryptCloseAlgorithmProvider
LIBS
