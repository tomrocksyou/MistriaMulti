; In-game menu supervisor of the Linux launcher (docs/SYNC-MENU.md; the Windows twin is in launcher/launcher.asm).
;
; The game's mod cannot start programs, so everything the player chooses in the game's Multiplayer menu reaches the launcher
; through two small files in <game data>/mod_data/mistrimulti/menu/ (the same file bridge the game and helper already use):
;   cmd.txt      written by the mod, "key=value" lines:  seq=N, cmd=host|join|scan|stop, host=IPv4, port=N, password=..., room=8hex
;                The launcher reads it about four times a second, deletes it at once (a password must not stay on disk) and
;                answers each new "seq" exactly once.
;   status.json  written by the launcher about once a second and after every change: heartbeat, the last seq it applied,
;                state (idle|hosting|joining|downloading|ready|error|scanning), err (a number the mod turns into plain words),
;                this computer's addresses (host) and the hosts found by the last scan.
; Nothing listens and no helper runs until the player picks Host or Join: standby opens no port at all. Hosting starts the
; transport helper plus the discovery answer (UDP 7776) and the world server (TCP 7775); Join starts the helper as a guest, waits
; for the host's authenticated WELCOME (so a wrong password is reported before anything is downloaded), then downloads the world.
; Everything the player or the network can send is validated like launcher.cfg is, before it reaches a file or a command line.

%define ST_IDLE 0
%define ST_HOSTING 1
%define ST_JOINING 2
%define ST_DOWNLOAD 3
%define ST_READY 4
%define ST_ERROR 5
%define ST_SCANNING 6
%define ST_STOPPED 7                   ; the launcher is ending (the game closed): the mod stops showing Idle at once

; err codes (docs/SYNC-MENU.md has the table; the mod turns them into words)
%define ER_NONE 0
%define ER_NOHELPER 1
%define ER_HELPERFAIL 2
%define ER_BADADDR 3
%define ER_NOANSWER 4
%define ER_BADPASS 5
%define ER_CONTROL 6
%define ER_REJ_BASE 20                  ; + the helper's reject reason: 21 password, 22 banned, 23 slot busy, 24 full, 26 password needed
%define ER_WORLD_BASE 40                ; + world_fetch result: 41 cannot connect, 42 host has no world, 43 bad reply, 44 checksum, 45 cannot write, 46 memory, 47 refused (no joined session or wrong proof)

section .data
n_menudir db '/menu/x',0
n_menucmd db '/menu/cmd.txt',0
n_menustat db '/menu/status.json',0
k_seq db 4,'seq='
k_cmd db 4,'cmd='
c_scan db 'scan',0
c_stop db 'stop',0
s_statusfile db '/status.json',0
f_auth db '"auth":',0
f_reject db '"reject":',0
j_m1 db '{"v":1,"hb":',0
j_m2 db ',"seq":',0
j_m3 db ',"state":"',0
j_m4 db '","err":',0
j_m5 db ',"session":"',0
j_m6 db '","helper":',0
j_m7 db ',"scan":',0
j_m8 db ',"port":',0
j_m9 db ',"addrs":[',0
j_m10 db '],"hosts":[',0
j_m11 db ']}',0
j_h1 db '{"ip":"',0
j_h2 db '","port":',0
j_h3 db ',"flags":',0
j_h4 db ',"name":"',0
j_h5 db '"}',0
j_q db '"',0
j_comma db ',',0
st_idle db 'idle',0
st_hosting db 'hosting',0
st_joining db 'joining',0
st_download db 'downloading',0
st_ready db 'ready',0
st_error db 'error',0
st_scanning db 'scanning',0
st_stopped db 'stopped',0
se_none db 'none',0
se_host db 'host',0
se_join db 'join',0
r_standby db 'MistriaMulti: no launcher.cfg is needed. Waiting for Host or Join in the in-game Multiplayer menu.',10,0
align 8
sv_state_names dq st_idle, st_hosting, st_joining, st_download, st_ready, st_error, st_scanning, st_stopped
sv_session_names dq se_none, se_host, se_join

section .bss
sv_legacy resd 1
sv_seq resd 1
sv_state resd 1
sv_err resd 1
sv_session resd 1
sv_phase resd 1
sv_scan resd 1
sv_helper_ok resd 1
sv_prev_slot resd 1
sv_cmd resd 1
sv_deadline resq 1
sv_last_write resq 1
sv_addr_count resd 1
sv_addrs resd 10
sv_t_seq resb 16
sv_t_cmd resb 16
sv_t_host resb 32
sv_t_port resb 16
sv_t_pass resb 72
sv_t_room resb 16
sv_tmp resb 48
sv_ipbuf resb 20
sv_json resb 4096

section .text
; ---------------- status file ----------------
FN sv_status_write
    lea rcx, [sv_json]
    mov edx, 4096
    call pb_start
    lea rcx, [j_m1]
    call pb_str
    call ticks_ms
    mov rcx, rax
    call pb_int
    lea rcx, [j_m2]
    call pb_str
    mov ecx, [sv_seq]
    call pb_int
    lea rcx, [j_m3]
    call pb_str
    mov eax, [sv_state]
    lea rdx, [sv_state_names]
    mov rcx, [rdx+rax*8]
    call pb_str
    lea rcx, [j_m4]
    call pb_str
    mov ecx, [sv_err]
    call pb_int
    lea rcx, [j_m5]
    call pb_str
    mov eax, [sv_session]
    lea rdx, [sv_session_names]
    mov rcx, [rdx+rax*8]
    call pb_str
    lea rcx, [j_m6]
    call pb_str
    mov ecx, [sv_helper_ok]
    call pb_int
    lea rcx, [j_m7]
    call pb_str
    mov ecx, [sv_scan]
    call pb_int
    lea rcx, [j_m8]
    call pb_str
    mov ecx, [cfg_port]
    call pb_int
    lea rcx, [j_m9]
    call pb_str
    xor r12d, r12d
.addr:
    cmp r12d, [sv_addr_count]
    jae .addrs_done
    test r12d, r12d
    jz .a1
    lea rcx, [j_comma]
    call pb_str
.a1:
    lea rcx, [j_q]
    call pb_str
    lea rax, [sv_addrs]
    mov ecx, [rax+r12*4]
    lea rdx, [sv_ipbuf]
    call ip_text
    lea rcx, [sv_ipbuf]
    call pb_str
    lea rcx, [j_q]
    call pb_str
    inc r12d
    jmp .addr
.addrs_done:
    lea rcx, [j_m10]
    call pb_str
    xor r12d, r12d
.host:
    cmp r12d, [mp_host_count]
    jae .hosts_done
    cmp r12d, 12
    jae .hosts_done
    test r12d, r12d
    jz .h1
    lea rcx, [j_comma]
    call pb_str
.h1:
    lea rcx, [j_h1]
    call pb_str
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [sv_ipbuf]
    call ip_text
    lea rcx, [sv_ipbuf]
    call pb_str
    lea rcx, [j_h2]
    call pb_str
    lea rax, [mp_host_port]
    movzx ecx, word [rax+r12*2]
    call pb_int
    lea rcx, [j_h3]
    call pb_str
    lea rax, [mp_host_flags]
    movzx ecx, byte [rax+r12]
    call pb_int
    lea rcx, [j_h4]
    call pb_str
    mov eax, r12d
    shl eax, 5
    lea rsi, [mp_host_name]
    add rsi, rax
    xor r13d, r13d
.nm:
    movzx ecx, byte [rsi+r13]
    test cl, cl
    jz .nmend
    cmp cl, '"'
    je .sub
    cmp cl, '\'
    jne .putc
.sub:
    mov cl, '_'
.putc:
    call pb_chr
    inc r13d
    jmp .nm
.nmend:
    lea rcx, [j_h5]
    call pb_str
    inc r12d
    jmp .host
.hosts_done:
    lea rcx, [j_m11]
    call pb_str
    call pb_end
    cmp eax, -1
    je .d
    mov r13d, eax
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_menustat]
    call path2
    lea rcx, [p1]
    lea rdx, [sv_json]
    mov r8d, r13d
    call write_file
    call ticks_ms
    mov [sv_last_write], rax
.d:
END_FN

FN sv_set                       ; ecx = state, edx = err: records and publishes at once
    mov [sv_state], ecx
    mov [sv_err], edx
    call sv_status_write
END_FN

; Writes the status again after a second, so the game sees the launcher is alive.
FN sv_status_tick
    call ticks_ms
    sub rax, [sv_last_write]
    cmp rax, 1000
    jb .d
    call sv_status_write
.d:
END_FN

; ---------------- start / stop of a session ----------------
FN sess_stop
    call stop_helper
    call disc_stop
    mov dword [cfg_mode], 0
    xor ecx, ecx
    call write_control                  ; control.json says enabled:false, mode idle
    mov dword [sv_phase], 0
    mov dword [sv_session], 0
    mov dword [sv_addr_count], 0
END_FN

; Fills sv_addrs with this computer's addresses, the Tailscale one first (what a friend types or scans for).
FN sv_collect_addrs
    mov dword [sv_addr_count], 0
    mov dword [mp_tgt_count], 0
    call mp_collect_adapters
    call mp_tailscale
    mov ecx, [mp_ts_self]
    test ecx, ecx
    jz .locals
    lea rax, [sv_addrs]
    mov [rax], ecx
    mov dword [sv_addr_count], 1
.locals:
    xor r12d, r12d
.l: cmp r12d, [mp_local_count]
    jae .d
    mov ecx, [sv_addr_count]
    cmp ecx, 8
    jae .d
    lea rax, [mp_local_ips]
    mov r8d, [rax+r12*4]
    mov eax, r8d
    and eax, 0xFFFF
    cmp eax, 0xFEA9                     ; 169.254.x.x (self-assigned): no use to a friend
    je .next
    xor edx, edx
    lea r9, [sv_addrs]
.dup:
    cmp edx, ecx
    jae .add
    cmp [r9+rdx*4], r8d
    je .next
    inc edx
    jmp .dup
.add:
    mov [r9+rcx*4], r8d
    inc dword [sv_addr_count]
.next:
    inc r12d
    jmp .l
.d:
END_FN

; Hosting: sv_t_port / sv_t_pass / sv_t_room were validated by the caller.
FN sv_host
    call sess_stop
    mov dword [cfg_mode], 1
    mov dword [cfg_player], 0
    mov dword [cfg_port], 7777
    cmp byte [sv_t_port], 0
    je .port_ok
    lea rcx, [sv_t_port]
    call a2i
    mov [cfg_port], eax
.port_ok:
    mov eax, [cfg_port]
    mov [cfg_local], eax
    mov byte [a_host], 0
    lea rcx, [a_pass]
    lea rdx, [sv_t_pass]
    call str_copy
    lea rcx, [a_room]
    lea rdx, [sv_t_room]
    cmp byte [sv_t_room], 0
    jne .room
    lea rdx, [room_default]
.room:
    call str_copy
    cmp dword [sv_helper_ok], 0
    mov ecx, ST_ERROR
    mov edx, ER_NOHELPER
    je .fail
    lea rcx, [epoch_a]
    call guid_hex
    call prepare_bridge
    call write_auth
    test eax, eax
    jnz .authok
    cmp byte [a_pass], 0                ; without a password the helper still works (its keys stay in memory)
    mov ecx, ST_ERROR
    mov edx, ER_BADPASS
    jne .fail
.authok:
    mov ecx, 1
    call write_control
    mov ecx, ST_ERROR
    mov edx, ER_CONTROL
    test eax, eax
    jz .fail
    call start_helper
    mov ecx, ST_ERROR
    mov edx, ER_HELPERFAIL
    test eax, eax
    jz .fail
    call disc_start
    call sv_collect_addrs
    mov dword [sv_session], 1
    mov ecx, ST_HOSTING
    xor edx, edx
    call sv_set
    jmp .d
.fail:
    mov r14d, ecx
    mov r15d, edx
    call sess_stop
    mov ecx, r14d
    mov edx, r15d
    call sv_set
.d:
END_FN

; Joining: sv_t_host, sv_t_port, sv_t_pass and sv_t_room were validated by the caller.
FN sv_join
    call sess_stop
    mov dword [cfg_mode], 2
    mov dword [cfg_port], 7777
    cmp byte [sv_t_port], 0
    je .port_ok
    lea rcx, [sv_t_port]
    call a2i
    mov [cfg_port], eax
.port_ok:
    lea rcx, [a_host]
    lea rdx, [sv_t_host]
    call str_copy
    lea rcx, [a_pass]
    lea rdx, [sv_t_pass]
    call str_copy
    lea rcx, [a_room]
    lea rdx, [sv_t_room]
    cmp byte [sv_t_room], 0
    jne .room
    lea rdx, [room_default]
.room:
    call str_copy
    ; a player number 1..7 that differs from the last attempt (a taken number is reported by the host as "busy")
    lea rcx, [sv_tmp]
    call guid_hex
    movzx eax, byte [guid]
    xor edx, edx
    mov ecx, 7
    div ecx
    inc edx
    cmp edx, [sv_prev_slot]
    jne .slot
    mov eax, edx
    xor edx, edx
    mov ecx, 7
    div ecx
    inc edx
.slot:
    mov [cfg_player], edx
    mov [sv_prev_slot], edx
    mov eax, [cfg_port]
    add eax, edx
    mov [cfg_local], eax
    mov ecx, ST_ERROR
    mov edx, ER_BADADDR
    cmp eax, 65535
    ja .fail
    cmp dword [sv_helper_ok], 0
    mov ecx, ST_ERROR
    mov edx, ER_NOHELPER
    je .fail
    lea rcx, [epoch_a]
    call guid_hex
    call prepare_bridge
    call write_auth
    test eax, eax
    jnz .authok
    cmp byte [a_pass], 0
    mov ecx, ST_ERROR
    mov edx, ER_BADPASS
    jne .fail
.authok:
    mov ecx, 1
    call write_control
    mov ecx, ST_ERROR
    mov edx, ER_CONTROL
    test eax, eax
    jz .fail
    call start_helper
    mov ecx, ST_ERROR
    mov edx, ER_HELPERFAIL
    test eax, eax
    jz .fail
    mov dword [sv_session], 2
    mov dword [sv_phase], 1
    call ticks_ms
    add rax, 12000
    mov [sv_deadline], rax
    mov ecx, ST_JOINING
    xor edx, edx
    call sv_set
    jmp .d
.fail:
    mov r14d, ecx
    mov r15d, edx
    call sess_stop
    mov ecx, r14d
    mov edx, r15d
    call sv_set
.d:
END_FN

; Number after the needle (rcx = needle) in the helper's status text read into file_buf (r12 bytes) -> eax, or -1 if absent
FN sv_json_num
    mov r13, rcx
    call str_len
    mov r9d, eax
    lea rcx, [file_buf]
    mov rdx, r12
    mov r8, r13
    call find_bytes
    test rax, rax
    jz .none
    mov r9d, r9d
    mov rcx, r13
    mov r14, rax
    call str_len
    add r14, rax
    xor eax, eax
    xor edx, edx
.dig:
    movzx ecx, byte [r14+rdx]
    sub ecx, '0'
    cmp ecx, 9
    ja .end
    imul eax, eax, 10
    add eax, ecx
    inc edx
    cmp edx, 6
    jb .dig
.end:
    test edx, edx
    jnz .d
.none:
    mov eax, -1
.d:
END_FN

; Once the helper reports the host's WELCOME the world is downloaded (or the join fails with the reason).
FN sv_join_step
    cmp dword [sv_phase], 1
    jne .d
    lea rcx, [p1]
    lea rdx, [bridge_dir]
    lea r8, [s_statusfile]
    call path2
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 1000
    call read_file
    mov r12, rax
    cmp rax, 10
    jl .wait
    lea rax, [file_buf]
    mov byte [rax+r12], 0
    lea rcx, [f_auth]
    call sv_json_num
    cmp eax, 2
    je .welcomed
    lea rcx, [f_reject]
    call sv_json_num
    test eax, eax
    jle .wait
    add eax, ER_REJ_BASE
    mov r13d, eax
    call sess_stop
    mov ecx, ST_ERROR
    mov edx, r13d
    call sv_set
    jmp .d
.wait:
    call ticks_ms
    cmp rax, [sv_deadline]
    jb .d
    call sess_stop
    mov ecx, ST_ERROR
    mov edx, ER_NOANSWER
    call sv_set
    jmp .d
.welcomed:
    mov dword [sv_phase], 2
    mov ecx, ST_DOWNLOAD
    xor edx, edx
    call sv_set
    lea rcx, [a_host]
    call ip_parse
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [data_dir]
    lea r8, [s_mp_saves]
    call path2
    mov dword [wf_connect_ms], 3000
    lea rcx, [bridge_dir]
    mov edx, [cfg_player]
    call world_use_session              ; the helper wrote this session's key before it reported the WELCOME
    mov ecx, r12d
    lea rdx, [p1]
    call world_fetch
    mov r12d, eax
    test eax, eax
    jnz .worldfail
    mov dword [sv_phase], 0
    mov ecx, ST_READY
    xor edx, edx
    call sv_set
    jmp .d
.worldfail:
    call sess_stop
    add r12d, ER_WORLD_BASE
    mov ecx, ST_ERROR
    mov edx, r12d
    call sv_set
.d:
END_FN

FN sv_scan_now
    mov ecx, ST_SCANNING
    xor edx, edx
    call sv_set
    call mp_scan
    inc dword [sv_scan]
    mov ecx, ST_IDLE
    cmp dword [sv_session], 1
    jne .set
    mov ecx, ST_HOSTING
.set:
    xor edx, edx
    call sv_set
END_FN

; ---------------- commands ----------------
; Reads and deletes cmd.txt. eax: 0 nothing new, 1 host, 2 join, 3 scan, 4 stop, 9 anything else (answered, not acted on).
FN sv_read_cmd
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_menucmd]
    call path2
    lea rcx, [p1]
    call path_kind
    cmp eax, 1
    jne .none
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 1000
    call read_file
    mov r12, rax
    lea rcx, [p1]
    call sys_unlink                     ; consumed: a password never stays on disk
    test r12, r12
    jle .none
    mov [cfg_len], r12
    lea rax, [file_buf]
    mov byte [rax+r12], 0
    lea rcx, [k_seq]
    lea rdx, [sv_t_seq]
    mov r8d, 16
    call cfg_get
    lea rcx, [sv_t_seq]
    call a2i
    cmp eax, 1
    jl .none
    cmp eax, [sv_seq]
    je .none
    mov [sv_seq], eax
    lea rcx, [k_cmd]
    lea rdx, [sv_t_cmd]
    mov r8d, 16
    call cfg_get
    lea rcx, [k_host]
    lea rdx, [sv_t_host]
    mov r8d, 32
    call cfg_get
    lea rcx, [k_port]
    lea rdx, [sv_t_port]
    mov r8d, 16
    call cfg_get
    lea rcx, [k_pass]
    lea rdx, [sv_t_pass]
    mov r8d, 72
    call cfg_get
    lea rcx, [k_room]
    lea rdx, [sv_t_room]
    mov r8d, 16
    call cfg_get
    mov eax, 9
    lea rcx, [sv_t_cmd]
    lea rdx, [h_host]
    call a_equal
    mov edx, 1
    test eax, eax
    jnz .got
    lea rcx, [sv_t_cmd]
    lea rdx, [h_join]
    call a_equal
    mov edx, 2
    test eax, eax
    jnz .got
    lea rcx, [sv_t_cmd]
    lea rdx, [c_scan]
    call a_equal
    mov edx, 3
    test eax, eax
    jnz .got
    lea rcx, [sv_t_cmd]
    lea rdx, [c_stop]
    call a_equal
    mov edx, 4
    test eax, eax
    jnz .got
    mov edx, 9
.got:
    mov eax, edx
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

; eax 1 if sv_t_port is empty or a number 1..65535 and sv_t_pass / sv_t_room are acceptable (room empty or 8 hex digits)
FN sv_valid_common
    cmp byte [sv_t_port], 0
    je .pass
    lea rcx, [sv_t_port]
    call a2i
    cmp eax, 1
    jl .no
    cmp eax, 65535
    jg .no
.pass:
    lea rcx, [sv_t_pass]
    call v_pass
    test eax, eax
    jz .no
    cmp byte [sv_t_room], 0
    je .yes
    lea rcx, [sv_t_room]
    call v_room
    test eax, eax
    jz .no
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN sv_poll
    call sv_read_cmd
    test eax, eax
    jz .step
    mov [sv_cmd], eax
    cmp eax, 1
    je .host
    cmp eax, 2
    je .join
    cmp eax, 3
    je .scan
    cmp eax, 4
    je .stop
    call sv_status_write                ; unknown command: only the answer (seq) changes
    jmp .step
.host:
    call sv_valid_common
    test eax, eax
    jnz .host_ok
    mov ecx, ST_ERROR
    mov edx, ER_BADADDR
    call sv_set
    jmp .step
.host_ok:
    call sv_host
    jmp .step
.join:
    lea rcx, [sv_t_host]
    call v_ipv4
    test eax, eax
    jz .join_bad
    call sv_valid_common
    test eax, eax
    jnz .join_ok
.join_bad:
    call sess_stop
    mov ecx, ST_ERROR
    mov edx, ER_BADADDR
    call sv_set
    jmp .step
.join_ok:
    call sv_join
    jmp .step
.scan:
    call sv_scan_now
    jmp .step
.stop:
    call sess_stop
    mov ecx, ST_IDLE
    xor edx, edx
    call sv_set
.step:
    call sv_join_step
    call sv_status_tick
END_FN

; Folder, stale command, counters and the helper check: shared by standby and the optional launcher.cfg start.
FN menu_prepare
    mov dword [sv_seq], 0
    mov dword [sv_scan], 0
    mov dword [sv_session], 0
    mov dword [sv_phase], 0
    mov dword [sv_addr_count], 0
    mov dword [mp_host_count], 0
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_menudir]
    call path2
    lea rcx, [p1]
    call ensure_dirs
    lea rcx, [p1]
    lea rdx, [mod_dir]
    lea r8, [n_menucmd]
    call path2
    lea rcx, [p1]
    call sys_unlink                     ; a command left over from an earlier run must not be applied
    lea rcx, [p1]
    lea rdx, [exe_dir]
    lea r8, [n_helper]
    call path2
    lea rcx, [p1]
    mov edx, 1                          ; X_OK
    call sys_access
    xor ecx, ecx
    test rax, rax
    setz cl
    mov [sv_helper_ok], ecx
END_FN

; Standby start (no launcher.cfg): safe defaults, control.json (enabled:false, mode idle) and the first status.
; eax 1 ok, 0 if control.json could not be written.
FN menu_init
    mov dword [cfg_mode], 0
    mov dword [cfg_port], 7777
    mov dword [cfg_player], 0
    mov byte [a_host], 0
    mov byte [a_pass], 0
    lea rsi, [room_default]
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
    call menu_prepare
    xor ecx, ecx
    call write_control
    test eax, eax
    jz .d
    mov ecx, ST_IDLE
    xor edx, edx
    cmp dword [sv_helper_ok], 0
    jne .set
    mov ecx, ST_ERROR
    mov edx, ER_NOHELPER
.set:
    call sv_set
    mov eax, 1
.d:
END_FN
