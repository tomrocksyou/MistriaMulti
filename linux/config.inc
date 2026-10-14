; Where the game keeps its files on Linux, and the launcher.cfg shared by the launcher and the manager.
;
; The game's CONFIG_DIRECTORY is GameMaker's game_save_id (scripts/Serialization/Serde/SerdeUtils.gml). On Windows that is
; %LOCALAPPDATA%\FieldsOfMistria. For Linux the game files do not say where the runtime puts it, so find_datadir looks in
; every place it can plausibly be and takes the first folder that already holds the game's "saves" (or this mod's "mod_data"):
;   1. $MISTRIMULTI_DATA_DIR                   (explicit; always wins, no search)
;   2. $STEAM_COMPAT_DATA_PATH/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria   (Steam sets it for Proton games)
;   3. ${XDG_CONFIG_HOME:-~/.config}/FieldsOfMistria                  (GameMaker's native Linux runner convention)
;   4. ${XDG_DATA_HOME:-~/.local/share}/FieldsOfMistria
;   5. <Steam library>/steamapps/compatdata/<any app id>/pfx/.../AppData/Local/FieldsOfMistria  (Steam Deck, Proton)
; If nothing exists yet but STEAM_COMPAT_DATA_PATH is set, entry 2 is used. Otherwise find_datadir fails and the caller
; falls back to the plain game launch (launcher) or says so (manager).

section .data
k_mode db 5,'mode='
k_host db 5,'host='
k_port db 5,'port='
k_player db 7,'player='
k_room db 5,'room='
room_default db '4d495354',0
a_host_s db 'host',0
a_join_s db 'join',0
s_env_datadir db 'MISTRIMULTI_DATA_DIR',0
s_env_compat db 'STEAM_COMPAT_DATA_PATH',0
s_env_home db 'HOME',0
s_env_xdg_config db 'XDG_CONFIG_HOME',0
s_env_xdg_data db 'XDG_DATA_HOME',0
s_proton_sub db '/pfx/drive_c/users/steamuser/AppData/Local/FieldsOfMistria',0
s_foldername db '/FieldsOfMistria',0
s_dot_config db '/.config',0
s_dot_share db '/.local/share',0
s_compatdata db '/steamapps/compatdata',0
s_saves db '/saves',0
s_mod_data db '/mod_data',0
s_mod_sub db '/mod_data/mistrimulti',0
s_x db '/x',0
s_empty db 0
s_mp_saves db '/multiplayer/saves',0
s_proc_exe db '/proc/self/exe',0
n_cfg db '/launcher.cfg',0
steam_roots dq sr1, sr2, sr3, 0
sr1 db '/.local/share/Steam',0
sr2 db '/.steam/steam',0
sr3 db '/.var/app/com.valvesoftware.Steam/.local/share/Steam',0
align 8

section .bss
exe_path resb 1100
exe_dir resb 1100
data_dir resb 1100
dd_alt resb 1100
home_dir resq 1
mod_dir resb 1100
p1 resb 1100
p2 resb 1100
p3 resb 1100
cand resb 1100
cand2 resb 1100
file_buf resb 8200
out_buf resb 4096
cfg_len resq 1
cfg_mode resd 1
cfg_port resd 1
cfg_player resd 1
cfg_local resd 1
a_mode resb 16
a_host resb 32
a_port resb 16
a_player resb 16
a_room resb 16

section .text
FN path2                        ; rcx destination (1100 bytes), rdx first part, r8 second part -> eax length, -1 if too long
    mov r12, rdx
    mov r13, r8
    mov edx, 1100
    call pb_start
    mov rcx, r12
    call pb_str
    mov rcx, r13
    call pb_str
    call pb_end
END_FN

FN path3                        ; rcx destination, rdx, r8, r9 parts
    mov r12, rdx
    mov r13, r8
    mov r14, r9
    mov edx, 1100
    call pb_start
    mov rcx, r12
    call pb_str
    mov rcx, r13
    call pb_str
    mov rcx, r14
    call pb_str
    call pb_end
END_FN

; Finds the program's own folder through /proc/self/exe. eax 1 ok.
FN exe_init
    lea rcx, [s_proc_exe]
    lea rdx, [exe_path]
    mov r8d, 1090
    call sys_readlink
    test rax, rax
    jg .have
    xor ecx, ecx                        ; no /proc: fall back to the name the program was started with
    call arg_n
    test rax, rax
    jz .bad
    cmp byte [rax], '/'
    jne .bad
    lea rcx, [exe_path]
    mov rdx, rax
    call str_copy
    jmp .copied
.have:
    lea rcx, [exe_path]
    mov byte [rcx+rax], 0
.copied:
    lea rdx, [exe_path]
    lea rcx, [exe_dir]
    call str_copy
    lea rcx, [exe_dir]
    call cut_last_component
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; A folder name is acceptable when it is absolute, short, and can sit inside JSON text and a command line unchanged.
FN valid_dir                    ; rcx path -> eax 1/0
    cmp byte [rcx], '/'
    jne .no
    xor edx, edx
.l: movzx eax, byte [rcx+rdx]
    test al, al
    jz .end
    cmp al, 32
    jb .no
    cmp al, 127
    je .no
    cmp al, '"'
    je .no
    cmp al, '\'
    je .no
    inc edx
    jmp .l
.end:
    cmp edx, 380
    ja .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; rcx = candidate game folder. A folder holding "saves" is taken at once (eax 1, data_dir set); one that only holds
; "mod_data" is remembered in dd_alt for the case that nothing better turns up.
FN dd_try
    mov r12, rcx
    lea rcx, [p3]
    mov rdx, r12
    lea r8, [s_saves]
    call path2
    cmp eax, -1
    je .no
    lea rcx, [p3]
    call path_kind
    cmp eax, 2
    jne .alt
    lea rcx, [data_dir]
    mov rdx, r12
    call str_copy
    mov eax, 1
    jmp .d
.alt:
    cmp byte [dd_alt], 0
    jne .no
    lea rcx, [p3]
    mov rdx, r12
    lea r8, [s_mod_data]
    call path2
    cmp eax, -1
    je .no
    lea rcx, [p3]
    call path_kind
    cmp eax, 2
    jne .no
    lea rcx, [dd_alt]
    mov rdx, r12
    call str_copy
.no:
    xor eax, eax
.d:
END_FN

; Fills data_dir. eax 1 ok, 0 if the game folder could not be determined.
FN find_datadir
    mov byte [data_dir], 0
    mov byte [dd_alt], 0
    lea rcx, [s_env_home]
    call env_get
    mov [home_dir], rax
    lea rcx, [s_env_datadir]
    call env_get
    test rax, rax
    jz .search
    cmp byte [rax], 0
    je .search
    mov r12, rax
    mov rcx, rax
    call valid_dir
    test eax, eax
    jz .fail
    lea rcx, [data_dir]
    mov rdx, r12
    call str_copy
    jmp .trim
.search:
    xor r15d, r15d                     ; STEAM_COMPAT_DATA_PATH, kept for the last resort
    lea rcx, [s_env_compat]
    call env_get
    test rax, rax
    jz .config
    cmp byte [rax], 0
    je .config
    mov r15, rax
    lea rcx, [cand]
    mov rdx, r15
    lea r8, [s_proton_sub]
    call path2
    cmp eax, -1
    je .config
    lea rcx, [cand]
    call dd_try
    test eax, eax
    jnz .found
.config:
    lea rcx, [s_env_xdg_config]
    lea rdx, [s_dot_config]
    call .base
    test rax, rax
    jz .data
    lea rcx, [cand]
    mov rdx, rax
    lea r8, [s_foldername]
    call path2
    cmp eax, -1
    je .data
    lea rcx, [cand]
    call dd_try
    test eax, eax
    jnz .found
.data:
    lea rcx, [s_env_xdg_data]
    lea rdx, [s_dot_share]
    call .base
    test rax, rax
    jz .steam
    lea rcx, [cand]
    mov rdx, rax
    lea r8, [s_foldername]
    call path2
    cmp eax, -1
    je .steam
    lea rcx, [cand]
    call dd_try
    test eax, eax
    jnz .found
.steam:
    cmp qword [home_dir], 0
    je .alt
    xor r13d, r13d
.root:
    lea rax, [steam_roots]
    mov rdx, [rax+r13*8]
    test rdx, rdx
    jz .alt
    lea rcx, [cand2]
    mov r8, rdx
    mov rdx, [home_dir]
    lea r9, [s_compatdata]
    call path3
    cmp eax, -1
    je .nextroot
    lea rcx, [cand2]
    call dir_open
    test rax, rax
    js .nextroot
.entry:
    call dir_next
    test rax, rax
    jz .endroot
    mov r12, rax
    cmp byte [rax], '.'
    je .entry
    ; cand = cand2 + "/" + name + proton sub folder
    lea rcx, [cand]
    mov edx, 1100
    call pb_start
    lea rcx, [cand2]
    call pb_str
    lea rcx, [s_slash]
    call pb_str
    mov rcx, r12
    call pb_str
    lea rcx, [s_proton_sub]
    call pb_str
    call pb_end
    cmp eax, -1
    je .entry
    lea rcx, [cand]
    call dd_try
    test eax, eax
    jz .entry
    call dir_close
    jmp .found
.endroot:
    call dir_close
.nextroot:
    inc r13d
    jmp .root
.alt:
    cmp byte [dd_alt], 0
    je .lastresort
    lea rcx, [data_dir]
    lea rdx, [dd_alt]
    call str_copy
    jmp .found
.lastresort:
    test r15, r15
    jz .fail
    lea rcx, [data_dir]
    mov rdx, r15
    lea r8, [s_proton_sub]
    call path2
    cmp eax, -1
    je .fail
.found:
.trim:
    lea rcx, [data_dir]
    call valid_dir
    test eax, eax
    jz .fail
    lea rcx, [data_dir]
    call str_len
.tl:cmp rax, 1
    jbe .ok
    lea rdx, [data_dir]
    cmp byte [rdx+rax-1], '/'
    jne .ok
    mov byte [rdx+rax-1], 0
    dec rax
    jmp .tl
.ok:
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
    jmp .d
; local helper: rcx = name of an XDG variable, rdx = fallback below $HOME -> rax pointer to a base folder, 0 if none
.base:
    push rdx
    call env_get
    pop rdx
    test rax, rax
    jz .homebase
    cmp byte [rax], '/'
    je .basedone
.homebase:
    cmp qword [home_dir], 0
    je .nobase
    push rdx
    lea rcx, [p2]
    mov rdx, [home_dir]
    pop r8
    call path2
    cmp eax, -1
    je .nobase
    lea rax, [p2]
    ret
.nobase:
    xor eax, eax
.basedone:
    ret
.d:
END_FN

; Fills mod_dir and creates it. eax 1 ok.
FN mod_dir_init
    lea rcx, [mod_dir]
    lea rdx, [data_dir]
    lea r8, [s_mod_sub]
    call path2
    cmp eax, -1
    je .bad
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_cfg]
    call path2
    lea rcx, [p1]
    call ensure_dirs
    mov eax, 1
    jmp .d
.bad:
    mov byte [mod_dir], 0
    xor eax, eax
.d:
END_FN

; ---------------- launcher.cfg ----------------
; rcx = key (length-prefixed), rdx = out ASCII buffer, r8 = out size. Value of the "key=..." line in file_buf -> eax length (0 if absent)
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

; Reads and validates launcher.cfg. eax 1 valid. Sets cfg_mode (1 host, 2 join), cfg_port, cfg_player, cfg_local, a_mode, a_host, a_room.
; The checks are the Windows launcher's, one for one: every value is validated before it reaches a command line or a file.
FN load_config
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_cfg]
    call path2
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
    cmp dword [cfg_mode], 1
    jne .join
    mov dword [cfg_player], 0
    mov eax, [cfg_port]
    mov [cfg_local], eax
    mov byte [a_host], 0
    jmp .ok
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
.ok:
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; Writes launcher.cfg from cfg_mode, a_host, cfg_port, cfg_player, a_room (same text as the Windows launcher: CRLF line ends). eax 1 ok.
FN cfg_save
    lea rcx, [out_buf]
    mov edx, 512
    call pb_start
    lea rcx, [t_cfg_mode]
    call pb_str
    lea rcx, [a_host_s]
    cmp dword [cfg_mode], 1
    je .m
    lea rcx, [a_join_s]
.m: call pb_str
    lea rcx, [t_cfg_host]
    call pb_str
    lea rcx, [a_host]
    call pb_str
    lea rcx, [t_cfg_port]
    call pb_str
    mov ecx, [cfg_port]
    call pb_int
    lea rcx, [t_cfg_player]
    call pb_str
    mov ecx, [cfg_player]
    call pb_int
    lea rcx, [t_cfg_room]
    call pb_str
    lea rcx, [a_room]
    call pb_str
    lea rcx, [t_crlf]
    call pb_str
    call pb_end
    cmp eax, -1
    je .bad
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_cfg]
    call path2
    lea rcx, [p1]
    lea rdx, [out_buf]
    mov r8d, r12d
    call write_file
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

section .data
t_cfg_mode db 'mode=',0
t_cfg_host db 13,10,'host=',0
t_cfg_port db 13,10,'port=',0
t_cfg_player db 13,10,'player=',0
t_cfg_room db 13,10,'room=',0
t_crlf db 13,10,0
align 8
section .text
