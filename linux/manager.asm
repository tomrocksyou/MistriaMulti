; MistriaMulti manager for Linux and the Steam Deck: the console twin of the Windows manager window (updater/mp.inc).
;   mistrimulti-manager host [--password TEXT]   write the host setup (optionally with a room password) and show the addresses to give to friends
;   mistrimulti-manager join [IP]            find hosts (broadcast + Tailscale peers) and choose one, or join an IP directly
;                            [--player N] [--room CODE] [--port N] [--password TEXT]
;   mistrimulti-manager scan                 only list the hosts that can be found
;   mistrimulti-manager steam-setup          print the Steam launch option for the launcher
;   mistrimulti-manager save-solo            copy the solo saves to ~/Documents/MistriMulti Backups
; Test hooks (like the Windows manager): --scan <file>, --fetch <ip> <folder> <result file>, --targets <file>, --stamp <seconds>.
; NASM x86-64 ELF, raw system calls, no C runtime. Shares linux/*.inc with the launcher.
bits 64
default rel
%include "abi.inc"

section .text
%include "sys.inc"
%include "sha256.inc"
%include "config.inc"
%include "net.inc"

section .data
a_host_cmd db 'host',0
a_join_cmd db 'join',0
a_scan_cmd db 'scan',0
a_steam_cmd db 'steam-setup',0
a_save_cmd db 'save-solo',0
a_help1 db 'help',0
a_help2 db '--help',0
a_scan_hook db '--scan',0
a_fetch_hook db '--fetch',0
a_targets_hook db '--targets',0
a_stamp_hook db '--stamp',0
t_self db 'self ',0
t_target db 'target ',0
o_player db '--player',0
o_room db '--room',0
o_port db '--port',0
cfg_host_text db 'mode=host',13,10,'port=7777',13,10,'player=0',13,10,'room=',13,10
cfg_host_len equ $ - cfg_host_text
    db 0
o_pass db '--password',0
t_badpass db 'The password must be 1 to 64 letters, digits or punctuation, without spaces or accents.',10,0
t_cfg_pass_line db 'password=',0
t_crlf_z db 13,10,0
n_launcher db '/mistrimulti-launcher',0
n_backups_dir db '/MistriMulti Backups',0
s_documents db '/Documents',0
s_userdirs db '/user-dirs.dirs',0
s_env_xdg_docs db 'XDG_DOCUMENTS_DIR',0
k_docs db 'XDG_DOCUMENTS_DIR="'
k_docs_len equ $ - k_docs
t_usage db 'MistriaMulti manager',10
    db '  mistrimulti-manager host [--password TEXT]   set this computer up as the host (with an optional room password)',10
    db '                      and show the addresses to give to friends',10
    db '  mistrimulti-manager join [IP]       find hosts on your network and on Tailscale and join one (or join IP directly)',10
    db '                      [--player N] [--room CODE] [--port N] [--password TEXT]',10
    db '  mistrimulti-manager scan            list the hosts that can be found',10
    db '  mistrimulti-manager steam-setup     print the Steam launch option for the launcher',10
    db '  mistrimulti-manager save-solo       copy your solo saves to ~/Documents/MistriMulti Backups',10,0
t_nodir db 'Could not find the folder where the game keeps its files. Start the game once, or set MISTRIMULTI_DATA_DIR to that folder.',10,0
t_nocfg db 'Could not save the setup.',10,0
t_hostmsg db 'You are set to host.',10,10,'Tell your friends one of these addresses; they pick yours in the join list or type it:',10,10,0
t_tailscale db 'Tailscale:    ',0
t_lan db 'This network: ',0
t_hostend db 10,'Then start the game from Steam and choose Multiplayer on New Game or Load Game.',10
    db 'If you have not set the Steam launch option yet, run: mistrimulti-manager steam-setup',10,0
t_scanning db 'Looking for hosts...',10,0
t_found db 'Hosts found on your network and on Tailscale:',10,0
t_none db 'No host found. Make sure your friend is hosting, then scan again (or type the host IP address).',10,0
t_needroom db '   [needs a room code]',0
t_needpass db '   [needs a password]',0
t_passask db 'This host uses a room password. Ask them for it and type it here: ',0
t_pick db 'Number of the host to join, R to scan again, or an IPv4 address (Enter to quit): ',0
t_roomask db 'Room code (just press Enter unless your host gave you one): ',0
t_roomneed db 'This host uses a room code. Ask them for it and type it here: ',0
t_badip db 'That is not a valid IPv4 address (like 100.101.102.103).',10,0
t_badplayer db 'The player number must be 1 to 7.',10,0
t_badroom db 'The room code must be 8 characters, 0-9 and a-f.',10,0
t_badport db 'The port must be 1 to 65535 (and leave room for the player number).',10,0
t_badpick db 'That is not one of the listed hosts.',10,0
t_cancel db 'Nothing selected.',10,0
t_joined db 'Saved. Now start Fields of Mistria from Steam and choose Multiplayer on New Game or Load Game.',10,10,'Joining: ',0
t_player_is db 'Your player number is ',0
t_world_dl db 'Downloading the host',39,'s world...',10,0
t_world_ok db 'The host',39,'s world was downloaded. Choose Multiplayer on New Game to enter it.',10,0
t_world_no db 'The host',39,'s world could not be downloaded yet (is the host playing, and has it saved?). Run join again later, or just start the game: it tries again when it starts.',10,0
t_steam1 db 'One time only: in Steam, right-click Fields of Mistria > Properties > Launch Options, paste this line, and close the window:',10,10,0
t_steam2 db 10,10,'Steam then starts multiplayer automatically every time you press Play.',10,0
t_steam_missing db 'Warning: mistrimulti-launcher was not found next to the manager. Keep both programs in one folder.',10,0
t_cmd1 db '"',0
t_cmd2 db '" --steam %command%',0
t_nodocs db 'Could not find your Documents folder.',10,0
t_nosaves db 'No solo saves were found to back up.',10,0
t_saved1 db 'Saved ',0
t_saved2 db ' file(s) to:',10,0
t_nl db 10,0
t_dash db '   -   ',0
t_paren db ') ',0
t_two db '  ',0
align 8

section .bss
join_ip resb 32
join_port resd 1
join_flags resd 1
opt_player resd 1
opt_room resb 16
host_pass resb 72
opt_have_room resd 1
opt_port resd 1
copied resd 1
docs_dir resb 1100
dest_dir resb 1100
stampbuf resb 24
numbuf resb 24
ans resb 64
arg_ip resq 1
interactive resd 1
result_buf resb 24

section .text
; ---------------- small helpers ----------------
FN say_int                      ; ecx value -> stdout
    mov r12d, ecx
    lea rcx, [numbuf]
    mov edx, 24
    call pb_start
    mov ecx, r12d
    call pb_int
    call pb_end
    lea rcx, [numbuf]
    call say
END_FN

FN say_ip                       ; ecx IPv4 (network order)
    lea rdx, [numbuf]
    call ip_text
    lea rcx, [numbuf]
    call say
END_FN

FN prepare_paths                ; eax 1 ok; otherwise prints why
    call exe_init
    call find_datadir
    test eax, eax
    jz .nodir
    call mod_dir_init
    test eax, eax
    jz .nodir
    mov eax, 1
    jmp .d
.nodir:
    lea rcx, [t_nodir]
    call say_err
    xor eax, eax
.d:
END_FN

; player number from an existing launcher.cfg (1-7) or a random one -> eax
FN pick_player
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_cfg]
    call path2
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    cmp rax, 8
    jl .rand
    mov [cfg_len], rax
    lea rcx, [file_buf]
    mov byte [rcx+rax], 0
    lea rcx, [k_player]
    lea rdx, [a_player]
    mov r8d, 16
    call cfg_get
    lea rcx, [a_player]
    call a2i
    cmp eax, 1
    jl .rand
    cmp eax, 7
    jg .rand
    jmp .d
.rand:
    lea rcx, [file_buf]
    call guid_hex
    movzx eax, byte [guid]
    xor edx, edx
    mov ecx, 7
    div ecx
    lea eax, [rdx+1]
.d:
END_FN

; ---------------- host ----------------
FN do_host
    mov byte [a_pass], 0
    mov r12d, 2
.hargs:
    cmp r12, [argc_v]
    jae .hparsed
    mov ecx, r12d
    call arg_n
    mov r13, rax
    inc r12d
    mov rcx, r13
    lea rdx, [o_pass]
    call a_equal
    test eax, eax
    jz .husage
    mov ecx, r12d
    call arg_n
    test rax, rax
    jz .husage
    inc r12d
    mov r13, rax
    mov rcx, rax
    call v_pass
    test eax, eax
    jz .hbadpass
    lea rdi, [a_pass]
    mov rsi, r13
    mov ecx, 65
.hcp:
    lodsb
    stosb
    test al, al
    jz .hargs
    dec ecx
    jnz .hcp
    jmp .hbadpass
.husage:
    lea rcx, [t_usage]
    call say_err
    mov eax, 2
    jmp .d
.hbadpass:
    lea rcx, [t_badpass]
    call say_err
    mov eax, 2
    jmp .d
.hparsed:
    call prepare_paths
    test eax, eax
    jz .fail
    lea rcx, [out_buf]
    mov edx, 512
    call pb_start
    lea rcx, [cfg_host_text]
    call pb_str
    cmp byte [a_pass], 0
    je .hnopass
    lea rcx, [t_cfg_pass_line]
    call pb_str
    lea rcx, [a_pass]
    call pb_str
    lea rcx, [t_crlf_z]
    call pb_str
.hnopass:
    call pb_end
    cmp eax, -1
    je .nosave
    mov r14d, eax
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_cfg]
    call path2
    lea rcx, [p1]
    lea rdx, [out_buf]
    mov r8d, r14d
    mov dword [wf_mode], 0644o
    cmp byte [a_pass], 0
    je .hwrite
    mov dword [wf_mode], 0600o
.hwrite:
    call write_file
    mov dword [wf_mode], 0644o
    test eax, eax
    jz .nosave
    mov dword [mp_tgt_count], 0
    call mp_collect_adapters
    call mp_tailscale
    lea rcx, [t_hostmsg]
    call say
    cmp dword [mp_ts_self], 0
    je .lan
    lea rcx, [t_tailscale]
    call say
    mov ecx, [mp_ts_self]
    call say_ip
    lea rcx, [t_nl]
    call say
.lan:
    xor r12d, r12d
.l: cmp r12d, [mp_local_count]
    jae .end
    lea rax, [mp_local_ips]
    mov r13d, [rax+r12*4]
    mov eax, r13d
    and eax, 0xFFFF
    cmp eax, 0xFEA9                     ; 169.254.x.x (self-assigned)
    je .nx
    cmp r13d, [mp_ts_self]              ; the Tailscale address was printed above
    je .nx
.show:
    lea rcx, [t_lan]
    call say
    mov ecx, r13d
    call say_ip
    lea rcx, [t_nl]
    call say
.nx:
    inc r12d
    jmp .l
.end:
    lea rcx, [t_hostend]
    call say
    xor eax, eax
    jmp .d
.nosave:
    lea rcx, [t_nocfg]
    call say_err
.fail:
    mov eax, 1
.d:
END_FN

; ---------------- steam setup ----------------
FN do_steam
    call exe_init
    test eax, eax
    jz .fail
    lea rcx, [p1]
    lea rdx, [exe_dir]
    lea r8, [n_launcher]
    call path2
    lea rcx, [p1]
    call path_kind
    cmp eax, 1
    je .have
    lea rcx, [t_steam_missing]
    call say_err
.have:
    lea rcx, [t_steam1]
    call say
    lea rcx, [t_cmd1]
    call say
    lea rcx, [p1]
    call say
    lea rcx, [t_cmd2]
    call say
    lea rcx, [t_steam2]
    call say
    xor eax, eax
    jmp .d
.fail:
    mov eax, 1
.d:
END_FN

; ---------------- save solo ----------------
; Documents folder: $XDG_DOCUMENTS_DIR, else XDG_DOCUMENTS_DIR in ~/.config/user-dirs.dirs, else ~/Documents. docs_dir, eax 1 ok
FN find_documents
    lea rcx, [s_env_xdg_docs]
    call env_get
    test rax, rax
    jz .userdirs
    cmp byte [rax], '/'
    jne .userdirs
    lea rcx, [docs_dir]
    mov rdx, rax
    lea r8, [s_empty]
    call path2
    cmp eax, -1
    jne .ok
.userdirs:
    lea rcx, [s_env_xdg_config]
    call env_get
    test rax, rax
    jz .homecfg
    cmp byte [rax], '/'
    je .cfgbase
.homecfg:
    cmp qword [home_dir], 0
    je .fallback
    lea rcx, [p2]
    mov rdx, [home_dir]
    lea r8, [s_dot_config]
    call path2
    lea rax, [p2]
.cfgbase:
    lea rcx, [p1]
    mov rdx, rax
    lea r8, [s_userdirs]
    call path2
    cmp eax, -1
    je .fallback
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    cmp rax, 0
    jle .fallback
    mov r13, rax
    lea rcx, [file_buf]
    mov byte [rcx+r13], 0
    xor r12d, r12d                      ; scan position: lines starting with the key
.line:
    lea rsi, [file_buf]
    add rsi, r12
    cmp byte [rsi], 0
    je .fallback
    lea rdi, [k_docs]
    mov ecx, k_docs_len
    repe cmpsb
    je .keyfound
.nl:lea rsi, [file_buf]
    cmp byte [rsi+r12], 0
    je .fallback
    cmp byte [rsi+r12], 10
    je .nextline
    inc r12
    jmp .nl
.nextline:
    inc r12
    jmp .line
.keyfound:
    ; rsi points just behind the opening quote
    lea rdi, [p3]
    xor ecx, ecx
.val:
    mov al, [rsi+rcx]
    cmp al, '"'
    je .valend
    cmp al, 10
    jbe .fallback
    cmp ecx, 900
    jae .fallback
    mov [rdi+rcx], al
    inc ecx
    jmp .val
.valend:
    mov byte [rdi+rcx], 0
    ; "$HOME/..." or an absolute path
    cmp byte [p3], '$'
    jne .abs
    cmp qword [home_dir], 0
    je .fallback
    cmp dword [p3+1], 'HOME'
    jne .fallback
    lea rcx, [docs_dir]
    mov rdx, [home_dir]
    lea r8, [p3+5]
    call path2
    cmp eax, -1
    je .fallback
    jmp .ok
.abs:
    cmp byte [p3], '/'
    jne .fallback
    lea rcx, [docs_dir]
    lea rdx, [p3]
    lea r8, [s_empty]
    call path2
    cmp eax, -1
    je .fallback
    jmp .ok
.fallback:
    cmp qword [home_dir], 0
    je .bad
    lea rcx, [docs_dir]
    mov rdx, [home_dir]
    lea r8, [s_documents]
    call path2
    cmp eax, -1
    je .bad
.ok:
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN do_save_solo
    call prepare_paths
    test eax, eax
    jz .fail
    call find_documents
    test eax, eax
    jz .nodocs
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_saves]
    call path2                          ; p1 = the solo saves
    lea rcx, [stampbuf]
    call time_stamp
    lea rcx, [dest_dir]
    lea rdx, [docs_dir]
    lea r8, [n_backups_dir]
    call path2                          ; dest_dir = <Documents>/MistriMulti Backups
    lea rcx, [p2]
    lea rdx, [dest_dir]
    lea r8, [s_slash]
    lea r9, [stampbuf]
    call path3                          ; p2 = dest_dir/<timestamp>
    cmp eax, -1
    je .nodocs
    mov dword [copied], 0
    lea rcx, [p1]
    call dir_open
    test rax, rax
    js .report
.each:
    call dir_next
    test rax, rax
    jz .done
    mov r13, rax
    lea rcx, [p3]
    lea rdx, [p1]
    lea r8, [s_slash]
    mov r9, r13
    call path3                          ; p3 = source file
    lea rcx, [cand]
    lea rdx, [p2]
    lea r8, [s_slash]
    mov r9, r13
    call path3                          ; cand = destination file
    cmp eax, -1
    je .each
    lea rcx, [p3]
    call path_kind
    cmp eax, 1
    jne .each
    cmp dword [copied], 0
    jne .copy
    lea rcx, [cand2]
    lea rdx, [p2]
    lea r8, [s_x]
    call path2
    lea rcx, [cand2]
    call ensure_dirs                    ; creates the backup folder (and the folders above it) on the first file
.copy:
    lea rcx, [p3]
    lea rdx, [cand]
    call copy_file
    test eax, eax
    jz .each
    inc dword [copied]
    jmp .each
.done:
    call dir_close
.report:
    cmp dword [copied], 0
    je .nosaves
    lea rcx, [t_saved1]
    call say
    mov ecx, [copied]
    call say_int
    lea rcx, [t_saved2]
    call say
    lea rcx, [p2]
    call say
    lea rcx, [t_nl]
    call say
    xor eax, eax
    jmp .d
.nosaves:
    lea rcx, [t_nosaves]
    call say
    xor eax, eax
    jmp .d
.nodocs:
    lea rcx, [t_nodocs]
    call say_err
.fail:
    mov eax, 1
.d:
END_FN

; ---------------- scan and join ----------------
FN list_hosts                   ; prints the numbered list of mp_host_*
    xor r12d, r12d
.l: cmp r12d, [mp_host_count]
    jae .d
    lea rcx, [t_two]
    call say
    lea ecx, [r12+1]
    call say_int
    lea rcx, [t_paren]
    call say
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    call say_ip
    lea rcx, [t_dash]
    call say
    mov eax, r12d
    shl eax, 5
    lea rcx, [mp_host_name]
    add rcx, rax
    call say
    lea rax, [mp_host_flags]
    test byte [rax+r12], 1
    jz .nc
    lea rcx, [t_needroom]
    call say
.nc:
    lea rax, [mp_host_flags]
    test byte [rax+r12], 2
    jz .np
    lea rcx, [t_needpass]
    call say
.np:
    lea rcx, [t_nl]
    call say
    inc r12d
    jmp .l
.d:
END_FN

FN do_scan_only
    lea rcx, [t_scanning]
    call say
    call mp_scan
    cmp dword [mp_host_count], 0
    je .none
    lea rcx, [t_found]
    call say
    call list_hosts
    xor eax, eax
    jmp .d
.none:
    lea rcx, [t_none]
    call say
    xor eax, eax
.d:
END_FN

; Saves the join setup and downloads the host's world. Inputs: join_ip (ASCII), join_port, opt_player (0 = automatic),
; opt_room ("" = default room). eax 0 ok.
FN finish_join
    call prepare_paths
    test eax, eax
    jz .fail
    mov eax, [opt_player]
    test eax, eax
    jnz .have_player
    call pick_player
.have_player:
    mov [cfg_player], eax
    add eax, [join_port]
    cmp eax, 65535
    ja .badport
    mov dword [cfg_mode], 2
    mov eax, [join_port]
    mov [cfg_port], eax
    lea rsi, [join_ip]
    lea rdi, [a_host]
    mov ecx, 32
    rep movsb
    cmp byte [opt_room], 0
    jne .customroom
    lea rsi, [room_default]
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
    jmp .save
.customroom:
    lea rsi, [opt_room]
    lea rdi, [a_room]
    mov ecx, 16
    rep movsb
.save:
    call cfg_save
    test eax, eax
    jz .nosave
    lea rcx, [t_world_dl]
    call say
    lea rcx, [join_ip]
    call ip_parse
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_mp_saves]
    call path2
    mov dword [wf_connect_ms], 3000
    mov ecx, r12d
    lea rdx, [p1]
    call world_fetch
    mov r13d, eax
    lea rcx, [t_joined]
    call say
    lea rcx, [join_ip]
    call say
    lea rcx, [t_nl]
    call say
    lea rcx, [t_player_is]
    call say
    mov ecx, [cfg_player]
    call say_int
    lea rcx, [t_nl]
    call say
    lea rcx, [t_nl]
    call say
    lea rcx, [t_world_ok]
    test r13d, r13d
    jz .msg
    lea rcx, [t_world_no]
.msg:
    call say
    xor eax, eax
    jmp .d
.badport:
    lea rcx, [t_badport]
    call say_err
    jmp .fail
.nosave:
    lea rcx, [t_nocfg]
    call say_err
.fail:
    mov eax, 1
.d:
END_FN

; Asks for a room code until it is valid or empty. rcx = prompt. opt_room is set; eax 1 ok, 0 when the input ended
FN ask_room
    mov r12, rcx
    mov r14d, 5
.again:
    dec r14d
    js .bad
    mov rcx, r12
    lea rdx, [ans]
    mov r8d, 16
    call ask
    cmp eax, -1
    je .bad
    test eax, eax
    jz .empty
    lea rcx, [ans]
    call v_room
    test eax, eax
    jz .invalid
    lea rsi, [ans]
    lea rdi, [opt_room]
    mov ecx, 16
    rep movsb
    mov eax, 1
    jmp .d
.empty:
    mov byte [opt_room], 0
    mov eax, 1
    jmp .d
.invalid:
    lea rcx, [t_badroom]
    call say
    jmp .again
.bad:
    xor eax, eax
.d:
END_FN

; The interactive part of join: scan, list, choose. Fills join_ip/join_port/join_flags. eax 1 chosen, 0 nothing chosen
FN choose_host
    mov r15d, 10                        ; attempts
.scan:
    dec r15d
    js .nothing
    lea rcx, [t_scanning]
    call say
    call mp_scan
    cmp dword [mp_host_count], 0
    je .empty
    lea rcx, [t_found]
    call say
    call list_hosts
    jmp .ask
.empty:
    lea rcx, [t_none]
    call say
.ask:
    lea rcx, [t_pick]
    lea rdx, [ans]
    mov r8d, 40
    call ask
    cmp eax, -1
    je .nothing
    test eax, eax
    jz .nothing
    movzx eax, byte [ans]
    or al, 32
    cmp al, 'r'
    je .rescan
    lea rcx, [ans]
    call v_ipv4
    test eax, eax
    jnz .typed
    lea rcx, [ans]
    call a2i
    cmp eax, 1
    jl .badpick
    cmp eax, [mp_host_count]
    jg .badpick
    dec eax
    mov r12d, eax
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [join_ip]
    call ip_text
    lea rax, [mp_host_port]
    movzx eax, word [rax+r12*2]
    mov [join_port], eax
    lea rax, [mp_host_flags]
    movzx eax, byte [rax+r12]
    mov [join_flags], eax
    test eax, 1
    jz .chosen
    lea rcx, [t_roomneed]
    call ask_room
    test eax, eax
    jz .nothing
    cmp byte [opt_room], 0
    je .ask                              ; a room code is required for this host
    jmp .chosen
.typed:
    lea rsi, [ans]
    lea rdi, [join_ip]
    mov ecx, 32
    rep movsb
    mov dword [join_port], 7777
    mov dword [join_flags], 0
    cmp dword [opt_have_room], 0
    jne .chosen
    lea rcx, [t_roomask]
    call ask_room
    test eax, eax
    jz .nothing
    jmp .chosen
.badpick:
    lea rcx, [t_badpick]
    call say
    jmp .ask
.rescan:
    jmp .scan
.chosen:
    test dword [join_flags], 2
    jz .chosen_ok
    cmp byte [a_pass], 0
    jne .chosen_ok
.askpass:
    lea rcx, [t_passask]
    lea rdx, [host_pass]
    mov r8d, 70
    call ask
    cmp eax, -1
    je .nothing
    test eax, eax
    jz .nothing                          ; this host cannot be joined without its password
    lea rcx, [host_pass]
    call v_pass
    test eax, eax
    jnz .gotpass
    lea rcx, [t_badpass]
    call say
    jmp .askpass
.gotpass:
    lea rsi, [host_pass]
    lea rdi, [a_pass]
    mov ecx, 65
    rep movsb
.chosen_ok:
    mov eax, 1
    jmp .d
.nothing:
    xor eax, eax
.d:
END_FN

FN do_join
    mov dword [opt_player], 0
    mov byte [opt_room], 0
    mov dword [opt_have_room], 0
    mov dword [opt_port], 7777
    mov qword [arg_ip], 0
    mov byte [a_pass], 0
    mov r12d, 2
.args:
    cmp r12, [argc_v]
    jae .parsed
    mov ecx, r12d
    call arg_n
    mov r13, rax
    inc r12d
    mov rcx, r13
    lea rdx, [o_player]
    call a_equal
    test eax, eax
    jnz .o_player
    mov rcx, r13
    lea rdx, [o_room]
    call a_equal
    test eax, eax
    jnz .o_room
    mov rcx, r13
    lea rdx, [o_port]
    call a_equal
    test eax, eax
    jnz .o_port
    mov rcx, r13
    lea rdx, [o_pass]
    call a_equal
    test eax, eax
    jnz .o_pass
    cmp byte [r13], '-'
    je .usage
    cmp qword [arg_ip], 0
    jne .usage
    mov [arg_ip], r13
    jmp .args
.o_player:
    mov ecx, r12d
    call arg_n
    test rax, rax
    jz .usage
    inc r12d
    mov rcx, rax
    call a2i
    cmp eax, 1
    jl .badplayer
    cmp eax, 7
    jg .badplayer
    mov [opt_player], eax
    jmp .args
.o_room:
    mov ecx, r12d
    call arg_n
    test rax, rax
    jz .usage
    inc r12d
    mov r13, rax
    mov rcx, rax
    call v_room
    test eax, eax
    jz .badroom
    lea rdi, [opt_room]
    mov rsi, r13
    mov ecx, 9
    rep movsb
    mov dword [opt_have_room], 1
    jmp .args
.o_pass:
    mov ecx, r12d
    call arg_n
    test rax, rax
    jz .usage
    inc r12d
    mov r13, rax
    mov rcx, rax
    call v_pass
    test eax, eax
    jz .badpass
    lea rdi, [a_pass]
    mov rsi, r13
    mov ecx, 65
.pcp:
    lodsb
    stosb
    test al, al
    jz .args
    dec ecx
    jnz .pcp
    jmp .badpass
.o_port:
    mov ecx, r12d
    call arg_n
    test rax, rax
    jz .usage
    inc r12d
    mov rcx, rax
    call a2i
    cmp eax, 1
    jl .badport
    cmp eax, 65535
    jg .badport
    mov [opt_port], eax
    jmp .args
.parsed:
    cmp qword [arg_ip], 0
    je .interactive
    mov rcx, [arg_ip]
    call v_ipv4
    test eax, eax
    jz .badip
    lea rdi, [join_ip]
    mov rsi, [arg_ip]
    mov ecx, 32
.cp:lodsb
    stosb
    test al, al
    jz .cpd
    dec ecx
    jnz .cp
.cpd:
    mov eax, [opt_port]
    mov [join_port], eax
    mov dword [join_flags], 0
    jmp .go
.interactive:
    call choose_host
    test eax, eax
    jz .cancel
    cmp dword [opt_port], 7777
    je .go
    mov eax, [opt_port]
    mov [join_port], eax
.go:
    call finish_join
    jmp .d
.usage:
    lea rcx, [t_usage]
    call say_err
    mov eax, 2
    jmp .d
.badplayer:
    lea rcx, [t_badplayer]
    jmp .err
.badroom:
    lea rcx, [t_badroom]
    jmp .err
.badpass:
    lea rcx, [t_badpass]
    jmp .err
.badport:
    lea rcx, [t_badport]
    jmp .err
.badip:
    lea rcx, [t_badip]
.err:
    call say_err
    mov eax, 2
    jmp .d
.cancel:
    lea rcx, [t_cancel]
    call say_err
    mov eax, 1
.d:
END_FN

; ---------------- test hooks ----------------
; --scan <file>: writes "<ip> <port> <flags> <name>" per host found
FN hook_scan
    mov ecx, 2
    call arg_n
    test rax, rax
    jz .bad
    mov r14, rax
    call mp_scan
    lea rcx, [out_buf]
    mov edx, 4000
    call pb_start
    xor r12d, r12d
.l: cmp r12d, [mp_host_count]
    jae .write
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [mp_ascii]
    call ip_text
    lea rcx, [mp_ascii]
    call pb_str
    mov cl, ' '
    call pb_chr
    lea rax, [mp_host_port]
    movzx ecx, word [rax+r12*2]
    call pb_int
    mov cl, ' '
    call pb_chr
    lea rax, [mp_host_flags]
    movzx ecx, byte [rax+r12]
    call pb_int
    mov cl, ' '
    call pb_chr
    mov eax, r12d
    shl eax, 5
    lea rcx, [mp_host_name]
    add rcx, rax
    call pb_str
    mov cl, 10
    call pb_chr
    inc r12d
    jmp .l
.write:
    call pb_end
    mov r8d, eax
    cmp eax, -1
    je .bad
    mov rcx, r14
    lea rdx, [out_buf]
    call write_file
    xor eax, eax
    jmp .d
.bad:
    mov eax, 1
.d:
END_FN

; --targets <file>: writes "self <ip>" (this computer's Tailscale address) and "target <ip>" for every address a scan would query
FN hook_targets
    mov ecx, 2
    call arg_n
    test rax, rax
    jz .bad
    mov r14, rax
    mov dword [mp_tgt_count], 0
    call mp_collect_adapters
    call mp_tailscale
    lea rcx, [out_buf]
    mov edx, 4000
    call pb_start
    cmp dword [mp_ts_self], 0
    je .targets
    lea rcx, [t_self]
    call pb_str
    mov ecx, [mp_ts_self]
    lea rdx, [mp_ascii]
    call ip_text
    lea rcx, [mp_ascii]
    call pb_str
    mov cl, 10
    call pb_chr
.targets:
    xor r12d, r12d
.l: cmp r12d, [mp_tgt_count]
    jae .write
    lea rcx, [t_target]
    call pb_str
    lea rax, [mp_tgt]
    mov ecx, [rax+r12*4]
    lea rdx, [mp_ascii]
    call ip_text
    lea rcx, [mp_ascii]
    call pb_str
    mov cl, 10
    call pb_chr
    inc r12d
    jmp .l
.write:
    call pb_end
    mov r8d, eax
    cmp eax, -1
    je .bad
    mov rcx, r14
    lea rdx, [out_buf]
    call write_file
    xor eax, eax
    jmp .d
.bad:
    mov eax, 1
.d:
END_FN

; --stamp <seconds since 1970>: prints the backup folder name for that moment (a test hook for the date arithmetic)
FN hook_stamp
    mov ecx, 2
    call arg_n
    test rax, rax
    jz .bad
    xor edx, edx
    xor ecx, ecx
.d: movzx r8d, byte [rax+rcx]
    test r8d, r8d
    jz .go
    sub r8d, '0'
    cmp r8d, 9
    ja .bad
    imul rdx, rdx, 10
    add rdx, r8
    inc ecx
    cmp ecx, 15
    jb .d
    jmp .bad
.go:
    lea rcx, [stampbuf]
    call time_stamp_at
    lea rcx, [stampbuf]
    call say
    lea rcx, [t_nl]
    call say
    xor eax, eax
    jmp .e
.bad:
    mov eax, 1
.e:
END_FN

; --fetch <ip> <folder> <result file>: world download; the result code is written to the file
FN hook_fetch
    mov ecx, 2
    call arg_n
    test rax, rax
    jz .bad
    mov r12, rax
    mov ecx, 3
    call arg_n
    test rax, rax
    jz .bad
    mov r13, rax
    mov ecx, 4
    call arg_n
    test rax, rax
    jz .bad
    mov r14, rax
    mov rcx, r12
    call v_ipv4
    test eax, eax
    jz .bad
    mov rcx, r12
    call ip_parse
    mov ecx, eax
    mov rdx, r13
    call world_fetch
    mov r15d, eax
    lea rcx, [result_buf]
    mov edx, 24
    call pb_start
    mov ecx, r15d
    call pb_int
    call pb_end
    mov r8d, eax
    mov rcx, r14
    lea rdx, [result_buf]
    call write_file
    xor eax, eax
    jmp .d
.bad:
    mov eax, 1
.d:
END_FN

program_main:
    mov ecx, 1
    call arg_n
    test rax, rax
    jz .usage
    mov r12, rax
    mov rcx, r12
    lea rdx, [a_host_cmd]
    call a_equal
    test eax, eax
    jnz .host
    mov rcx, r12
    lea rdx, [a_join_cmd]
    call a_equal
    test eax, eax
    jnz .join
    mov rcx, r12
    lea rdx, [a_scan_cmd]
    call a_equal
    test eax, eax
    jnz .scan
    mov rcx, r12
    lea rdx, [a_steam_cmd]
    call a_equal
    test eax, eax
    jnz .steam
    mov rcx, r12
    lea rdx, [a_save_cmd]
    call a_equal
    test eax, eax
    jnz .save
    mov rcx, r12
    lea rdx, [a_scan_hook]
    call a_equal
    test eax, eax
    jnz .hscan
    mov rcx, r12
    lea rdx, [a_fetch_hook]
    call a_equal
    test eax, eax
    jnz .hfetch
    mov rcx, r12
    lea rdx, [a_targets_hook]
    call a_equal
    test eax, eax
    jnz .htargets
    mov rcx, r12
    lea rdx, [a_stamp_hook]
    call a_equal
    test eax, eax
    jnz .hstamp
    mov rcx, r12
    lea rdx, [a_help1]
    call a_equal
    test eax, eax
    jnz .help
    mov rcx, r12
    lea rdx, [a_help2]
    call a_equal
    test eax, eax
    jnz .help
.usage:
    lea rcx, [t_usage]
    call say_err
    mov ecx, 2
    call sys_exit
.help:
    lea rcx, [t_usage]
    call say
    xor ecx, ecx
    call sys_exit
.host:
    call do_host
    jmp .exit
.join:
    call do_join
    jmp .exit
.scan:
    call do_scan_only
    jmp .exit
.steam:
    call do_steam
    jmp .exit
.save:
    call do_save_solo
    jmp .exit
.hscan:
    call hook_scan
    jmp .exit
.hfetch:
    call hook_fetch
    jmp .exit
.htargets:
    call hook_targets
    jmp .exit
.hstamp:
    call hook_stamp
.exit:
    mov ecx, eax
    call sys_exit

section .note.GNU-stack noalloc noexec nowrite progbits
