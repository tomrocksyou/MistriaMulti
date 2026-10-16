; MistriaMulti launcher for Linux and the Steam Deck (NASM, x86-64 ELF, raw system calls, no C runtime).
;   mistrimulti-launcher --steam <game command...>    Steam launch option:  "<folder>/mistrimulti-launcher" --steam %command%
;   mistrimulti-launcher --configure                  asks host / join once and saves launcher.cfg (also: no arguments)
; This is the Linux twin of launcher/launcher.asm and keeps its safety rules: the game is ALWAYS started, whatever fails
; first; every value read from launcher.cfg is validated strictly before it reaches a command line or a file; solo saves are
; only ever copied (never changed or removed). Shared pieces live in linux/*.inc and common/textutil.inc.
bits 64
default rel
%include "abi.inc"

section .text
%include "sys.inc"
%include "sha256.inc"
%include "config.inc"
%include "net.inc"
%include "worldserve.inc"
%include "menu.inc"

section .data
s_steam db '--steam',0
s_configure db '--configure',0
s_direct db '--mistrimulti-direct',0
s_gamename db 'fieldsofmistria',0
n_log db '/launcher.log',0
n_control db '/control.json',0
n_identity db '/local_identity.json',0
n_steamtmp db '/steamid.tmp',0
n_probe db '/mistrimulti-steam-id-linux',0
n_helper db '/mistrimulti-helper-linux',0
n_helperlog db '/helper.log',0
n_authcfg db '/auth.cfg',0
n_wk1 db 'world_',0
n_installkey db '/install.key',10,0
n_trustkeys db '/trust_keys.txt',10,0
n_denylist db '/deny.txt',10,0
t_auth_key db 'key=',0
t_auth_keys db 'keys=',0
t_auth_deny db 'deny=',0
t_auth_pass db 'pass=',0
n_backups db '/solo_backups',0
n_bridge db '/bridge_',0
n_stop db 'stop.flag',0
n_status db 'status.json',0
n_txframe db 'tx.frame',0
n_txtmp db 'tx.tmp',0
n_pid db 'helper.pid',0
n_rx1 db 'rx_',0
n_rx2 db '.json',0
s_steamlib db '/libsteam_api.so',0
s_env_steamapi db 'MISTRIMULTI_STEAM_API',0
s_deck1 db '/.local/share/Steam/steamapps/common/Fields of Mistria/libsteam_api.so',0
s_deck2 db '/.steam/steam/steamapps/common/Fields of Mistria/libsteam_api.so',0
s_pfx db '/pfx/drive_c/'
s_pfx_len equ $ - s_pfx
s_cdrive db 'C:/',0
j_enabled db '{"enabled":',0
j_true db 'true',0
j_false db 'false',0
j_mode db ',"mode":"',0
j_id db '","id":',0
j_uid db ',"uid":"',0
j_epoch db '","epoch":"',0
j_bridge db '","bridge":"',0
j_end db '"}',0
json_identity1 db '{"uid":"',0
json_identity2 db '"}',0
needle_local db '"uid":"local:'
needle_local_len equ $ - needle_local
t_stop db 'stop'
t_stop_len equ $ - t_stop
h_host db 'host',0
h_join db 'join',0
h_zero db '0',0
h_idle db 'idle',0
r_exe db 'Multiplayer not started: the game command does not name FieldsOfMistria. The game was started normally.',10,0
r_flag db 'Multiplayer not started: --mistrimulti-direct was given. The game was started normally.',10,0
r_paths db 'Multiplayer not started: could not find the folder where the game keeps its files (set MISTRIMULTI_DATA_DIR). The game was started normally.',10,0
r_config db 'Multiplayer not started: launcher.cfg is missing or invalid. Run mistrimulti-launcher --configure. The game was started normally.',10,0
r_control db 'Multiplayer not started: control.json could not be written. The game was started normally.',10,0
r_auth db 'Multiplayer not started: auth.cfg could not be written, so the room password cannot be applied. The game was started normally.',10,0
r_helper db 'Multiplayer not started: the network helper could not be started (is mistrimulti-helper-linux next to the launcher, and is the port free? see helper.log). The game was started normally.',10,0
r_nogame db 'MistriaMulti: could not start the game command.',10,0
p_mode db 'Host a game (H) or join a friend (J)? ',0
p_ip db 'Host IPv4 address (for example 192.168.1.20): ',0
p_port db 'Port (Enter for 7777): ',0
p_player db 'Your player number, 1 to 7, or just press Enter to pick one for you: ',0
p_room db 'Room code (just press Enter unless your host gave you one): ',0
t_hostinfo db 10,'Tell your friends your Tailscale IP address (it starts with 100.). That is all they need to join you.',10,0
t_player1 db 'Your player number is ',0
t_player2 db ' (every friend needs a different one; run setup again to change it).',10,0
t_bad db 'That value is not valid, try again.',10,0
t_giveup db 'Setup was not saved.',10,0
t_nodir db 'Could not find the folder where the game keeps its files. Start the game once, or set MISTRIMULTI_DATA_DIR to that folder.',10,0
t_saved db 10,'Saved.',10,'One time only: in Steam, right-click Fields of Mistria > Properties > Launch Options, paste the line below, and close the window.',10,10,0
t_cmd1 db '"',0
t_cmd2 db '" --steam %command%',10,10,0
t_nl db 10,0
t_optional db 'Optional setup: you can skip it. Start the game from Steam and choose Multiplayer, then Host a game or Join a game, in the game itself.',10,'This pre-sets a role (saved in launcher.cfg) that starts by itself.',10,10,0
align 8
name_table dq n_stop, n_status, n_txframe, n_txtmp, n_pid

section .bss
sig_flag resd 1
sigact_buf resb 32
reason resq 1
game_exit resd 1
game_pid resq 1
game_idx resq 1
h_helper resq 1
uid_a resb 64
epoch_a resb 40
bridge_dir resb 1100
bridge_json resb 1100
minname resb 32
bk_dest resb 1100
bk_dst resb 1100
stampbuf resb 24
num1 resb 16
num2 resb 16
num3 resb 16
helper_argv resq 10
probe_argv resq 4
have_old resd 1
old_mode resd 1
old_player resd 1
ans resb 64
; discovery and world server
disc_sock resq 1
tcp_sock resq 1
disc_pfds resb 16
disc_from resb 32
disc_fromlen resd 1
disc_buf resb 128
disc_resp resb 64
uts resb 400
ws_name resb 80
ws_path resb 1100
ws_size resd 1
ws_key resq 1
ws_from resb 32
ws_fromlen resd 1
ws_tv resb 16
ws_best_set resd 1

section .text
FN a_cmp                        ; rcx, rdx ASCII strings -> eax negative / 0 / positive (byte order)
.l: movzx eax, byte [rcx]
    movzx r8d, byte [rdx]
    cmp eax, r8d
    jne .diff
    test eax, eax
    jz .d
    inc rcx
    inc rdx
    jmp .l
.diff:
    sub eax, r8d
.d:
END_FN

; ---------------- identity ----------------
FN get_uid
    ; Steam identity probe (a separate process, so a Steam problem can never stop the launcher)
    lea rcx, [p1]
    lea rdx, [exe_dir]
    lea r8, [n_probe]
    call path2
    lea rcx, [p1]
    call path_kind
    cmp eax, 1
    jne .local
    call find_steam_lib                  ; p2 = libsteam_api.so, eax 1 if found
    test eax, eax
    jz .local
    lea rcx, [p3]
    lea rdx, [mod_dir]
    lea r8, [n_steamtmp]
    call path2
    lea rcx, [p3]
    mov edx, O_WRITE_NEW
    mov r8d, 0600o
    call sys_open
    test rax, rax
    js .local
    mov r12, rax
    lea rax, [p1]
    mov [probe_argv], rax
    lea rax, [p2]
    mov [probe_argv+8], rax
    mov qword [probe_argv+16], 0
    call open_devnull
    mov [rsp+32], rax
    mov qword [rsp+40], 0
    lea rcx, [p1]
    lea rdx, [probe_argv]
    mov r8, -1
    mov r9, r12
    call spawn
    mov r13, rax
    mov rcx, r12
    call sys_close
    test r13, r13
    js .read
    mov rcx, r13
    mov edx, 5000
    call proc_wait
    cmp rax, -1
    jne .read
    mov rcx, r13
    call proc_kill
.read:
    lea rcx, [p3]
    lea rdx, [file_buf]
    mov r8d, 200
    call read_file
    mov r13, rax
    lea rcx, [p3]
    call sys_unlink
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
    lea rdx, [mod_dir]
    lea r8, [n_identity]
    call path2
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
    lea rcx, [out_buf]
    mov edx, 256
    call pb_start
    lea rcx, [json_identity1]
    call pb_str
    lea rcx, [uid_a]
    call pb_str
    lea rcx, [json_identity2]
    call pb_str
    call pb_end
    mov r8d, eax
    lea rcx, [p1]
    lea rdx, [out_buf]
    call write_file
.done:
END_FN

; Looks for the game's libsteam_api.so (native Linux game only; under Proton there is none and the local identity is used).
; Leaves its path in p2. eax 1 if found.
FN find_steam_lib
    lea rcx, [s_env_steamapi]
    call env_get
    test rax, rax
    jz .arg
    cmp byte [rax], 0
    je .arg
    lea rcx, [p2]
    mov rdx, rax
    lea r8, [s_empty]
    call path2
    lea rcx, [p2]
    call path_kind
    cmp eax, 1
    je .yes
.arg:
    cmp qword [game_idx], 0
    je .cwd
    mov rcx, [game_idx]
    call arg_n
    mov r12, rax
    lea rcx, [p3]
    mov rdx, r12
    lea r8, [s_empty]
    call path2
    lea rcx, [p3]
    call cut_last_component
    lea rcx, [p2]
    lea rdx, [p3]
    lea r8, [s_steamlib]
    call path2
    lea rcx, [p2]
    call path_kind
    cmp eax, 1
    je .yes
.cwd:
    lea rcx, [p3]                       ; Steam starts the game command in the game's folder
    mov edx, 1000
    call sys_getcwd
    test rax, rax
    jle .home
    lea rcx, [p2]
    lea rdx, [p3]
    lea r8, [s_steamlib]
    call path2
    lea rcx, [p2]
    call path_kind
    cmp eax, 1
    je .yes
.home:
    cmp qword [home_dir], 0
    je .no
    lea rcx, [p2]
    mov rdx, [home_dir]
    lea r8, [s_deck1]
    call path2
    lea rcx, [p2]
    call path_kind
    cmp eax, 1
    je .yes
    lea rcx, [p2]
    mov rdx, [home_dir]
    lea r8, [s_deck2]
    call path2
    lea rcx, [p2]
    call path_kind
    cmp eax, 1
    je .yes
.no:
    xor eax, eax
    jmp .d
.yes:
    mov eax, 1
.d:
END_FN

; ---------------- control.json and the bridge ----------------
; ecx = 1 enabled / 0 disabled. Writes control.json (compact JSON, validated pieces only). eax 1 ok.
; A data folder inside a Proton prefix is written the way the Windows game sees it: .../pfx/drive_c/X becomes C:/X.
FN write_control
    mov r12d, ecx
    lea rcx, [bridge_dir]
    call str_len
    mov rdx, rax
    lea rcx, [bridge_dir]
    lea r8, [s_pfx]
    mov r9d, s_pfx_len
    call find_bytes
    mov r13, rax
    lea rcx, [bridge_json]
    mov edx, 1100
    call pb_start
    test r13, r13
    jz .native
    lea rcx, [s_cdrive]
    call pb_str
    lea rcx, [r13+s_pfx_len]
    call pb_str
    jmp .built
.native:
    lea rcx, [bridge_dir]
    call pb_str
.built:
    call pb_end
    cmp eax, -1
    je .bad
    lea rcx, [out_buf]
    mov edx, 2048
    call pb_start
    lea rcx, [j_enabled]
    call pb_str
    lea rcx, [j_false]
    test r12d, r12d
    jz .en
    lea rcx, [j_true]
.en:call pb_str
    lea rcx, [j_mode]
    call pb_str
    lea rcx, [h_host]
    cmp dword [cfg_mode], 1
    je .m
    lea rcx, [h_join]
    cmp dword [cfg_mode], 2
    je .m
    lea rcx, [h_idle]
.m: call pb_str
    lea rcx, [j_id]
    call pb_str
    mov ecx, [cfg_player]
    call pb_int
    lea rcx, [j_uid]
    call pb_str
    lea rcx, [uid_a]
    call pb_str
    lea rcx, [j_epoch]
    call pb_str
    lea rcx, [epoch_a]
    call pb_str
    lea rcx, [j_bridge]
    call pb_str
    lea rcx, [bridge_json]
    call pb_str
    lea rcx, [j_end]
    call pb_str
    call pb_end
    cmp eax, -1
    je .bad
    cmp eax, 1900
    jae .bad
    mov r13d, eax
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_control]
    call path2
    lea rcx, [p1]
    lea rdx, [out_buf]
    mov r8d, r13d
    call write_file
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN unlink_in                    ; rcx folder, rdx file name -> removes folder/name (a missing file is fine)
    mov r12, rcx
    mov r13, rdx
    lea rcx, [p1]
    mov edx, 1100
    call pb_start
    mov rcx, r12
    call pb_str
    lea rcx, [s_slash]
    call pb_str
    mov rcx, r13
    call pb_str
    call pb_end
    lea rcx, [p1]
    call sys_unlink
END_FN

FN prepare_bridge
    lea rcx, [bridge_dir]
    mov edx, 1100
    call pb_start
    lea rcx, [mod_dir]
    call pb_str
    lea rcx, [n_bridge]
    call pb_str
    mov ecx, [cfg_player]
    call pb_int
    call pb_end
    lea rcx, [p2]
    lea rdx, [bridge_dir]
    lea r8, [s_x]
    call path2
    lea rcx, [p2]
    call ensure_dirs                    ; creates the bridge folder itself (everything in front of the last name)
    ; remove only this helper's own transient files
    xor r12d, r12d
.names:
    cmp r12d, 5
    jae .rx
    lea rcx, [bridge_dir]
    lea rax, [name_table]
    mov rdx, [rax+r12*8]
    call unlink_in
    inc r12d
    jmp .names
.rx:
    xor r12d, r12d
.rxl:
    cmp r12d, 8
    jae .wk0
    lea rcx, [p3]
    mov edx, 64
    call pb_start
    lea rcx, [n_rx1]
    call pb_str
    mov ecx, r12d
    call pb_int
    lea rcx, [n_rx2]
    call pb_str
    call pb_end
    lea rcx, [bridge_dir]
    lea rdx, [p3]
    call unlink_in
    inc r12d
    jmp .rxl
.wk0:                                   ; session keys of an earlier run (world_<slot>.key) must not outlive it
    xor r12d, r12d
.wk:
    cmp r12d, 8
    jae .d
    lea rcx, [p3]
    mov edx, 64
    call pb_start
    lea rcx, [n_wk1]
    call pb_str
    mov ecx, r12d
    call pb_int
    lea rcx, [s_wkey2]
    call pb_str
    call pb_end
    lea rcx, [bridge_dir]
    lea rdx, [p3]
    call unlink_in
    inc r12d
    jmp .wk
.d:
END_FN

FN is_stamp                     ; rcx: eax 1 if "YYYYMMDD-HHMMSS"
    xor edx, edx
.l: movzx eax, byte [rcx+rdx]
    cmp edx, 15
    je .end
    test al, al
    jz .no
    cmp edx, 8
    jne .dig
    cmp al, '-'
    jne .no
    jmp .n
.dig:
    sub eax, '0'
    cmp eax, 9
    ja .no
.n: inc edx
    jmp .l
.end:
    cmp byte [rcx+15], 0
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
    mov byte [minname], 0
    lea rcx, [p2]
    call dir_open
    test rax, rax
    js .d
.scan:
    call dir_next
    test rax, rax
    jz .scanned
    mov r13, rax
    mov rcx, r13
    call is_stamp
    test eax, eax
    jz .scan
    lea rcx, [p3]
    lea rdx, [p2]
    lea r8, [s_slash]
    mov r9, r13
    call path3
    lea rcx, [p3]
    call path_kind
    cmp eax, 2
    jne .scan
    inc r12d
    cmp byte [minname], 0
    je .take
    mov rcx, r13
    lea rdx, [minname]
    call a_cmp
    test eax, eax
    jns .scan
.take:
    lea rcx, [minname]
    mov rdx, r13
    call str_copy
    jmp .scan
.scanned:
    call dir_close
    cmp r12d, 10
    jbe .d
    lea rcx, [p3]
    lea rdx, [p2]
    lea r8, [s_slash]
    lea r9, [minname]
    call path3
    lea rcx, [p3]
    call dir_open
    test rax, rax
    js .rmdir
.del:
    call dir_next
    test rax, rax
    jz .deldone
    mov r13, rax
    lea rcx, [p1]
    lea rdx, [p3]
    lea r8, [s_slash]
    mov r9, r13
    call path3
    lea rcx, [p1]
    call path_kind
    cmp eax, 2
    je .del
    lea rcx, [p1]
    call sys_unlink
    jmp .del
.deldone:
    call dir_close
.rmdir:
    lea rcx, [p3]
    call sys_rmdir
    test rax, rax
    jz .again
.d:
END_FN

; Copies the solo saves to mod_data/mistrimulti/solo_backups/<timestamp> (UTC). Copy only; never changes the saves.
FN backup_saves
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_saves]
    call path2
    lea rcx, [p2]
    lea rdx, [mod_dir]
    lea r8, [n_backups]
    call path2
    lea rcx, [p3]
    lea rdx, [p2]
    lea r8, [s_x]
    call path2
    lea rcx, [p3]
    call ensure_dirs
    lea rcx, [stampbuf]
    call time_stamp
    lea rcx, [bk_dest]
    lea rdx, [p2]
    lea r8, [s_slash]
    lea r9, [stampbuf]
    call path3
    cmp eax, -1
    je .d
    lea rcx, [bk_dest]
    mov edx, 0755o
    call sys_mkdir
    lea rcx, [p1]
    call dir_open
    test rax, rax
    js .prune
.each:
    call dir_next
    test rax, rax
    jz .done
    mov r13, rax
    lea rcx, [p3]
    lea rdx, [p1]
    lea r8, [s_slash]
    mov r9, r13
    call path3
    lea rcx, [bk_dst]
    lea rdx, [bk_dest]
    lea r8, [s_slash]
    mov r9, r13
    call path3
    lea rcx, [p3]
    call path_kind
    cmp eax, 1
    jne .each
    lea rcx, [p3]
    lea rdx, [bk_dst]
    call copy_file
    jmp .each
.done:
    call dir_close
.prune:
    call prune_backups
.d:
END_FN

; Writes <bridge>/auth.cfg for the helper: where it keeps the install key and the key store, the deny list, and the room
; password (docs/SECURITY.md). Private to this user. eax 1 ok. Rewritten at every start, so a removed password disappears.
FN write_auth
    lea rcx, [out_buf]
    mov edx, 4096
    call pb_start
    lea rcx, [t_auth_key]
    call pb_str
    lea rcx, [mod_dir]
    call pb_str
    lea rcx, [n_installkey]
    call pb_str
    lea rcx, [t_auth_keys]
    call pb_str
    lea rcx, [mod_dir]
    call pb_str
    lea rcx, [n_trustkeys]
    call pb_str
    lea rcx, [t_auth_deny]
    call pb_str
    lea rcx, [mod_dir]
    call pb_str
    lea rcx, [n_denylist]
    call pb_str
    cmp byte [a_pass], 0
    je .nopass
    lea rcx, [t_auth_pass]
    call pb_str
    lea rcx, [a_pass]
    call pb_str
    lea rcx, [t_nl]
    call pb_str
.nopass:
    call pb_end
    cmp eax, -1
    je .bad
    mov r13d, eax
    lea rcx, [p1]
    lea rdx, [bridge_dir]
    lea r8, [n_authcfg]
    call path2
    lea rcx, [p1]
    lea rdx, [out_buf]
    mov r8d, r13d
    mov dword [wf_mode], 0600o
    call write_file
    mov dword [wf_mode], 0644o
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; ---------------- helper ----------------
; A joining player refreshes the host's world just before the game starts (quietly: failures are fine).
FN join_refresh_world
    cmp dword [cfg_mode], 2
    jne .d
    lea rcx, [a_host]
    call ip_parse
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_mp_saves]
    call path2
    mov dword [wf_connect_ms], 1500
    lea rcx, [bridge_dir]
    mov edx, [cfg_player]
    call world_use_session
    call ticks_ms                       ; the world is released only to a joined player: wait for the helper's WELCOME
    add rax, 5000
    mov r13, rax
.wait:
    mov rcx, [wf_keypath]
    call wa_load_key
    test eax, eax
    jnz .go
    call ticks_ms
    cmp rax, r13
    jae .d
    mov ecx, 150
    call sleep_ms
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

; Starts the network helper with the arguments the Windows launcher passes. eax 1 if it is still running after a short wait.
FN start_helper
    lea rcx, [p1]
    lea rdx, [exe_dir]
    lea r8, [n_helper]
    call path2
    lea rcx, [p1]
    mov edx, 1                          ; X_OK
    call sys_access
    test rax, rax
    jnz .bad
    ; numbers as text
    lea rcx, [num1]
    mov edx, 16
    call pb_start
    mov ecx, [cfg_local]
    call pb_int
    call pb_end
    lea rcx, [num2]
    mov edx, 16
    call pb_start
    mov ecx, [cfg_player]
    call pb_int
    call pb_end
    lea rcx, [num3]
    mov edx, 16
    call pb_start
    mov ecx, [cfg_port]
    call pb_int
    call pb_end
    lea rax, [p1]
    mov [helper_argv], rax
    lea rax, [h_host]
    cmp dword [cfg_mode], 1
    je .m
    lea rax, [h_join]
.m: mov [helper_argv+8], rax
    lea rax, [num1]
    mov [helper_argv+16], rax
    lea rax, [num2]
    mov [helper_argv+24], rax
    lea rax, [a_room]
    mov [helper_argv+32], rax
    lea rax, [bridge_dir]
    mov [helper_argv+40], rax
    cmp dword [cfg_mode], 1
    jne .joinargs
    mov qword [helper_argv+48], 0
    jmp .go
.joinargs:
    lea rax, [a_host]
    mov [helper_argv+48], rax
    lea rax, [num3]
    mov [helper_argv+56], rax
    mov qword [helper_argv+64], 0
.go:
    lea rcx, [p2]
    lea rdx, [mod_dir]
    lea r8, [n_helperlog]
    call path2
    lea rcx, [p2]
    mov edx, O_WRITE_NEW
    mov r8d, 0644o
    call sys_open
    mov r12, rax                        ; helper.log; -1 (output stays as it is) if it cannot be created
    test r12, r12
    jns .haslog
    mov r12, -1
.haslog:
    call open_devnull
    mov r13, rax
    mov [rsp+32], r12                   ; stderr
    mov qword [rsp+40], 1               ; die with the launcher
    lea rcx, [p1]
    lea rdx, [helper_argv]
    mov r8, r13
    mov r9, r12
    call spawn
    mov r14, rax
    cmp r12, -1
    je .nolog
    mov rcx, r12
    call sys_close
.nolog:
    test r14, r14
    js .bad
    mov rcx, r14
    mov edx, 400
    call proc_wait
    cmp rax, -1
    jne .bad
    mov [h_helper], r14
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN stop_helper
    cmp qword [h_helper], 0
    je .d
    lea rcx, [p1]
    lea rdx, [bridge_dir]
    lea r8, [s_stop_flag]
    call path2
    lea rcx, [p1]
    lea rdx, [t_stop]
    mov r8d, t_stop_len
    call write_plain
    mov rcx, [h_helper]
    mov edx, 2500
    call proc_wait
    cmp rax, -1
    jne .closed
    mov rcx, [h_helper]
    call proc_kill
.closed:
    mov qword [h_helper], 0
.d:
END_FN

; ---------------- host discovery and world server ----------------
; While hosting, answer "who is hosting?" queries on UDP 7776 and serve the newest multiplayer save on TCP 7775.
; Query:  exactly 64 bytes starting "MSDQ", version 1.  Reply: 64 bytes "MSDR", version 1, flags, game port, computer name.
; The reply is never larger than the query, so this cannot be used to amplify traffic.
FN disc_start
    mov qword [disc_sock], 0
    mov qword [tcp_sock], 0
    cmp dword [cfg_mode], 1
    jne .d
    mov ecx, 2
    mov edx, 2 | 0x800 | 0x80000        ; SOCK_DGRAM
    xor r8d, r8d
    call sys_socket
    test rax, rax
    js .tcp
    mov rbx, rax
    lea rcx, [disc_from]
    mov edx, DISC_PORT_NET
    xor r8d, r8d
    call fill_sockaddr
    mov rcx, rbx
    lea rdx, [disc_from]
    mov r8d, 16
    call sys_bind
    test rax, rax
    jnz .udpfail
    mov [disc_sock], rbx
    jmp .tcp
.udpfail:
    mov rcx, rbx
    call sys_close
.tcp:
    ; the host's world is offered on TCP 7775
    mov ecx, 2
    mov edx, 1 | 0x800 | 0x80000        ; SOCK_STREAM
    xor r8d, r8d
    call sys_socket
    test rax, rax
    js .reply
    mov r12, rax
    mov dword [wf_one], 1
    mov rcx, r12
    mov edx, 1                          ; SOL_SOCKET
    mov r8d, 2                          ; SO_REUSEADDR
    lea r9, [wf_one]
    mov qword [rsp+32], 4
    call sys_setsockopt
    lea rcx, [disc_from]
    mov edx, WF_PORT_NET
    xor r8d, r8d
    call fill_sockaddr
    mov rcx, r12
    lea rdx, [disc_from]
    mov r8d, 16
    call sys_bind
    test rax, rax
    jnz .tcpfail
    mov rcx, r12
    mov edx, 4
    call sys_listen
    test rax, rax
    jnz .tcpfail
    mov [tcp_sock], r12
    jmp .reply
.tcpfail:
    mov rcx, r12
    call sys_close
.reply:
    ; the fixed part of the reply
    lea rdi, [disc_resp]
    xor eax, eax
    mov ecx, 64
    rep stosb
    mov dword [disc_resp], 'MSDR'
    mov byte [disc_resp+4], 1
    lea rcx, [a_room]
    lea rdx, [room_default]
    call a_equal
    xor eax, 1                          ; flag bit 0: this host uses a custom room code
    cmp byte [a_pass], 0
    je .nopassflag
    or al, 2                            ; flag bit 1: this host needs a room password
.nopassflag:
    mov [disc_resp+5], al
    mov eax, [cfg_port]
    mov [disc_resp+6], ax
    lea rcx, [uts]
    call sys_uname
    test rax, rax
    jnz .d
    lea rsi, [uts+65]                   ; nodename
    lea rdi, [disc_resp+8]
    xor ecx, ecx
.nm:movzx eax, byte [rsi+rcx]
    test al, al
    jz .d
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 31
    jb .nm
.d:
END_FN

; Newest valid multiplayer save -> eax 1, with ws_name (ASCII), ws_path, ws_size
FN world_find_newest
    mov dword [ws_best_set], 0
    mov qword [ws_key], 0
    mov dword [ws_size], 0
    mov byte [ws_name], 0
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_mp_saves]
    call path2
    lea rcx, [p1]
    call dir_open
    test rax, rax
    js .none
.each:
    call dir_next
    test rax, rax
    jz .scanned
    mov r13, rax
    mov rcx, r13
    call wf_valid_name
    test eax, eax
    jz .each
    cmp dword [wh_id], 0
    je .anyworld
    mov rcx, r13
    call wf_name_id
    cmp eax, [wh_id]                    ; the mod named the world being played: only that world's saves count
    jne .each
.anyworld:
    lea rcx, [p3]
    lea rdx, [p1]
    lea r8, [s_slash]
    mov r9, r13
    call path3
    cmp eax, -1
    je .each
    lea rcx, [p3]
    call path_kind
    cmp eax, 1
    jne .each
    mov rax, [st_buf+48]                ; size
    test rax, rax
    jz .each
    cmp rax, WF_MAX_FILE
    ja .each
    mov r14, rax
    mov rax, [st_buf+88]                ; modification time, seconds
    imul rax, rax, 1000000000
    add rax, [st_buf+96]
    cmp dword [ws_best_set], 0
    je .better
    cmp rax, [ws_key]
    jbe .each
.better:
    mov [ws_key], rax
    mov dword [ws_best_set], 1
    mov [ws_size], r14d
    lea rcx, [ws_name]
    mov rdx, r13
    call str_copy
    jmp .each
.scanned:
    call dir_close
    cmp dword [ws_best_set], 0
    je .none
    lea rcx, [ws_path]
    lea rdx, [p1]
    lea r8, [s_slash]
    lea r9, [ws_name]
    call path3
    cmp eax, -1
    je .none
    mov eax, 1
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

; Serves one waiting connection: sends the newest multiplayer save with its SHA-256. Never reads a path from the client.
FN world_serve
    mov dword [ws_fromlen], 16
    mov rcx, [tcp_sock]
    lea rdx, [ws_from]
    lea r8, [ws_fromlen]
    mov r9d, O_CLOEXEC
    call sys_accept4
    test rax, rax
    js .d
    mov rbx, rax
    mov [wf_sock], rbx
    mov qword [ws_tv], 15
    mov qword [ws_tv+8], 0
    mov rcx, rbx
    mov edx, 1                          ; SOL_SOCKET
    mov r8d, 20                         ; SO_RCVTIMEO
    lea r9, [ws_tv]
    mov qword [rsp+32], 16
    call sys_setsockopt
    mov rcx, rbx
    mov edx, 1
    mov r8d, 21                         ; SO_SNDTIMEO
    lea r9, [ws_tv]
    mov qword [rsp+32], 16
    call sys_setsockopt
    call wa_serve_auth                  ; nothing is read from disk or sent before the client proved its join session
    test eax, eax
    jz .close
    lea rdi, [wf_hdr]
    xor eax, eax
    mov ecx, 144
    rep stosb
    mov dword [wf_hdr], 'MSWR'
    mov byte [wf_hdr+4], 2
    xor r12d, r12d                      ; file buffer
    call wh_state                       ; the world the mod says the host plays now; its newest save (any newest save without a note)
    test eax, eax
    jz .nosave
    mov r13d, [ws_size]
    xor ecx, ecx
    mov edx, r13d
    mov r8d, 3
    mov r9d, 0x22
    mov qword [rsp+32], -1
    mov qword [rsp+40], 0
    call sys_mmap
    cmp rax, -4096
    ja .cannot
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
    mov byte [wf_hdr+5], 4              ; the host plays a world it has not saved: nothing downloadable is that world
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
    cmp r12, 0
    je .close
    cmp r12, -4096
    jae .close
    mov rcx, r12
    mov edx, r13d
    call sys_munmap
.close:
    mov rcx, rbx
    mov edx, 1                          ; SHUT_WR
    call sys_shutdown
    mov rcx, rbx
    call sys_close
    mov qword [wf_sock], 0
.d:
END_FN

; Waits for the game process (rcx pid) while answering discovery queries and world downloads. Sets game_exit.
FN disc_serve
    mov r12, rcx
.loop:
    mov rax, [disc_sock]
    mov [disc_pfds], eax
    mov word [disc_pfds+4], POLLIN
    mov word [disc_pfds+6], 0
    mov rax, [tcp_sock]
    mov [disc_pfds+8], eax
    mov word [disc_pfds+12], POLLIN
    mov word [disc_pfds+14], 0
    cmp qword [disc_sock], 0
    jne .p1
    mov dword [disc_pfds], -1            ; poll ignores a negative descriptor
.p1:cmp qword [tcp_sock], 0
    jne .poll
    mov dword [disc_pfds+8], -1
.poll:
    lea rcx, [disc_pfds]
    mov edx, 2
    mov r8d, 250
    call sys_poll
    test rax, rax
    jle .check
    test word [disc_pfds+14], POLLIN
    jz .udp
    call world_serve
.udp:
    test word [disc_pfds+6], POLLIN
    jz .check
    mov dword [disc_fromlen], 16
    mov rcx, [disc_sock]
    lea rdx, [disc_buf]
    mov r8d, 128
    xor r9d, r9d
    lea rax, [disc_from]
    mov [rsp+32], rax
    lea rax, [disc_fromlen]
    mov [rsp+40], rax
    call sys_recvfrom
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
    call sys_sendto
.check:
    call sv_poll                        ; commands from the in-game menu (linux/menu.inc)
    mov edx, [sig_flag]
    test edx, edx
    jz .nosig
    mov dword [sig_flag], 0
    mov rcx, r12
    call sys_kill                       ; the launcher was asked to stop: pass the signal to the game
.nosig:
    mov rcx, r12
    call proc_poll
    cmp rax, -1
    je .loop
    mov [game_exit], eax
    call disc_stop
.d:
END_FN

; Closes the discovery answer (UDP 7776) and the world server (TCP 7775): nothing listens when no host session runs.
FN disc_stop
    mov rcx, [disc_sock]
    test rcx, rcx
    jz .t
    call sys_close
    mov qword [disc_sock], 0
.t: mov rcx, [tcp_sock]
    test rcx, rcx
    jz .d
    call sys_close
    mov qword [tcp_sock], 0
.d:
END_FN

; Steam stops a game by sending SIGTERM (and Ctrl+C in a terminal sends SIGINT): the launcher passes the signal on to the game and
; then does its normal clean-up (helper stopped, control.json disabled) instead of dying in the middle.
sig_handler:
    mov [sig_flag], edi
    ret
sig_restorer:
    mov eax, 15                         ; rt_sigreturn
    syscall

FN install_signals
    lea rax, [sig_handler]
    mov [sigact_buf], rax
    mov qword [sigact_buf+8], 0x04000000 ; SA_RESTORER
    lea rax, [sig_restorer]
    mov [sigact_buf+16], rax
    mov qword [sigact_buf+24], 0
    mov ecx, 15
    lea rdx, [sigact_buf]
    xor r8d, r8d
    mov r9d, 8
    call sys_rt_sigaction
    mov ecx, 2
    lea rdx, [sigact_buf]
    xor r8d, r8d
    mov r9d, 8
    call sys_rt_sigaction
    mov ecx, 1
    lea rdx, [sigact_buf]
    xor r8d, r8d
    mov r9d, 8
    call sys_rt_sigaction
END_FN

; Runs the game command (everything after "--steam") as a child and waits for it, serving discovery and the world meanwhile.
; Sets game_exit.
FN launch_game
    mov dword [game_exit], 1
    call install_signals
    mov rax, [argv_v]
    lea rdx, [rax+16]
    mov rcx, [rdx]
    mov r8, -1                          ; stdin, stdout and stderr stay as Steam set them
    mov r9, -1
    mov qword [rsp+32], -1
    mov qword [rsp+40], 2               ; search PATH
    call spawn
    test rax, rax
    js .d
    mov [game_pid], rax
    mov rcx, rax
    call disc_serve
.d:
END_FN

; Replaces this process with the game (the plain, no-multiplayer start). Returns only if that fails.
FN exec_game
    xor ecx, ecx
    call sigpipe_set
    mov rax, [argv_v]
    mov rcx, [rax+16]
    lea rdx, [rax+16]
    call exec_search
    lea rcx, [r_nogame]
    call say_err
END_FN

; ---------------- configure ----------------
FN setup_failed_exit
    lea rcx, [t_giveup]
    call say
    mov ecx, 1
    call sys_exit
END_FN

configure_main:
    call exe_init
    call find_datadir
    test eax, eax
    jz cfg_nodir
    call mod_dir_init
    call load_config
    mov [have_old], eax
    test eax, eax
    jnz .keeppass
    mov byte [a_pass], 0               ; no usable old setup: nothing to keep (an invalid password is never written back)
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
    call cfg_save
    test eax, eax
    jz cfg_giveup
    lea rcx, [t_saved]
    call say
    lea rcx, [t_cmd1]
    call say
    lea rcx, [exe_path]
    call say
    lea rcx, [t_cmd2]
    call say
    cmp dword [cfg_mode], 1
    jne .joininfo
    lea rcx, [t_hostinfo]
    call say
    jmp .close
.joininfo:
    lea rcx, [t_player1]
    call say
    lea rcx, [ans]
    mov edx, 16
    call pb_start
    mov ecx, [cfg_player]
    call pb_int
    call pb_end
    lea rcx, [ans]
    call say
    lea rcx, [t_player2]
    call say
.close:
    xor ecx, ecx
    call sys_exit
cfg_nodir:
    lea rcx, [t_nodir]
    call say
cfg_giveup:
    lea rcx, [t_giveup]
    call say
    mov ecx, 1
    call sys_exit

; ---------------- --steam ----------------
; Writes why multiplayer was not started to mod_data/mistrimulti/launcher.log (only when the folder is known)
FN log_reason
    cmp qword [reason], 0
    je .d
    mov rcx, [reason]
    call say_err
    cmp byte [mod_dir], 0
    je .d
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_log]
    call path2
    mov rcx, [reason]
    call str_len
    mov r8, rax
    lea rcx, [p1]
    mov rdx, [reason]
    call write_plain
.d:
END_FN

; Finds the argument that names the game (its file name starts with "FieldsOfMistria": FieldsOfMistria.exe under Proton,
; or the native program). game_idx = its index, 0 if none. Also looks for --mistrimulti-direct (eax 1).
FN scan_game_args
    mov qword [game_idx], 0
    xor r13d, r13d
    mov r12d, 2
.l: cmp r12, [argc_v]
    jae .d
    mov ecx, r12d
    call arg_n
    mov r14, rax
    mov rcx, rax
    lea rdx, [s_direct]
    call a_equal
    test eax, eax
    jz .name
    mov r13d, 1
.name:
    cmp qword [game_idx], 0
    jne .n
    mov rcx, r14
    call base_name
    mov rcx, rax
    lea rdx, [s_gamename]
    call a_starts_ci
    test eax, eax
    jz .n
    mov [game_idx], r12
.n: inc r12d
    jmp .l
.d:
    mov eax, r13d
END_FN

program_main:
    mov ecx, 1
    call arg_n
    test rax, rax
    jz configure_main                 ; no arguments: run the setup
    mov r12, rax
    mov rcx, r12
    lea rdx, [s_configure]
    call a_equal
    test eax, eax
    jnz configure_main
    mov rcx, r12
    lea rdx, [s_steam]
    call a_equal
    test eax, eax
    jz .exit1
    cmp qword [argc_v], 3
    jb .exit1
    mov ecx, 1                        ; a closed log pipe must not kill the launcher before the game starts
    call sigpipe_set
    call exe_init                     ; best effort from here on: every failure still starts the game
    call find_datadir
    mov r12d, eax
    test eax, eax
    jz .pathsdone
    call mod_dir_init
    mov r12d, eax
.pathsdone:
    call scan_game_args
    mov r13d, eax                     ; --mistrimulti-direct seen
    lea rbx, [r_exe]
    cmp qword [game_idx], 0
    je .direct
    lea rbx, [r_flag]
    test r13d, r13d
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
    call launch_game
    call sess_stop
    mov ecx, ST_STOPPED
    xor edx, edx
    call sv_set
    mov ecx, [game_exit]
    call sys_exit
.direct:
    mov [reason], rbx
    call log_reason
    call exec_game
    mov ecx, 127
    call sys_exit
.exit1:
    mov ecx, 1
    call sys_exit

section .data
s_stop_flag db '/stop.flag',0
section .note.GNU-stack noalloc noexec nowrite progbits
