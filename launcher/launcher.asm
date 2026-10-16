; MistriaMulti launcher (NASM, Windows x64, no C runtime).
;   MistriMultiLauncher.exe --steam <game exe> [game args]   Steam launch option: starts the helper, runs the game, cleans up.
;   MistriMultiLauncher.exe --configure                      asks host / join once and saves launcher.cfg
; Safety rules: the game is ALWAYS started, whatever fails first; every value read from launcher.cfg is validated
; strictly before it reaches a command line or file; solo saves are only ever copied (never changed or removed).
bits 64
default rel
%define WINDOWS 1
%include "abi.inc"

%macro WSTR 2
%1: dw __utf16__(%2), 0
%endmacro

extern GetCommandLineW, CommandLineToArgvW, ExitProcess, GetEnvironmentVariableW, GetModuleFileNameW
extern CreateProcessW, WaitForSingleObject, TerminateProcess, GetExitCodeProcess
extern DeleteFileW, CopyFileW, FindFirstFileW, FindNextFileW, FindClose, RemoveDirectoryW, GetLocalTime
extern WideCharToMultiByte, lstrlenW, lstrlenA, lstrcmpiW, wsprintfW, wsprintfA
extern CreateJobObjectW, SetInformationJobObject, AssignProcessToJobObject
extern CreateWindowExW
extern OpenClipboard, EmptyClipboard, SetClipboardData, CloseClipboard, GlobalAlloc, GlobalLock, GlobalUnlock
extern WSAStartup, WSACleanup, socket, bind, WSAPoll, recvfrom, sendto, closesocket, GetComputerNameA
extern listen, accept, inet_addr, setsockopt
extern CoCreateGuid, GetStdHandle, AllocConsole, SetConsoleOutputCP, Sleep, GetExitCodeProcess, ReadFile, WriteFile, CloseHandle

section .data
WSTR s_steam, "--steam"
WSTR s_configure, "--configure"
WSTR s_direct, "--mistrimulti-direct"
WSTR s_gameexe, "FieldsOfMistria.exe"
WSTR e_local, "LOCALAPPDATA"
WSTR f_mod, "%s\FieldsOfMistria\mod_data\mistrimulti"
WSTR f_saves, "%s\FieldsOfMistria\saves"
WSTR f_cat, "%s%s"
WSTR f_slash, "%s\%s"
WSTR f_star, "%s\*"
WSTR f_bridge, "%s\bridge_%d"
WSTR f_probecmd, `"%s" "%s"`
WSTR f_helpercmd_host, `"%s\\mistrimulti-helper.exe" host %d %d %s "%s"`
WSTR f_helpercmd_join, `"%s\\mistrimulti-helper.exe" join %d %d %s "%s" %s %d`
WSTR f_stamp, "\%04d%02d%02d-%02d%02d%02d"
WSTR f_launchopt, `"%s" --steam `
WSTR s_command, "%command%"
WSTR clip_static, "STATIC"
WSTR f_mpsaves_star, "%s\FieldsOfMistria\multiplayer\saves\*.sav"
WSTR f_mpsaves_file, "%s\FieldsOfMistria\multiplayer\saves\%S"
WSTR f_mpsaves_dir, "%s\FieldsOfMistria\multiplayer\saves"
WSTR n_cfg, "\launcher.cfg"
WSTR n_authcfg, "auth.cfg"
WSTR n_log, "\launcher.log"
WSTR n_control, "\control.json"
WSTR n_identity, "\local_identity.json"
WSTR n_steamtmp, "\steamid.tmp"
WSTR n_probe, "mistrimulti-steam-id.exe"
WSTR n_dll, "steam_api64.dll"
WSTR n_helper, "mistrimulti-helper.exe"
WSTR n_backups, "\solo_backups"
WSTR n_stop, "stop.flag"
WSTR n_status, "status.json"
WSTR n_txframe, "tx.frame"
WSTR n_txtmp, "tx.tmp"
WSTR n_pid, "helper.pid"
WSTR f_rx, "rx_%d.json"
r_exe db 'Multiplayer not started: the game executable is not FieldsOfMistria.exe. The game was started normally.',13,10,0
r_flag db 'Multiplayer not started: --mistrimulti-direct was given. The game was started normally.',13,10,0
r_paths db 'Multiplayer not started: could not work out the folders (LOCALAPPDATA?). The game was started normally.',13,10,0
r_config db 'Multiplayer not started: launcher.cfg is missing or invalid. Run the launcher with --configure. The game was started normally.',13,10,0
r_control db 'Multiplayer not started: control.json could not be written. The game was started normally.',13,10,0
r_auth db 'Multiplayer not started: auth.cfg could not be written, so the room password cannot be applied. The game was started normally.',13,10,0
r_helper db 'Multiplayer not started: the network helper could not be started (is mistrimulti-helper.exe next to the launcher, and is the port free?). The game was started normally.',13,10,0
k_mode db 5,'mode='
k_host db 5,'host='
k_port db 5,'port='
k_player db 7,'player='
k_room db 5,'room='
k_pass db 9,'password='
room_default db '4d495354',0
host_s_dummy db 0
a_host_s db 'host',0
a_join_s db 'join',0
a_idle_s db 'idle',0
needle_local db '"uid":"local:'
needle_local_len equ $ - needle_local
hexdigits db '0123456789abcdef'
json_control db '{"enabled":%s,"mode":"%s","id":%d,"uid":"%s","epoch":"%s","bridge":"%s"}',0
json_true db 'true',0
json_false db 'false',0
json_identity db '{"uid":"%s"}',0
cfg_fmt db 'mode=%s',13,10,'host=%s',13,10,'port=%d',13,10,'player=%d',13,10,'room=%s',13,10,0
f_cfg_pass db 'password=%s',13,10,0
f_auth_key db 'key=%s\install.key',13,10,0
f_auth_keys db 'keys=%s\trust_keys.txt',13,10,0
f_auth_deny db 'deny=%s\deny.txt',13,10,0
f_auth_pass db 'pass=%s',13,10,0
t_optional db 'Optional setup: you can skip it. Start the game from Steam and choose Multiplayer, then Host a game or Join a game, in the game itself.',13,10,'This pre-sets a role (saved in launcher.cfg) that starts by itself.',13,10,13,10,0
t_stop db 'stop'
t_stop_len equ $ - t_stop
p_mode db 'Host a game (H) or join a friend (J)? ',0
p_ip db 'Host IPv4 address (for example 192.168.1.20): ',0
p_port db 'Port (Enter for 7777): ',0
p_player db 'Your player number, 1 to 7, or just press Enter to pick one for you: ',0
p_room db 'Room code (just press Enter unless your host gave you one): ',0
t_hostinfo db 13,10,'Tell your friends your Tailscale IP address (it starts with 100.). That is all they need to join you.',13,10,0
t_player db 'Your player number is %d (every friend needs a different one; run setup again to change it).',13,10,0
p_close db 13,10,'Press Enter to close.',0
t_bad db 'That value is not valid, try again.',13,10,0
t_giveup db 'Setup was not saved.',13,10,0
t_roomis db 'Room code (give this to your friends): ',0
t_crlf db 13,10,0
t_saved db 13,10,'Saved. The line below is already copied to your clipboard.',13,10,'One time only: in Steam, right-click Fields of Mistria > Properties > Launch Options, press Ctrl+V, and close the window.',13,10,13,10,0
t_cmd1 db '"',0
t_cmd2 db '" --steam %command%',13,10,0
name_table dq n_stop, n_status, n_txframe, n_txtmp, n_pid
align 8

section .bss
sv_serving resd 1
tcp_sock resq 1
ws_name resb 80
ws_tmp resb 80
ws_size resd 1
ws_best resq 1
ws_path resw 1040
ws_from resb 32
ws_fromlen resd 1
ws_timeout resd 1
disc_pfds resb 32
disc_sock resq 1
disc_pfd resb 16
disc_from resb 32
disc_fromlen resd 1
disc_buf resb 128
disc_resp resb 64
wsadata resb 408
old_mode resd 1
old_player resd 1
h_job resq 1
jobinfo resb 144
in_pos resd 1
in_len resd 1
inbuf resb 256
reason resq 1
have_old resd 1
ans resb 64
minname resw 24
argc resd 1
argv resq 1
cmd_rest resq 1
game_exit resd 1
q_len resd 1
cfg_len resq 1
cfg_mode resd 1
cfg_port resd 1
cfg_player resd 1
cfg_local resd 1
h_in resq 1
h_out resq 1
h_helper resq 1
guid resb 16
sa resb 24
sinfo resb 104
pinfo resb 24
fd resb 600
st resb 16
a_mode resb 16
a_host resb 32
a_port resb 16
a_player resb 16
a_room resb 16
a_pass resb 72
auth_buf resb 4200
uid_a resb 64
epoch_a resb 40
line_a resb 256
w_host resw 32
w_room resw 16
exe_path resw 520
exe_dir resw 520
game_dir resw 520
local_app resw 520
mod_dir resw 520
bridge_dir resw 520
bridge_fwd resw 520
p1 resw 1040
p2 resw 1040
p3 resw 1040
cmd_buf resw 2080
utf8 resb 3200
file_buf resb 8200
names resw 1600

section .text
global start
%include "winutil.inc"
%include "world.inc"
%include "worldserve.inc"
%include "menu.inc"







FN wsubstr                      ; rcx haystack wide, rdx needle wide -> eax 1 if contained
    mov rsi, rcx
    mov r12, rdx
.o: cmp word [rsi], 0
    je .no
    xor r8d, r8d
.i: movzx eax, word [r12+r8*2]
    test ax, ax
    jz .yes
    cmp ax, [rsi+r8*2]
    jne .next
    inc r8d
    jmp .i
.next:
    add rsi, 2
    jmp .o
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN guid_hex                     ; fills guid, writes 32 lowercase hex chars + NUL at rcx
    mov r12, rcx
    lea rcx, [guid]
    call CoCreateGuid
    lea rsi, [guid]
    mov rdi, r12
    lea r8, [hexdigits]
    xor ecx, ecx
.h: movzx eax, byte [rsi+rcx]
    mov edx, eax
    shr edx, 4
    and eax, 15
    mov dl, [r8+rdx]
    mov [rdi], dl
    mov al, [r8+rax]
    mov [rdi+1], al
    add rdi, 2
    inc ecx
    cmp ecx, 16
    jb .h
    mov byte [rdi], 0
END_FN

; rcx = key (length-prefixed), rdx = out ASCII buffer, r8 = out size. Value of "key=..." line from file_buf -> eax length (0 if absent)
FN cfg_get
    movzx r9d, byte [rcx]
    lea r10, [rcx+1]
    mov r12, rdx
    mov r13, r8
    dec r13
    lea rsi, [file_buf]
    lea r11, [file_buf]
    add r11, [cfg_len]
.line:
    cmp rsi, r11
    jae .none
    mov rax, r11
    sub rax, rsi
    cmp rax, r9
    jb .skip
    xor ecx, ecx
.cmp:
    cmp rcx, r9
    je .match
    mov al, [rsi+rcx]
    cmp al, [r10+rcx]
    jne .skip
    inc rcx
    jmp .cmp
.match:
    lea rdi, [rsi+r9]
    xor ecx, ecx
.cp:
    cmp rdi, r11
    jae .dv
    mov al, [rdi]
    cmp al, 13
    je .dv
    cmp al, 10
    je .dv
    cmp rcx, r13
    jae .dv
    mov [r12+rcx], al
    inc rcx
    inc rdi
    jmp .cp
.dv:
    mov byte [r12+rcx], 0
    mov eax, ecx
    jmp .end
.skip:
.nl:
    cmp rsi, r11
    jae .none
    cmp byte [rsi], 10
    je .adv
    inc rsi
    jmp .nl
.adv:
    inc rsi
    jmp .line
.none:
    mov byte [r12], 0
    xor eax, eax
.end:
END_FN

; ---------------- paths ----------------
; Fills exe_path, exe_dir, game_dir (from argv[2] when present), local_app, mod_dir. eax=1 ok (game_dir is best effort)
FN setup_paths
    mov byte [game_dir], 0
    mov word [game_dir], 0
    cmp dword [argc], 3
    jb .nogame
    mov rax, [argv]
    mov rcx, [rax+16]
    lea rdx, [game_dir]
    call wcopy
    lea rcx, [game_dir]
    call cut_last_component
.nogame:
    xor ecx, ecx
    lea rdx, [exe_path]
    mov r8d, 520
    call GetModuleFileNameW
    test eax, eax
    jz .bad
    cmp eax, 519
    jae .bad
    lea rcx, [exe_path]
    lea rdx, [exe_dir]
    call wcopy
    lea rcx, [exe_dir]
    call cut_last_component
    lea rcx, [e_local]
    lea rdx, [local_app]
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jz .bad
    cmp eax, 400
    ja .bad
    lea rcx, [mod_dir]
    lea rdx, [f_mod]
    lea r8, [local_app]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_cfg]
    call wsprintfW
    lea rcx, [p1]
    call ensure_dirs
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; Reads and validates launcher.cfg. eax=1 valid. Sets cfg_mode (1 host, 2 join), cfg_port, cfg_player, cfg_local, a_*, w_*
FN load_config
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_cfg]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    cmp rax, 0
    jle .bad
    mov [cfg_len], rax
    lea rcx, [file_buf]
    mov byte [rcx+rax], 0
    lea rcx, [k_mode]
    lea rdx, [a_mode]
    mov r8d, 16
    call cfg_get
    lea rcx, [a_mode]
    lea rdx, [a_host_s]
    call a_equal
    test eax, eax
    jz .notHost
    mov dword [cfg_mode], 1
    jmp .modeOk
.notHost:
    lea rcx, [a_mode]
    lea rdx, [a_join_s]
    call a_equal
    test eax, eax
    jz .bad
    mov dword [cfg_mode], 2
.modeOk:
    lea rcx, [k_port]
    lea rdx, [a_port]
    mov r8d, 16
    call cfg_get
    mov dword [cfg_port], 7777
    test eax, eax
    jz .portOk
    lea rcx, [a_port]
    call a2i
    cmp eax, 1
    jl .bad
    cmp eax, 65535
    jg .bad
    mov [cfg_port], eax
.portOk:
    lea rcx, [k_room]
    lea rdx, [a_room]
    mov r8d, 16
    call cfg_get
    test eax, eax
    jnz .haveRoom
    lea rsi, [room_default]            ; no room code configured: everyone uses the built-in default
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
.haveRoom:
    lea rcx, [a_room]
    call v_room
    test eax, eax
    jz .bad
    lea rcx, [k_pass]                  ; optional room password; an unusable one stops multiplayer, never opens the room
    lea rdx, [a_pass]
    mov r8d, 72
    call cfg_get
    lea rcx, [a_pass]
    call v_pass
    test eax, eax
    jz .bad
    cmp dword [cfg_mode], 1
    jne .join
    mov dword [cfg_player], 0
    mov eax, [cfg_port]
    mov [cfg_local], eax
    mov byte [a_host], 0
    jmp .convert
.join:
    lea rcx, [k_player]
    lea rdx, [a_player]
    mov r8d, 16
    call cfg_get
    lea rcx, [a_player]
    call a2i
    cmp eax, 1
    jl .bad
    cmp eax, 7
    jg .bad
    mov [cfg_player], eax
    add eax, [cfg_port]
    cmp eax, 65535
    ja .bad
    mov [cfg_local], eax
    lea rcx, [k_host]
    lea rdx, [a_host]
    mov r8d, 32
    call cfg_get
    lea rcx, [a_host]
    call v_ipv4
    test eax, eax
    jz .bad
.convert:
    lea rcx, [a_host]
    call lstrlenA
    mov r8d, eax
    lea rcx, [w_host]
    lea rdx, [a_host]
    call ascii_to_wide
    lea rcx, [w_room]
    lea rdx, [a_room]
    mov r8d, 8
    call ascii_to_wide
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN



FN get_uid
    ; Steam identity probe (a separate process, so a Steam problem can never stop the launcher)
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [exe_dir]
    lea r9, [n_probe]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    test eax, eax
    jz .local
    lea rcx, [p2]
    lea rdx, [f_slash]
    lea r8, [game_dir]
    lea r9, [n_dll]
    call wsprintfW
    lea rcx, [p2]
    call file_exists
    test eax, eax
    jz .local
    lea rcx, [p3]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_steamtmp]
    call wsprintfW
    mov dword [sa], 24
    mov qword [sa+8], 0
    mov dword [sa+16], 1
    lea rcx, [p3]
    mov edx, 0x40000000
    mov r8d, 1
    lea r9, [sa]
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .local
    mov r12, rax
    lea rcx, [cmd_buf]
    lea rdx, [f_probecmd]
    lea r8, [p1]
    lea r9, [p2]
    call wsprintfW
    lea rcx, [cmd_buf]
    lea rdx, [game_dir]
    mov r8, r12
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .closefile
    mov r13, rax
    mov rcx, r13
    mov edx, 5000
    call WaitForSingleObject
    test eax, eax
    jz .waited
    mov rcx, r13
    mov edx, 1
    call TerminateProcess
    mov rcx, r13
    mov edx, 1000
    call WaitForSingleObject
.waited:
    mov rcx, r13
    call CloseHandle
.closefile:
    mov rcx, r12
    call CloseHandle
    lea rcx, [p3]
    lea rdx, [file_buf]
    mov r8d, 200
    call read_file
    mov r13, rax
    lea rcx, [p3]
    call DeleteFileW
    cmp r13, 23
    jl .local
    lea rsi, [file_buf]
    cmp dword [rsi], 'stea'
    jne .local
    cmp word [rsi+4], 'm:'
    jne .local
    mov ecx, 6
.dig:
    movzx eax, byte [rsi+rcx]
    sub eax, '0'
    cmp eax, 9
    ja .local
    inc ecx
    cmp ecx, 23
    jb .dig
    cmp r13, 23
    je .copy
    movzx eax, byte [rsi+23]
    cmp al, 13
    je .copy
    cmp al, 10
    je .copy
    test al, al
    jnz .local
.copy:
    lea rdi, [uid_a]
    mov ecx, 23
    rep movsb
    mov byte [rdi], 0
    jmp .done
.local:
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_identity]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 400
    call read_file
    cmp rax, 0
    jle .make
    mov rdx, rax
    lea rcx, [file_buf]
    lea r8, [needle_local]
    mov r9d, needle_local_len
    call find_bytes
    test rax, rax
    jz .make
    lea rsi, [rax+needle_local_len]
    xor ecx, ecx
.h: movzx eax, byte [rsi+rcx]
    cmp al, '0'
    jb .make
    cmp al, '9'
    jbe .hok
    cmp al, 'a'
    jb .make
    cmp al, 'f'
    ja .make
.hok:
    inc ecx
    cmp ecx, 32
    jb .h
    lea rdi, [uid_a]
    mov dword [rdi], 'loca'
    mov word [rdi+4], 'l:'
    add rdi, 6
    mov ecx, 32
    rep movsb
    mov byte [rdi], 0
    jmp .done
.make:
    lea rdi, [uid_a]
    mov dword [rdi], 'loca'
    mov word [rdi+4], 'l:'
    lea rcx, [uid_a+6]
    call guid_hex
    lea rcx, [utf8]
    lea rdx, [json_identity]
    lea r8, [uid_a]
    call wsprintfA
    mov r8d, eax
    lea rcx, [p1]
    lea rdx, [utf8]
    call write_file
.done:
END_FN

; rcx = 1 enabled / 0 disabled. Writes mod_data\mistrimulti\control.json (compact JSON, validated pieces only). eax=1 ok
FN write_control
    mov r12d, ecx
    lea rcx, [bridge_dir]
    lea rdx, [bridge_fwd]
    call wcopy
    lea rcx, [bridge_fwd]
    call to_forward
    mov ecx, 65001
    xor edx, edx
    lea r8, [bridge_fwd]
    mov r9d, -1
    lea rax, [file_buf]
    mov [rsp+32], rax
    mov qword [rsp+40], 3000
    mov qword [rsp+48], 0
    mov qword [rsp+56], 0
    call WideCharToMultiByte
    test eax, eax
    jz .bad
    lea rcx, [utf8]
    lea rdx, [json_control]
    lea r8, [json_false]
    test r12d, r12d
    jz .en
    lea r8, [json_true]
.en:
    lea r9, [a_host_s]
    cmp dword [cfg_mode], 1
    je .m
    lea r9, [a_join_s]
    cmp dword [cfg_mode], 2
    je .m
    lea r9, [a_idle_s]
.m: mov eax, [cfg_player]
    mov [rsp+32], rax
    lea rax, [uid_a]
    mov [rsp+40], rax
    lea rax, [epoch_a]
    mov [rsp+48], rax
    lea rax, [file_buf]
    mov [rsp+56], rax
    call wsprintfA
    cmp eax, 1000
    jae .bad
    mov r8d, eax
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_control]
    call wsprintfW
    lea rcx, [utf8]
    call lstrlenA
    mov r8d, eax
    lea rcx, [p1]
    lea rdx, [utf8]
    call write_file
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; Writes <bridge>\auth.cfg for the helper: where it keeps the install key and the key store, the deny list, and the room
; password (docs/SECURITY.md). Rewritten at every start, so a removed password disappears. eax=1 ok.
FN write_auth
    mov ecx, 65001
    xor edx, edx
    lea r8, [mod_dir]
    mov r9d, -1
    lea rax, [file_buf]
    mov [rsp+32], rax
    mov qword [rsp+40], 3000
    mov qword [rsp+48], 0
    mov qword [rsp+56], 0
    call WideCharToMultiByte
    test eax, eax
    jz .bad
    lea r12, [auth_buf]
    mov rcx, r12
    lea rdx, [f_auth_key]
    lea r8, [file_buf]
    call wsprintfA
    add r12, rax
    mov rcx, r12
    lea rdx, [f_auth_keys]
    lea r8, [file_buf]
    call wsprintfA
    add r12, rax
    mov rcx, r12
    lea rdx, [f_auth_deny]
    lea r8, [file_buf]
    call wsprintfA
    add r12, rax
    cmp byte [a_pass], 0
    je .nopass
    mov rcx, r12
    lea rdx, [f_auth_pass]
    lea r8, [a_pass]
    call wsprintfA
    add r12, rax
.nopass:
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    lea r9, [n_authcfg]
    call wsprintfW
    lea r8, [auth_buf]
    sub r12, r8
    mov r8, r12
    lea rcx, [p1]
    lea rdx, [auth_buf]
    call write_file
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN prepare_bridge
    lea rcx, [bridge_dir]
    lea rdx, [f_bridge]
    lea r8, [mod_dir]
    mov r9d, [cfg_player]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    lea r9, [n_stop]
    call wsprintfW
    lea rcx, [p1]
    call ensure_dirs
    ; remove only this helper's own transient files
    xor r12d, r12d
.names:
    cmp r12d, 5
    jae .rx
    lea rax, [name_table]
    mov r9, [rax+r12*8]
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    call wsprintfW
    lea rcx, [p1]
    call DeleteFileW
    inc r12d
    jmp .names
.rx:
    xor r12d, r12d
.rxl:
    cmp r12d, 8
    jae .wk0
    lea rcx, [p2]
    lea rdx, [f_rx]
    mov r8d, r12d
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    lea r9, [p2]
    call wsprintfW
    lea rcx, [p1]
    call DeleteFileW
    inc r12d
    jmp .rxl
.wk0:                                   ; session keys of an earlier run (world_<slot>.key) must not outlive it
    xor r12d, r12d
.wk:
    cmp r12d, 8
    jae .d
    lea rcx, [p1]
    lea rdx, [bridge_dir]
    mov r8d, r12d
    call wf_key_path
    lea rcx, [p1]
    call DeleteFileW
    inc r12d
    jmp .wk
.d:
END_FN

FN is_stamp                     ; rcx wide: eax 1 if "YYYYMMDD-HHMMSS"
    xor edx, edx
.l: movzx eax, word [rcx+rdx*2]
    cmp edx, 15
    je .end
    test ax, ax
    jz .no
    cmp edx, 8
    jne .dig
    cmp ax, '-'
    jne .no
    jmp .n
.dig:
    sub eax, '0'
    cmp eax, 9
    ja .no
.n: inc edx
    jmp .l
.end:
    cmp word [rcx+30], 0
    jne .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; keeps the 10 newest backup folders (names are timestamps) under p2 = solo_backups; only our own timestamp folders are touched
FN prune_backups
    mov r15d, 64
.again:
    dec r15d
    jz .d
    xor r12d, r12d                         ; count
    mov word [minname], 0
    lea rcx, [p3]
    lea rdx, [f_star]
    lea r8, [p2]
    call wsprintfW
    lea rcx, [p3]
    lea rdx, [fd]
    call FindFirstFileW
    cmp rax, -1
    je .d
    mov r13, rax
.scan:
    test dword [fd], 0x10
    jz .nx
    lea rcx, [fd+44]
    call is_stamp
    test eax, eax
    jz .nx
    inc r12d
    cmp word [minname], 0
    je .take
    lea rcx, [fd+44]
    lea rdx, [minname]
    call lstrcmpiW
    test eax, eax
    jns .nx
.take:
    lea rcx, [fd+44]
    lea rdx, [minname]
    call wcopy
.nx:
    mov rcx, r13
    lea rdx, [fd]
    call FindNextFileW
    test eax, eax
    jnz .scan
    mov rcx, r13
    call FindClose
    cmp r12d, 10
    jbe .d
    lea rcx, [p3]
    lea rdx, [f_slash]
    lea r8, [p2]
    lea r9, [minname]
    call wsprintfW
    lea rcx, [names]
    lea rdx, [f_star]
    lea r8, [p3]
    call wsprintfW
    lea rcx, [names]
    lea rdx, [fd]
    call FindFirstFileW
    cmp rax, -1
    je .rmdir
    mov r13, rax
.del:
    test dword [fd], 0x10
    jnz .dn
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [p3]
    lea r9, [fd+44]
    call wsprintfW
    lea rcx, [p1]
    call DeleteFileW
.dn:
    mov rcx, r13
    lea rdx, [fd]
    call FindNextFileW
    test eax, eax
    jnz .del
    mov rcx, r13
    call FindClose
.rmdir:
    lea rcx, [p3]
    call RemoveDirectoryW
    test eax, eax
    jnz .again
.d:
END_FN

; Copies the solo saves to mod_data\mistrimulti\solo_backups\<timestamp>. Copy only; never changes the saves.
FN backup_saves
    lea rcx, [p1]
    lea rdx, [f_saves]
    lea r8, [local_app]
    call wsprintfW
    lea rcx, [p2]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_backups]
    call wsprintfW
    lea rcx, [p3]
    lea rdx, [f_slash]
    lea r8, [p2]
    lea r9, [n_stop]
    call wsprintfW
    lea rcx, [p3]
    call ensure_dirs
    lea rcx, [st]
    call GetLocalTime
    lea rcx, [p3]
    lea rdx, [f_stamp]
    movzx r8d, word [st]
    movzx r9d, word [st+2]
    movzx eax, word [st+6]
    mov [rsp+32], rax
    movzx eax, word [st+8]
    mov [rsp+40], rax
    movzx eax, word [st+10]
    mov [rsp+48], rax
    movzx eax, word [st+12]
    mov [rsp+56], rax
    call wsprintfW
    lea rcx, [cmd_buf]
    lea rdx, [f_cat]
    lea r8, [p2]
    lea r9, [p3]
    call wsprintfW
    lea rcx, [cmd_buf]
    xor edx, edx
    call CreateDirectoryW
    lea rcx, [p3]
    lea rdx, [f_star]
    lea r8, [p1]
    call wsprintfW
    lea rcx, [p3]
    lea rdx, [fd]
    call FindFirstFileW
    cmp rax, -1
    je .prune
    mov r13, rax
.each:
    test dword [fd], 0x10
    jnz .nx
    lea rcx, [p3]
    lea rdx, [f_slash]
    lea r8, [p1]
    lea r9, [fd+44]
    call wsprintfW
    lea rcx, [names]
    lea rdx, [f_slash]
    lea r8, [cmd_buf]
    lea r9, [fd+44]
    call wsprintfW
    lea rcx, [p3]
    lea rdx, [names]
    xor r8d, r8d
    call CopyFileW
.nx:
    mov rcx, r13
    lea rdx, [fd]
    call FindNextFileW
    test eax, eax
    jnz .each
    mov rcx, r13
    call FindClose
.prune:
    call prune_backups
END_FN

; Starts the network helper hidden. eax=1 if it is running after a short wait
; A joining player refreshes the host's world just before the game starts (quietly: failures are fine).
FN join_refresh_world
    cmp dword [cfg_mode], 2
    jne .d
    lea rcx, [a_host]
    call inet_addr
    cmp eax, -1
    je .d
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [f_mpsaves_dir]
    lea r8, [local_app]
    call wsprintfW
    mov dword [wf_connect_ms], 1500
    lea rcx, [bridge_dir]
    mov edx, [cfg_player]
    call world_use_session
    call GetTickCount64                 ; the world is released only to a joined player: wait for the helper's WELCOME
    add rax, 5000
    mov r13, rax
.wait:
    mov rcx, [wf_keypath]
    call wa_load_key
    test eax, eax
    jnz .go
    call GetTickCount64
    cmp rax, r13
    jae .d
    mov ecx, 150
    call Sleep
    jmp .wait
.go:
    mov ecx, r12d
    lea rdx, [p1]
    call world_fetch
.d:
END_FN

; Host side of the world server: ecx = slot of the guest -> eax 1 with its session key in wa_key (worldauth.inc)
FN wf_key_for_slot
    mov r8d, ecx
    lea rcx, [wf_path2]
    lea rdx, [bridge_dir]
    call wf_key_path
    lea rcx, [wf_path2]
    call wa_load_key
END_FN

FN start_helper
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [exe_dir]
    lea r9, [n_helper]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    test eax, eax
    jz .bad
    lea rcx, [bridge_dir]
    lea rdx, [bridge_fwd]
    call wcopy
    lea rcx, [bridge_fwd]
    call to_forward
    cmp dword [cfg_mode], 1
    jne .join
    lea rcx, [cmd_buf]
    lea rdx, [f_helpercmd_host]
    lea r8, [exe_dir]
    mov r9d, [cfg_local]
    mov eax, [cfg_player]
    mov [rsp+32], rax
    lea rax, [w_room]
    mov [rsp+40], rax
    lea rax, [bridge_fwd]
    mov [rsp+48], rax
    call wsprintfW
    jmp .go
.join:
    lea rcx, [cmd_buf]
    lea rdx, [f_helpercmd_join]
    lea r8, [exe_dir]
    mov r9d, [cfg_local]
    mov eax, [cfg_player]
    mov [rsp+32], rax
    lea rax, [w_room]
    mov [rsp+40], rax
    lea rax, [bridge_fwd]
    mov [rsp+48], rax
    lea rax, [w_host]
    mov [rsp+56], rax
    mov eax, [cfg_port]
    mov [rsp+64], rax
    call wsprintfW
.go:
    lea rcx, [cmd_buf]
    lea rdx, [exe_dir]
    xor r8d, r8d
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .bad
    mov [h_helper], rax
    ; Tie the helper to this launcher: if the launcher is killed, Windows ends the helper too.
    xor ecx, ecx
    xor edx, edx
    call CreateJobObjectW
    test rax, rax
    jz .nojob
    mov [h_job], rax
    lea rdi, [jobinfo]
    xor eax, eax
    mov ecx, 144
    rep stosb
    mov dword [jobinfo+16], 0x2000        ; JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    mov rcx, [h_job]
    mov edx, 9                            ; JobObjectExtendedLimitInformation
    lea r8, [jobinfo]
    mov r9d, 144
    call SetInformationJobObject
    mov rcx, [h_job]
    mov rdx, [h_helper]
    call AssignProcessToJobObject
.nojob:
    mov rcx, [h_helper]
    mov edx, 400
    call WaitForSingleObject
    cmp eax, 258                    ; WAIT_TIMEOUT = still running
    je .ok
    mov rcx, [h_helper]
    call CloseHandle
    mov qword [h_helper], 0
.bad:
    xor eax, eax
    jmp .d
.ok:
    mov eax, 1
.d:
END_FN

FN stop_helper
    cmp qword [h_helper], 0
    je .d
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    lea r9, [n_stop]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [t_stop]
    mov r8d, t_stop_len
    call write_file
    mov rcx, [h_helper]
    mov edx, 2500
    call WaitForSingleObject
    test eax, eax
    jz .closed
    mov rcx, [h_helper]
    mov edx, 1
    call TerminateProcess
.closed:
    mov rcx, [h_helper]
    call CloseHandle
    mov qword [h_helper], 0
    mov rcx, [h_job]                ; the job only exists to end a helper that outlives the launcher
    test rcx, rcx
    jz .d
    call CloseHandle
    mov qword [h_job], 0
.d:
END_FN

; ---------------- host discovery ----------------
; While hosting, answer "who is hosting?" queries on UDP 7776 so friends can find this PC without typing an IP.
; Query:  exactly 64 bytes starting "MSDQ", version 1.  Reply: 64 bytes "MSDR", version 1, flags, game port, computer name.
; The reply is never larger than the query, so this cannot be used to amplify traffic.
FN disc_start
    mov qword [disc_sock], 0
    cmp dword [cfg_mode], 1
    jne .d
    mov ecx, 0x0202
    lea rdx, [wsadata]
    call WSAStartup
    test eax, eax
    jnz .d
    mov ecx, 2                      ; AF_INET
    mov edx, 2                      ; SOCK_DGRAM
    mov r8d, 17                     ; IPPROTO_UDP
    call socket
    cmp rax, -1
    je .d
    mov rbx, rax
    lea rdi, [disc_from]
    xor eax, eax
    mov ecx, 16
    rep stosb
    mov word [disc_from], 2         ; AF_INET, port 7776 (0x1E60) in network order, address 0.0.0.0
    mov word [disc_from+2], 0x601E
    mov rcx, rbx
    lea rdx, [disc_from]
    mov r8d, 16
    call bind
    test eax, eax
    jnz .fail
    mov [disc_sock], rbx
    ; the host's world is offered on TCP 7775 (see world.inc)
    mov qword [tcp_sock], 0
    mov ecx, 2
    mov edx, 1
    mov r8d, 6
    call socket
    cmp rax, -1
    je .notcp
    mov r12, rax
    lea rdi, [disc_from]
    xor eax, eax
    mov ecx, 16
    rep stosb
    mov word [disc_from], 2
    mov word [disc_from+2], WF_PORT_NET
    mov rcx, r12
    lea rdx, [disc_from]
    mov r8d, 16
    call bind
    test eax, eax
    jnz .tcpfail
    mov rcx, r12
    mov edx, 1
    call listen
    test eax, eax
    jnz .tcpfail
    mov [tcp_sock], r12
    jmp .notcp
.tcpfail:
    mov rcx, r12
    call closesocket
.notcp:
    ; prepare the fixed part of the reply
    lea rdi, [disc_resp]
    xor eax, eax
    mov ecx, 64
    rep stosb
    mov dword [disc_resp], 'MSDR'
    mov byte [disc_resp+4], 1
    lea rcx, [a_room]
    lea rdx, [room_default]
    call a_equal
    xor eax, 1                      ; flag bit 0: this host uses a custom room code
    cmp byte [a_pass], 0
    je .nopassflag
    or al, 2                            ; flag bit 1: this host needs a room password
.nopassflag:
    mov [disc_resp+5], al
    mov eax, [cfg_port]
    mov [disc_resp+6], ax
    mov dword [q_len], 31
    lea rcx, [disc_resp+8]
    lea rdx, [q_len]
    call GetComputerNameA
    jmp .d
.fail:
    mov rcx, rbx
    call closesocket
.d:
END_FN

; Newest valid multiplayer save -> eax 1, with ws_name (ASCII), ws_path (wide), ws_size
FN world_find_newest
    mov qword [ws_best], 0
    mov dword [ws_size], 0
    mov byte [ws_name], 0
    lea rcx, [p1]
    lea rdx, [f_mpsaves_star]
    lea r8, [local_app]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [fd]
    call FindFirstFileW
    cmp rax, -1
    je .none
    mov r13, rax
.each:
    test dword [fd], 0x10
    jnz .next
    cmp dword [fd+28], 0                ; size high word must be 0
    jne .next
    mov eax, [fd+32]
    test eax, eax
    jz .next
    cmp eax, WF_MAX_FILE
    ja .next
    lea rcx, [ws_tmp]
    lea rdx, [fd+44]
    mov r8d, 80
    call wide_to_ascii
    lea rcx, [ws_tmp]
    call wf_valid_name
    test eax, eax
    jz .next
    cmp dword [wh_id], 0
    je .anyworld
    lea rcx, [ws_tmp]
    call wf_name_id
    cmp eax, [wh_id]                    ; the mod named the world being played: only that world's saves count
    jne .next
.anyworld:
    mov rax, [fd+20]                    ; last write time
    cmp rax, [ws_best]
    jbe .next
    mov [ws_best], rax
    mov eax, [fd+32]
    mov [ws_size], eax
    lea rsi, [ws_tmp]
    lea rdi, [ws_name]
    mov ecx, 80
    rep movsb
.next:
    mov rcx, r13
    lea rdx, [fd]
    call FindNextFileW
    test eax, eax
    jnz .each
    mov rcx, r13
    call FindClose
    cmp qword [ws_best], 0
    je .none
    lea rcx, [ws_path]
    lea rdx, [f_mpsaves_file]
    lea r8, [local_app]
    lea r9, [ws_name]
    call wsprintfW
    mov eax, 1
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

; Serves one waiting connection: sends the newest multiplayer save with its SHA-256. Never reads a path from the client.
FN world_serve
    mov dword [ws_fromlen], 32
    mov rcx, [tcp_sock]
    lea rdx, [ws_from]
    lea r8, [ws_fromlen]
    call accept
    cmp rax, -1
    je .d
    mov rbx, rax
    mov [wf_sock], rbx
    mov dword [ws_timeout], 15000
    mov rcx, rbx
    mov edx, 0xFFFF                    ; SOL_SOCKET
    mov r8d, 0x1006                    ; SO_RCVTIMEO
    lea r9, [ws_timeout]
    mov qword [rsp+32], 4
    call setsockopt
    mov rcx, rbx
    mov edx, 0xFFFF
    mov r8d, 0x1005                    ; SO_SNDTIMEO
    lea r9, [ws_timeout]
    mov qword [rsp+32], 4
    call setsockopt
    call wa_serve_auth                 ; nothing is read from disk or sent before the client proved its join session
    test eax, eax
    jz .close
    lea rdi, [wf_hdr]
    xor eax, eax
    mov ecx, 144
    rep stosb
    mov dword [wf_hdr], 'MSWR'
    mov byte [wf_hdr+4], 2
    xor r12d, r12d                     ; file buffer
    call wh_state                      ; the world the mod says the host plays now; its newest save (any newest save without a note)
    test eax, eax
    jz .nosave
    mov r13d, [ws_size]
    xor ecx, ecx
    mov edx, r13d
    mov r8d, 0x3000
    mov r9d, 4
    call VirtualAlloc
    test rax, rax
    jz .cannot
    mov r12, rax
    lea rcx, [ws_path]
    mov rdx, r12
    mov r8d, r13d
    call read_file
    cmp rax, r13
    jne .cannot
    mov rcx, r12
    mov edx, r13d
    lea r8, [wf_hdr+12]
    call sha256_raw
    test eax, eax
    jz .cannot
    mov [wf_hdr+8], r13d
    lea rsi, [ws_name]
    lea rdi, [wf_hdr+48]
    mov ecx, 63
    rep movsb
    call wh_fill_hdr
    call wa_sign_header
    lea rcx, [wf_hdr]
    mov edx, 144
    call wf_send_all
    test eax, eax
    jz .free
    mov rcx, r12
    mov edx, r13d
    call wf_send_all
    jmp .free
.nosave:
    mov byte [wf_hdr+5], 1
    cmp dword [wh_id], 0
    je .sendhdr
    mov byte [wf_hdr+5], 4             ; the host plays a world it has not saved: nothing downloadable is that world
    jmp .sendhdr
.cannot:
    lea rdi, [wf_hdr+8]
    xor eax, eax
    mov ecx, 104
    rep stosb
    mov byte [wf_hdr+5], 2
.sendhdr:
    call wh_fill_hdr
    call wa_sign_header
    lea rcx, [wf_hdr]
    mov edx, 144
    call wf_send_all
.free:
    test r12, r12
    jz .close
    mov rcx, r12
    xor edx, edx
    mov r8d, 0x8000
    call VirtualFree
.close:
    mov rcx, rbx
    mov edx, 1                         ; SD_SEND
    call shutdown
    mov rcx, rbx
    call closesocket
.d:
END_FN

; Waits for the game process (rcx handle) while answering discovery queries and world downloads.
FN disc_serve
    mov r12, rcx
.loop:
    cmp qword [disc_sock], 0
    jne .have
    cmp qword [tcp_sock], 0
    jne .have
    mov rcx, r12                        ; standby or joined: nothing listens, so just wait a moment for the game to end
    mov edx, 250
    call WaitForSingleObject
    jmp .check
.have:
    mov rax, [disc_sock]
    mov [disc_pfds], rax
    mov word [disc_pfds+8], 0x0100      ; POLLRDNORM
    mov word [disc_pfds+10], 0
    mov rax, [tcp_sock]
    mov [disc_pfds+16], rax
    mov word [disc_pfds+24], 0x0100
    mov word [disc_pfds+26], 0
    mov edx, 1
    cmp qword [tcp_sock], 0
    je .poll
    mov edx, 2
.poll:
    lea rcx, [disc_pfds]
    mov r8d, 250
    call WSAPoll
    test eax, eax
    jle .check
    test word [disc_pfds+26], 0x0100
    jz .udp
    call world_serve
.udp:
    test word [disc_pfds+10], 0x0100
    jz .check
    mov dword [disc_fromlen], 32
    mov rcx, [disc_sock]
    lea rdx, [disc_buf]
    mov r8d, 128
    xor r9d, r9d
    lea rax, [disc_from]
    mov [rsp+32], rax
    lea rax, [disc_fromlen]
    mov [rsp+40], rax
    call recvfrom
    cmp eax, 64
    jne .check
    cmp dword [disc_buf], 'MSDQ'
    jne .check
    cmp byte [disc_buf+4], 1
    jne .check
    call wh_disc_flags
    mov rcx, [disc_sock]
    lea rdx, [disc_resp]
    mov r8d, 64
    xor r9d, r9d
    lea rax, [disc_from]
    mov [rsp+32], rax
    mov eax, [disc_fromlen]
    mov [rsp+40], rax
    call sendto
.check:
    call sv_poll                        ; commands from the in-game menu (launcher/menu.inc)
    mov rcx, r12
    xor edx, edx
    call WaitForSingleObject
    test eax, eax
    jnz .loop
    call disc_stop
.d:
END_FN

; Runs the game command line (everything after "--steam") and waits for it. Sets game_exit.
FN launch_game
    mov dword [game_exit], 1
    mov rsi, [cmd_rest]
    lea rdi, [cmd_buf]
    xor ecx, ecx
.cp:
    movzx eax, word [rsi+rcx*2]
    mov [rdi+rcx*2], ax
    test ax, ax
    jz .copied
    inc ecx
    cmp ecx, 2040
    jb .cp
    jmp .d                          ; absurdly long command line: refuse
.copied:
    lea rcx, [cmd_buf]
    xor edx, edx
    cmp word [game_dir], 0
    je .nowd
    lea rdx, [game_dir]
.nowd:
    xor r8d, r8d
    xor r9d, r9d
    call spawn
    test rax, rax
    jz .d
    mov rbx, rax
    cmp dword [sv_serving], 0           ; the plain no-multiplayer start just waits for the game
    jne .serve
    mov rcx, rbx
    mov edx, -1
    call WaitForSingleObject
    jmp .waited
.serve:
    mov rcx, rbx
    call disc_serve
.waited:
    mov rcx, rbx
    lea rdx, [game_exit]
    call GetExitCodeProcess
    mov rcx, rbx
    call CloseHandle
.d:
END_FN

; Puts  "<launcher>" --steam %command%  on the clipboard so it can simply be pasted into Steam. Failures are ignored.
FN copy_launch_option
    lea rcx, [names]
    lea rdx, [f_launchopt]
    lea r8, [exe_path]
    call wsprintfW
    lea rcx, [names]
    lea rdx, [s_command]
    lea r8, [p2]
    call join_wide
    lea rcx, [p2]
    call clip_set
END_FN

; ---------------- console (configure) ----------------
FN say                          ; rcx ASCII
    mov r12, rcx
    call lstrlenA
    mov r8d, eax
    mov rcx, [h_out]
    mov rdx, r12
    lea r9, [q_len]
    mov qword [rsp+32], 0
    call WriteFile
END_FN

; next input byte -> eax, or -1 at end of input (refills from stdin; works for consoles and pipes)
FN getc
    mov eax, [in_pos]
    cmp eax, [in_len]
    jb .have
    mov rcx, [h_in]
    lea rdx, [inbuf]
    mov r8d, 250
    lea r9, [q_len]
    mov qword [rsp+32], 0
    call ReadFile
    test eax, eax
    jz .eof
    mov eax, [q_len]
    test eax, eax
    jz .eof
    mov [in_len], eax
    mov dword [in_pos], 0
.have:
    mov eax, [in_pos]
    lea rcx, [inbuf]
    movzx eax, byte [rcx+rax]
    inc dword [in_pos]
    jmp .d
.eof:
    mov dword [in_pos], 0
    mov dword [in_len], 0
    mov eax, -1
.d:
END_FN

; rcx prompt, rdx out buffer, r8 size -> eax length, -1 at end of input. Spaces and the line ending are dropped.
FN ask
    mov r12, rdx
    mov r13, r8
    dec r13
    call say
    xor r14d, r14d                  ; characters stored
    xor r15d, r15d                  ; bytes seen
.ch:
    call getc
    cmp eax, -1
    je .end
    inc r15d
    cmp al, 10
    je .e
    cmp al, 13
    je .ch
    cmp al, ' '
    je .ch
    cmp r14, r13
    jae .ch
    mov [r12+r14], al
    inc r14
    jmp .ch
.end:
    test r15d, r15d
    jz .eof
.e: mov byte [r12+r14], 0
    mov eax, r14d
    jmp .d
.eof:
    mov byte [r12], 0
    mov eax, -1
.d:
END_FN

configure_main:
    mov ecx, -10
    call GetStdHandle
    mov [h_in], rax
    mov ecx, -11
    call GetStdHandle
    mov [h_out], rax
    cmp qword [h_in], 0
    je .alloc
    cmp qword [h_in], -1
    je .alloc
    cmp qword [h_out], 0
    je .alloc
    cmp qword [h_out], -1
    jne .have
.alloc:
    call AllocConsole
    mov ecx, 65001
    call SetConsoleOutputCP
    mov ecx, -10
    call GetStdHandle
    mov [h_in], rax
    mov ecx, -11
    call GetStdHandle
    mov [h_out], rax
.have:
    call setup_paths
    test eax, eax
    jz cfg_giveup
    call load_config
    mov [have_old], eax
    test eax, eax
    jnz .keeppass
    mov byte [a_pass], 0
.keeppass:
    lea rcx, [t_optional]
    call say
    mov eax, [cfg_mode]
    mov [old_mode], eax
    mov eax, [cfg_player]
    mov [old_player], eax
    mov r14d, 5
.ask_mode:
    dec r14d
    js cfg_giveup
    lea rcx, [p_mode]
    lea rdx, [ans]
    mov r8d, 60
    call ask
    cmp eax, -1
    je cfg_giveup
    test eax, eax
    jz .mode_empty
    movzx eax, byte [ans]
    or al, 32
    cmp al, 'h'
    je .is_host
    cmp al, 'j'
    je .is_join
    jmp .mode_bad
.mode_empty:
    cmp dword [have_old], 0
    je .mode_bad
    mov eax, [cfg_mode]
    cmp eax, 1
    je .is_host
    jmp .is_join
.mode_bad:
    lea rcx, [t_bad]
    call say
    jmp .ask_mode
.is_host:
    mov dword [cfg_mode], 1
    lea rdi, [a_mode]
    mov dword [rdi], 'host'
    mov byte [rdi+4], 0
    mov byte [a_host], 0
    mov dword [cfg_player], 0
    jmp .port
.is_join:
    mov dword [cfg_mode], 2
    lea rdi, [a_mode]
    mov dword [rdi], 'join'
    mov byte [rdi+4], 0
    mov r14d, 5
.ask_ip:
    dec r14d
    js cfg_giveup
    lea rcx, [p_ip]
    lea rdx, [ans]
    mov r8d, 32
    call ask
    cmp eax, -1
    je cfg_giveup
    lea rcx, [ans]
    call v_ipv4
    test eax, eax
    jz .ip_bad
    lea rsi, [ans]
    lea rdi, [a_host]
    mov ecx, 32
    rep movsb
    jmp .port
.ip_bad:
    lea rcx, [t_bad]
    call say
    jmp .ask_ip
.port:
    mov r14d, 5
.ask_port:
    dec r14d
    js cfg_giveup
    lea rcx, [p_port]
    lea rdx, [ans]
    mov r8d, 16
    call ask
    cmp eax, -1
    je cfg_giveup
    test eax, eax
    jnz .port_val
    mov dword [cfg_port], 7777
    jmp .after_port
.port_val:
    lea rcx, [ans]
    call a2i
    cmp eax, 1
    jl .port_bad
    cmp eax, 65535
    jg .port_bad
    mov [cfg_port], eax
    jmp .after_port
.port_bad:
    lea rcx, [t_bad]
    call say
    jmp .ask_port
.after_port:
    cmp dword [cfg_mode], 1
    je .host_room
    mov r14d, 5
.ask_player:
    dec r14d
    js cfg_giveup
    lea rcx, [p_player]
    lea rdx, [ans]
    mov r8d, 16
    call ask
    cmp eax, -1
    je cfg_giveup
    test eax, eax
    jnz .player_val
    cmp dword [old_mode], 2
    jne .rand
    mov eax, [old_player]
    cmp eax, 1
    jl .rand
    cmp eax, 7
    jg .rand
    mov [cfg_player], eax
    jmp .join_room
.rand:
    lea rcx, [file_buf]
    call guid_hex
    movzx eax, byte [guid]
    xor edx, edx
    mov ecx, 7
    div ecx
    inc edx
    mov [cfg_player], edx
    jmp .join_room
.player_val:
    lea rcx, [ans]
    call a2i
    cmp eax, 1
    jl .player_bad
    cmp eax, 7
    jg .player_bad
    mov [cfg_player], eax
    jmp .join_room
.player_bad:
    lea rcx, [t_bad]
    call say
    jmp .ask_player
.join_room:
    mov r14d, 5
.ask_room:
    dec r14d
    js cfg_giveup
    lea rcx, [p_room]
    lea rdx, [ans]
    mov r8d, 16
    call ask
    cmp eax, -1
    je cfg_giveup
    test eax, eax
    jz .room_default
    lea rcx, [ans]
    call v_room
    test eax, eax
    jz .room_bad
    lea rsi, [ans]
    lea rdi, [a_room]
    mov ecx, 16
    rep movsb
    jmp .save
.room_default:
    lea rsi, [room_default]
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
    jmp .save
.room_bad:
    lea rcx, [t_bad]
    call say
    jmp .ask_room
.host_room:
    ; a host keeps a custom room code it already had; otherwise the shared default is used
    cmp dword [old_mode], 1
    jne .defroom
    cmp dword [have_old], 0
    je .defroom
    lea rcx, [a_room]
    call v_room
    test eax, eax
    jnz .save
.defroom:
    lea rsi, [room_default]
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
.save:
    lea rcx, [utf8]
    lea rdx, [cfg_fmt]
    lea r8, [a_mode]
    lea r9, [a_host]
    mov eax, [cfg_port]
    mov [rsp+32], rax
    mov eax, [cfg_player]
    mov [rsp+40], rax
    lea rax, [a_room]
    mov [rsp+48], rax
    call wsprintfA
    cmp byte [a_pass], 0
    je .nopw
    lea rcx, [utf8]
    call lstrlenA
    lea rcx, [utf8]
    add rcx, rax
    lea rdx, [f_cfg_pass]
    lea r8, [a_pass]
    call wsprintfA
.nopw:
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_cfg]
    call wsprintfW
    lea rcx, [utf8]
    call lstrlenA
    mov r8d, eax
    lea rcx, [p1]
    lea rdx, [utf8]
    call write_file
    test eax, eax
    jz cfg_giveup
    mov ecx, 65001
    xor edx, edx
    lea r8, [exe_path]
    mov r9d, -1
    lea rax, [file_buf]
    mov [rsp+32], rax
    mov qword [rsp+40], 3000
    mov qword [rsp+48], 0
    mov qword [rsp+56], 0
    call WideCharToMultiByte
    call copy_launch_option
    lea rcx, [t_saved]
    call say
    lea rcx, [t_cmd1]
    call say
    lea rcx, [file_buf]
    call say
    lea rcx, [t_cmd2]
    call say
    cmp dword [cfg_mode], 1
    jne .joininfo
    lea rcx, [t_hostinfo]
    call say
    jmp .close
.joininfo:
    lea rcx, [utf8]
    lea rdx, [t_player]
    mov r8d, [cfg_player]
    call wsprintfA
    lea rcx, [utf8]
    call say
.close:
    lea rcx, [p_close]
    lea rdx, [ans]
    mov r8d, 60
    call ask
    xor ecx, ecx
    call ExitProcess
cfg_giveup:
    lea rcx, [t_giveup]
    call say
    mov ecx, 1
    call ExitProcess

; ---------------- --steam ----------------
FN skip_to_game_cmd
    call GetCommandLineW
    mov rsi, rax
    cmp word [rsi], '"'
    jne .unq
    add rsi, 2
.q: movzx eax, word [rsi]
    test ax, ax
    jz .end
    cmp ax, '"'
    je .qe
    add rsi, 2
    jmp .q
.qe:
    add rsi, 2
    jmp .sp1
.unq:
    movzx eax, word [rsi]
    test ax, ax
    jz .end
    cmp ax, ' '
    je .sp1
    add rsi, 2
    jmp .unq
.sp1:
    cmp word [rsi], ' '
    jne .tok2
    add rsi, 2
    jmp .sp1
.tok2:
    movzx eax, word [rsi]
    test ax, ax
    jz .end
    cmp ax, ' '
    je .sp2
    add rsi, 2
    jmp .tok2
.sp2:
    cmp word [rsi], ' '
    jne .end
    add rsi, 2
    jmp .sp2
.end:
    mov [cmd_rest], rsi
END_FN

; is argv[2] named FieldsOfMistria.exe ? eax 1/0
FN game_exe_ok
    mov rax, [argv]
    mov rsi, [rax+16]
    mov rdi, rsi
    xor r8, r8
    xor r9d, r9d
.l: movzx eax, word [rsi+r9*2]
    test ax, ax
    jz .e
    cmp ax, '\'
    je .s
    cmp ax, '/'
    jne .n
.s: lea r8, [r9+1]
.n: inc r9
    jmp .l
.e: lea rcx, [rdi+r8*2]
    lea rdx, [s_gameexe]
    call lstrcmpiW
    test eax, eax
    sete al
    movzx eax, al
END_FN

; Writes why multiplayer was not started to mod_data\mistrimulti\launcher.log (only when the folder is known)
FN log_reason
    cmp qword [reason], 0
    je .d
    cmp word [mod_dir], 0
    je .d
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_log]
    call wsprintfW
    mov rcx, [reason]
    call lstrlenA
    mov r8d, eax
    lea rcx, [p1]
    mov rdx, [reason]
    call write_file
.d:
END_FN

start:
    sub rsp, 8
    and rsp, -16
    sub rsp, 160
    call GetCommandLineW
    mov rcx, rax
    lea rdx, [argc]
    call CommandLineToArgvW
    mov [argv], rax
    cmp dword [argc], 2
    jb configure_main                 ; double-clicked: run the setup
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_configure]
    call wequal
    test eax, eax
    jnz configure_main
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_steam]
    call wequal
    test eax, eax
    jz .exit1
    cmp dword [argc], 3
    jb .exit1
    call skip_to_game_cmd
    call setup_paths                  ; best effort: game_dir is filled even when the rest fails
    mov r12d, eax
    call game_exe_ok
    lea rbx, [r_exe]
    test eax, eax
    jz .direct
    mov rcx, [cmd_rest]
    lea rdx, [s_direct]
    call wsubstr
    lea rbx, [r_flag]
    test eax, eax
    jnz .direct
    lea rbx, [r_paths]
    test r12d, r12d
    jz .direct
    call load_config
    mov [sv_legacy], eax              ; 1: a valid launcher.cfg (optional, advanced): that role starts by itself, as before
    call get_uid
    lea rcx, [epoch_a]
    call guid_hex
    cmp dword [sv_legacy], 0
    jne .legacy
    ; No launcher.cfg: standby. Nothing is hosted or joined and no port opens; the in-game Multiplayer menu decides.
    lea rbx, [r_control]
    call menu_init
    test eax, eax
    jz .direct
    lea rax, [r_standby]
    mov [reason], rax
    call log_reason
    call backup_saves
    jmp .run
.legacy:
    call menu_prepare
    call prepare_bridge
    call write_auth
    lea rbx, [r_auth]
    test eax, eax
    jnz .authok
    cmp byte [a_pass], 0                ; without a password the helper still works (its keys stay in memory)
    jne .direct
.authok:
    mov ecx, 1
    call write_control
    lea rbx, [r_control]
    test eax, eax
    jz .direct
    call backup_saves
    call start_helper
    test eax, eax
    jnz .legacy_up
    xor ecx, ecx
    call write_control
    lea rbx, [r_helper]
    jmp .direct
.legacy_up:
    mov eax, [cfg_mode]
    mov [sv_session], eax
    call join_refresh_world
    call disc_start
    mov ecx, ST_READY
    cmp dword [cfg_mode], 1
    jne .legacy_state
    call sv_collect_addrs
    mov ecx, ST_HOSTING
.legacy_state:
    xor edx, edx
    call sv_set
.run:
    call sv_daily_check
    mov dword [sv_serving], 1
    call launch_game
    call sess_stop
    mov ecx, ST_STOPPED
    xor edx, edx
    call sv_set
    mov ecx, [game_exit]
    call ExitProcess
.direct:
    mov [reason], rbx
    call log_reason
    call launch_game
    mov ecx, [game_exit]
    call ExitProcess
.exit1:
    mov ecx, 1
    call ExitProcess
