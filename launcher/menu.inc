; In-game menu supervisor of the Windows launcher

ST_IDLE equ 0
ST_HOSTING equ 1
ST_JOINING equ 2
ST_DOWNLOAD equ 3
ST_READY equ 4
ST_ERROR equ 5
ST_SCANNING equ 6
ST_STOPPED equ 7
ER_NONE equ 0
ER_NOHELPER equ 1
ER_HELPERFAIL equ 2
ER_BADADDR equ 3
ER_NOANSWER equ 4
ER_BADPASS equ 5
ER_CONTROL equ 6
ER_NOSCAN equ 7
ER_REJ_BASE equ 20
ER_WORLD_BASE equ 40

extern GetTickCount64, GetSystemTimeAsFileTime, ExpandEnvironmentStringsW

section .data
WSTR n_menudir, "\menu\x"
WSTR n_menucmd, "\menu\cmd.txt"
WSTR n_menustat, "\menu\status.json"
WSTR n_menutmp, "\menu\status.tmp"
WSTR n_menuworld, "\menu\world.txt"
WSTR n_scanfile, "\menu\scan.txt"
WSTR n_addrfile, "\menu\addrs.txt"
WSTR n_manager, "MistriMulti.exe"
WSTR f_mgrcmd, `"%s\\MistriMulti.exe" %s "%s"`
WSTR s_optscan, "--scan"
WSTR s_optaddrs, "--addrs"
WSTR s_optupdate, "--update"
WSTR n_updcfg, "\update.cfg"
WSTR n_updchk, "\update_check.txt"
WSTR n_updres, "\menu\update.txt"
WSTR n_chkdl, "\menu\latest.dl"
WSTR n_updtmp, "\update_check.tmp"
WSTR s_manifest_rel, "\mods\mistrimulti\manifest.toml"
WSTR s_curl_path, "%SystemRoot%\System32\curl.exe"
WSTR e_relurl, "MISTRIMULTI_RELEASE_URL"
WSTR e_uplimit, "MISTRIMULTI_UPDATE_TIMEOUT_MS"
WSTR s_rel_url, "https://github.com/tomrocksyou/MistriaMulti/releases/latest/download/latest.txt"
WSTR f_curlcmd, `"%s" -fsSL --max-time 5 --connect-timeout 3 --max-filesize 65536 --proto =https --proto-redir =https -o "%s" "%s"`
WSTR f_curlcmd_o, `"%s" -fsSL --max-time 5 --connect-timeout 3 --max-filesize 65536 -o "%s" "%s"`
k_seq db 4,'seq='
k_cmd db 4,'cmd='
c_scan db 'scan',0
c_stop db 'stop',0
c_update db 'update',0
c_ucancel db 'update_cancel',0
j_pct_s db '%s',0
f_auth db '"auth":',0
f_reject db '"reject":',0
j_m1 db '{"v":1,"hb":%d,"seq":%d,"state":"%s","err":%d,"session":"%s","helper":%d,"scan":%d,"port":%d,"hw":%d,"hf":%d,"dw":%d',0
j_m9 db ',"addrs":[',0
j_addr db '%s"%d.%d.%d.%d"',0
j_m10 db '],"hosts":[',0
j_host db '%s{"ip":"%d.%d.%d.%d","port":%d,"flags":%d,"name":"%s"}',0
j_m11 db ']}',0
j_empty db 0
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
r_standby db 'MistriaMulti: no launcher.cfg is needed. Waiting for Host or Join in the in-game Multiplayer menu.',13,10,0
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
up_proc resq 1
ck_proc resq 1
up_wres resw 1040
ck_wout resw 1040
ck_wcurl resw 1040
ck_wurl resw 520
up_ft resq 1
up_wnum resw 16
sv_deadline resq 1
sv_last_write resq 1
sv_addr_count resd 1
sv_addrs resd 10
sv_hcount resd 1
sv_hip resd 16
sv_hport resd 16
sv_hflags resd 16
sv_hname resb 16*32
sv_t_seq resb 16
sv_t_cmd resb 16
sv_t_host resb 32
sv_t_port resb 16
sv_t_pass resb 72
sv_t_room resb 16
sv_tmp resb 48
sv_json resb 4096
sv_hw resd 1
sv_hf resd 1
sv_dw resd 1
wh_id resd 1
wh_found resd 1
wh_buf resb 64
wh_disc_bits resd 1
wh_disc_at resq 1

section .text
FN sv_status_write
    lea r12, [sv_json]
    call GetTickCount64
    and eax, 0x7fffffff
    mov r8d, eax
    mov rcx, r12
    lea rdx, [j_m1]
    mov r9d, [sv_seq]
    mov eax, [sv_state]
    lea r10, [sv_state_names]
    mov rax, [r10+rax*8]
    mov [rsp+32], rax
    mov eax, [sv_err]
    mov [rsp+40], rax
    mov eax, [sv_session]
    lea r10, [sv_session_names]
    mov rax, [r10+rax*8]
    mov [rsp+48], rax
    mov eax, [sv_helper_ok]
    mov [rsp+56], rax
    mov eax, [sv_scan]
    mov [rsp+64], rax
    mov eax, [cfg_port]
    mov [rsp+72], rax
    mov eax, [sv_hw]
    mov [rsp+80], rax
    mov eax, [sv_hf]
    mov [rsp+88], rax
    mov eax, [sv_dw]
    mov [rsp+96], rax
    call wsprintfA
    add r12, rax
    call up_json_make
    mov rcx, r12
    lea rdx, [j_pct_s]
    lea r8, [up_json]
    call wsprintfA
    add r12, rax
    mov rcx, r12
    lea rdx, [j_m9]
    call wsprintfA
    add r12, rax
    xor r13d, r13d
.addr:
    cmp r13d, [sv_addr_count]
    jae .addrs_done
    mov rcx, r12
    lea rdx, [j_addr]
    lea r8, [j_empty]
    test r13d, r13d
    jz .a1
    lea r8, [j_comma]
.a1:
    lea rax, [sv_addrs]
    mov eax, [rax+r13*4]
    mov r14d, eax
    movzx r9d, al
    mov r10d, r14d
    shr r10d, 8
    and r10d, 255
    mov r11d, r14d
    shr r11d, 16
    and r11d, 255
    shr r14d, 24
    mov [rsp+32], r10
    mov [rsp+40], r11
    mov [rsp+48], r14
    call wsprintfA
    add r12, rax
    inc r13d
    jmp .addr
.addrs_done:
    mov rcx, r12
    lea rdx, [j_m10]
    call wsprintfA
    add r12, rax
    xor r13d, r13d
.host:
    cmp r13d, [sv_hcount]
    jae .hosts_done
    cmp r13d, 12
    jae .hosts_done
    mov rcx, r12
    lea rdx, [j_host]
    lea r8, [j_empty]
    test r13d, r13d
    jz .h1
    lea r8, [j_comma]
.h1:
    lea rax, [sv_hip]
    mov eax, [rax+r13*4]
    mov r14d, eax
    movzx r9d, al
    mov r10d, r14d
    shr r10d, 8
    and r10d, 255
    mov r11d, r14d
    shr r11d, 16
    and r11d, 255
    shr r14d, 24
    mov [rsp+32], r10
    mov [rsp+40], r11
    mov [rsp+48], r14
    lea rax, [sv_hport]
    mov eax, [rax+r13*4]
    mov [rsp+56], rax
    lea rax, [sv_hflags]
    mov eax, [rax+r13*4]
    mov [rsp+64], rax
    mov eax, r13d
    shl eax, 5
    lea r10, [sv_hname]
    add rax, r10
    mov [rsp+72], rax
    call wsprintfA
    add r12, rax
    inc r13d
    jmp .host
.hosts_done:
    mov rcx, r12
    lea rdx, [j_m11]
    call wsprintfA
    add r12, rax
    lea rax, [sv_json]
    sub r12, rax
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menutmp]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [sv_json]
    mov r8, r12
    call write_file
    test eax, eax
    jz .d
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menustat]
    call wsprintfW
    lea rcx, [p2]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menutmp]
    call wsprintfW
    lea rcx, [p2]
    lea rdx, [p1]
    mov r8d, 1
    call MoveFileExW
    call GetTickCount64
    mov [sv_last_write], rax
.d:
END_FN

FN sv_set
    mov [sv_state], ecx
    mov [sv_err], edx
    call sv_status_write
END_FN

FN sv_status_tick
    call GetTickCount64
    sub rax, [sv_last_write]
    cmp rax, 1000
    jb .d
    call sv_status_write
.d:
END_FN

FN disc_stop
    mov rcx, [disc_sock]
    test rcx, rcx
    jz .t
    call closesocket
    mov qword [disc_sock], 0
.t: mov rcx, [tcp_sock]
    test rcx, rcx
    jz .d
    call closesocket
    mov qword [tcp_sock], 0
.d:
END_FN

FN wh_forget
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menuworld]
    call wsprintfW
    lea rcx, [p1]
    call DeleteFileW
    mov dword [wh_id], 0
    mov dword [wh_disc_bits], 0
    mov qword [wh_disc_at], 0
END_FN

FN sv_world_clear
    mov dword [sv_hw], 0
    mov dword [sv_hf], 0
    mov dword [sv_dw], 0
END_FN

FN wh_load
    mov dword [wh_id], 0
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menuworld]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [wh_buf]
    mov r8d, 40
    call read_file
    test rax, rax
    jle .d
    lea rcx, [wh_buf]
    mov byte [rcx+rax], 0
    call wf_parse_world
    mov [wh_id], eax
.d:
END_FN

FN wh_state
    call wh_load
    call world_find_newest
    mov [wh_found], eax
END_FN

FN wh_fill_hdr
    mov eax, [wh_id]
    test eax, eax
    jz .d
    mov [wf_hdr+44], eax
    mov al, 1
    cmp dword [wh_found], 0
    je .set
    or al, 2
.set:
    mov [wf_hdr+6], al
.d:
END_FN

FN wh_disc_flags
    call GetTickCount64
    mov rcx, rax
    sub rcx, [wh_disc_at]
    cmp rcx, 1000
    jb .have
    mov [wh_disc_at], rax
    call wh_state
    xor eax, eax
    cmp dword [wh_id], 0
    je .store
    mov eax, 4
    cmp dword [wh_found], 0
    je .store
    or eax, 8
.store:
    mov [wh_disc_bits], eax
.have:
    movzx eax, byte [disc_resp+5]
    and eax, 3
    or eax, [wh_disc_bits]
    mov [disc_resp+5], al
END_FN

FN sess_stop
    call wh_forget
    call stop_helper
    call disc_stop
    mov dword [cfg_mode], 0
    xor ecx, ecx
    call write_control
    mov dword [sv_phase], 0
    mov dword [sv_session], 0
    mov dword [sv_addr_count], 0
END_FN

FN sv_run_manager
    mov r12, rcx
    mov r13, rdx
    mov r14d, r8d
    lea rcx, [p3]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    mov r9, r13
    call wsprintfW
    lea rcx, [p3]
    call DeleteFileW
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [exe_dir]
    lea r9, [n_manager]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    test eax, eax
    jz .no
    lea rcx, [cmd_buf]
    lea rdx, [f_mgrcmd]
    lea r8, [exe_dir]
    mov r9, r12
    lea rax, [p3]
    mov [rsp+32], rax
    call wsprintfW
    lea rcx, [cmd_buf]
    lea rdx, [exe_dir]
    xor r8d, r8d
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .no
    mov rbx, rax
    mov rcx, rbx
    mov edx, r14d
    call WaitForSingleObject
    mov r12d, eax
    test eax, eax
    jz .closeit
    mov rcx, rbx
    mov edx, 1
    call TerminateProcess
.closeit:
    mov rcx, rbx
    call CloseHandle
    test r12d, r12d
    jnz .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN sv_collect_addrs
    mov dword [sv_addr_count], 0
    lea rcx, [s_optaddrs]
    lea rdx, [n_addrfile]
    mov r8d, 8000
    call sv_run_manager
    test eax, eax
    jz .d
    lea rcx, [p3]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    mov r13, rax
    cmp rax, 7
    jl .d
    lea rax, [file_buf]
    mov byte [rax+r13], 0
    xor r12d, r12d
.line:
    cmp r12, r13
    jae .d
    cmp dword [sv_addr_count], 8
    jae .d
    lea rsi, [file_buf]
    add rsi, r12
    lea rdi, [sv_t_host]
    xor ecx, ecx
.cp:
    movzx eax, byte [rsi+rcx]
    cmp al, 33
    jb .endtok
    cmp ecx, 30
    jae .endtok
    mov [rdi+rcx], al
    inc ecx
    jmp .cp
.endtok:
    mov byte [rdi+rcx], 0
    add r12, rcx
.skipnl:
    cmp r12, r13
    jae .check
    lea rsi, [file_buf]
    movzx eax, byte [rsi+r12]
    inc r12
    cmp al, 10
    jne .skipnl
.check:
    lea rcx, [sv_t_host]
    call v_ipv4
    test eax, eax
    jz .line
    lea rcx, [sv_t_host]
    call inet_addr
    mov edx, [sv_addr_count]
    lea rcx, [sv_addrs]
    mov [rcx+rdx*4], eax
    inc dword [sv_addr_count]
    jmp .line
.d:
END_FN

FN sv_host
    call sess_stop
    call sv_world_clear
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
    mov word [w_host], 0
    lea rsi, [sv_t_pass]
    lea rdi, [a_pass]
    mov ecx, 72
    rep movsb
    lea rsi, [sv_t_room]
    cmp byte [sv_t_room], 0
    jne .room
    lea rsi, [room_default]
.room:
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
    lea rcx, [w_room]
    lea rdx, [a_room]
    mov r8d, 8
    call ascii_to_wide
    mov ecx, ST_ERROR
    mov edx, ER_NOHELPER
    cmp dword [sv_helper_ok], 0
    je .fail
    lea rcx, [epoch_a]
    call guid_hex
    call prepare_bridge
    call write_auth
    test eax, eax
    jnz .authok
    mov ecx, ST_ERROR
    mov edx, ER_BADPASS
    cmp byte [a_pass], 0
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

FN sv_join
    call sess_stop
    call sv_world_clear
    mov dword [cfg_mode], 2
    mov dword [cfg_port], 7777
    cmp byte [sv_t_port], 0
    je .port_ok
    lea rcx, [sv_t_port]
    call a2i
    mov [cfg_port], eax
.port_ok:
    lea rsi, [sv_t_host]
    lea rdi, [a_host]
    mov ecx, 32
    rep movsb
    lea rsi, [sv_t_pass]
    lea rdi, [a_pass]
    mov ecx, 72
    rep movsb
    lea rsi, [sv_t_room]
    cmp byte [sv_t_room], 0
    jne .room
    lea rsi, [room_default]
.room:
    lea rdi, [a_room]
    mov ecx, 9
    rep movsb
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
    mov ecx, ST_ERROR
    mov edx, ER_NOHELPER
    cmp dword [sv_helper_ok], 0
    je .fail
    lea rcx, [epoch_a]
    call guid_hex
    call prepare_bridge
    call write_auth
    test eax, eax
    jnz .authok
    mov ecx, ST_ERROR
    mov edx, ER_BADPASS
    cmp byte [a_pass], 0
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
    call GetTickCount64
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

FN sv_json_num
    mov r13, rcx
    call lstrlenA
    mov r9d, eax
    lea rcx, [file_buf]
    mov rdx, r12
    mov r8, r13
    call find_bytes
    test rax, rax
    jz .none
    mov r14, rax
    mov rcx, r13
    call lstrlenA
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

FN sv_join_step
    cmp dword [sv_phase], 1
    jne .d
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [bridge_dir]
    lea r9, [n_status]
    call wsprintfW
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
    call GetTickCount64
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
    call inet_addr
    mov r12d, eax
    lea rcx, [p1]
    lea rdx, [f_mpsaves_dir]
    lea r8, [local_app]
    call wsprintfW
    mov dword [wf_connect_ms], 3000
    lea rcx, [bridge_dir]
    mov edx, [cfg_player]
    call world_use_session
    mov ecx, r12d
    lea rdx, [p1]
    call world_fetch
    mov r12d, eax
    mov eax, [wf_host_id]
    mov [sv_hw], eax
    mov eax, [wf_host_flags]
    mov [sv_hf], eax
    mov eax, [wf_got_id]
    mov [sv_dw], eax
    test r12d, r12d
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

FN sv_tok
    xor r10d, r10d
    dec r9
.l: cmp rcx, rdx
    jae .e
    movzx eax, byte [rcx]
    cmp al, ' '
    je .sp
    cmp al, 13
    je .e
    cmp al, 10
    je .e
    cmp r10, r9
    jae .adv
    mov [r8+r10], al
    inc r10
.adv:
    inc rcx
    jmp .l
.sp:
    inc rcx
.e: mov byte [r8+r10], 0
    mov rax, rcx
END_FN

FN sv_parse_scan
    mov dword [sv_hcount], 0
    lea rcx, [p3]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    mov r13, rax
    cmp rax, 8
    jl .d
    lea rax, [file_buf]
    mov byte [rax+r13], 0
    lea r13, [rax+r13]
    lea r12, [file_buf]
.line:
    cmp r12, r13
    jae .d
    cmp dword [sv_hcount], 16
    jae .d
    mov rcx, r12
    mov rdx, r13
    lea r8, [sv_t_host]
    mov r9d, 32
    call sv_tok
    mov r12, rax
    mov rcx, r12
    mov rdx, r13
    lea r8, [sv_t_port]
    mov r9d, 16
    call sv_tok
    mov r12, rax
    mov rcx, r12
    mov rdx, r13
    lea r8, [sv_t_seq]
    mov r9d, 16
    call sv_tok
    mov r12, rax
    lea rcx, [sv_t_host]
    call v_ipv4
    test eax, eax
    jz .skip
    lea rcx, [sv_t_port]
    call a2i
    cmp eax, 1
    jl .skip
    cmp eax, 65535
    jg .skip
    mov r14d, eax
    lea rcx, [sv_t_seq]
    call a2i
    cmp eax, 0
    jl .skip
    cmp eax, 255
    jg .skip
    mov r15d, eax
    mov ebx, [sv_hcount]
    lea rcx, [sv_t_host]
    call inet_addr
    lea rcx, [sv_hip]
    mov [rcx+rbx*4], eax
    lea rcx, [sv_hport]
    mov [rcx+rbx*4], r14d
    lea rcx, [sv_hflags]
    mov [rcx+rbx*4], r15d
    mov eax, ebx
    shl eax, 5
    lea rdi, [sv_hname]
    add rdi, rax
    xor ecx, ecx
.nm:
    cmp r12, r13
    jae .nmend
    movzx eax, byte [r12]
    cmp al, 13
    je .nmend
    cmp al, 10
    je .nmend
    inc r12
    cmp ecx, 31
    jae .nm
    cmp al, 32
    jb .bad
    cmp al, 126
    ja .bad
    cmp al, '"'
    je .bad
    cmp al, '\'
    jne .store
.bad:
    mov al, '_'
.store:
    mov [rdi+rcx], al
    inc ecx
    jmp .nm
.nmend:
    mov byte [rdi+rcx], 0
    inc dword [sv_hcount]
.skip:
.nl:
    cmp r12, r13
    jae .line
    movzx eax, byte [r12]
    inc r12
    cmp al, 10
    jne .nl
    jmp .line
.d:
END_FN

FN sv_scan_now
    mov ecx, ST_SCANNING
    xor edx, edx
    call sv_set
    mov dword [sv_hcount], 0
    lea rcx, [s_optscan]
    lea rdx, [n_scanfile]
    mov r8d, 12000
    call sv_run_manager
    mov r12d, eax
    test eax, eax
    jz .failed
    call sv_parse_scan
    inc dword [sv_scan]
    mov ecx, ST_IDLE
    cmp dword [sv_session], 1
    jne .set
    mov ecx, ST_HOSTING
.set:
    xor edx, edx
    call sv_set
    jmp .d
.failed:
    inc dword [sv_scan]
    mov ecx, ST_ERROR
    mov edx, ER_NOSCAN
    call sv_set
.d:
END_FN

FN sv_read_cmd
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menucmd]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    test eax, eax
    jz .none
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 1000
    call read_file
    mov r12, rax
    test r12, r12
    jle .none
    lea rcx, [p1]
    call DeleteFileW
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
    lea rcx, [sv_t_cmd]
    lea rdx, [a_host_s]
    call a_equal
    mov edx, 1
    test eax, eax
    jnz .got
    lea rcx, [sv_t_cmd]
    lea rdx, [a_join_s]
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
    lea rcx, [sv_t_cmd]
    lea rdx, [c_update]
    call a_equal
    mov edx, 5
    test eax, eax
    jnz .got
    lea rcx, [sv_t_cmd]
    lea rdx, [c_ucancel]
    call a_equal
    mov edx, 6
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
    cmp eax, 5
    je .update
    cmp eax, 6
    je .ucancel
    call sv_status_write
    jmp .step
.update:
    call up_cmd_update
    jmp .step
.ucancel:
    call up_cmd_cancel
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
    call sv_world_clear
    mov ecx, ST_IDLE
    xor edx, edx
    call sv_set
.step:
    call sv_join_step
    call up_step
    call chk_step
    call sv_status_tick
END_FN

FN menu_prepare
    mov dword [sv_seq], 0
    mov dword [sv_scan], 0
    mov dword [sv_session], 0
    mov dword [sv_phase], 0
    mov dword [sv_addr_count], 0
    mov dword [sv_hcount], 0
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menudir]
    call wsprintfW
    lea rcx, [p1]
    call ensure_dirs
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_menucmd]
    call wsprintfW
    lea rcx, [p1]
    call DeleteFileW
    call sv_world_clear
    call wh_forget
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [exe_dir]
    lea r9, [n_helper]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    mov [sv_helper_ok], eax
END_FN

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

FN plat_ms
    call GetTickCount64
END_FN

FN plat_unix
    lea rcx, [up_ft]
    call GetSystemTimeAsFileTime
    mov rax, [up_ft]
    mov rcx, 116444736000000000
    sub rax, rcx
    jb .zero
    xor edx, edx
    mov rcx, 10000000
    div rcx
    jmp .d
.zero:
    xor eax, eax
.d:
END_FN

FN plat_load
    lea rcx, [p1]
    lea rdx, [file_buf]
    mov r8d, 8000
    call read_file
    test rax, rax
    jle .no
    mov [cfg_len], rax
    lea rcx, [file_buf]
    mov byte [rcx+rax], 0
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN plat_cfg_read
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_updcfg]
    call wsprintfW
    call plat_load
END_FN

FN plat_cache_read
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_updchk]
    call wsprintfW
    call plat_load
END_FN

FN plat_cache_write
    mov r12, rcx
    mov r13, rdx
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_updtmp]
    call wsprintfW
    lea rcx, [p1]
    mov rdx, r12
    mov r8, r13
    call write_file
    test eax, eax
    jz .d
    lea rcx, [p2]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_updchk]
    call wsprintfW
    lea rcx, [p1]
    lea rdx, [p2]
    mov r8d, 1
    call MoveFileExW
.d:
END_FN

FN plat_manifest_read
    cmp word [game_dir], 0
    je .no
    lea rcx, [p1]
    lea rdx, [f_cat]
    lea r8, [game_dir]
    lea r9, [s_manifest_rel]
    call wsprintfW
    call plat_load
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN plat_proc_poll
    mov r12, rcx
    test rcx, rcx
    jz .gone
    xor edx, edx
    call WaitForSingleObject
    test eax, eax
    jnz .running
    mov dword [up_ft], 1
    mov rcx, r12
    lea rdx, [up_ft]
    call GetExitCodeProcess
    mov eax, [up_ft]
    mov r13, rax
    mov rcx, r12
    call CloseHandle
    mov rax, r13
    jmp .d
.gone:
    mov eax, 1
    jmp .d
.running:
    mov rax, -1
.d:
END_FN

FN plat_proc_kill
    mov r12, rcx
    test rcx, rcx
    jz .d
    mov edx, 1
    call TerminateProcess
    mov rcx, r12
    mov edx, 2000
    call WaitForSingleObject
    mov rcx, r12
    call CloseHandle
.d:
END_FN

FN plat_up_limit
    lea rcx, [e_uplimit]
    lea rdx, [up_wnum]
    mov r8d, 8
    call GetEnvironmentVariableW
    test eax, eax
    jz .no
    cmp eax, 7
    ja .no
    lea rcx, [up_wnum]
    call w2i
    test eax, eax
    jnz .d
.no:
    xor eax, eax
.d:
END_FN

FN plat_up_prepare
    lea rcx, [up_wres]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_updres]
    call wsprintfW
    lea rcx, [up_wres]
    call DeleteFileW
END_FN

FN plat_up_start
    lea rcx, [p1]
    lea rdx, [f_slash]
    lea r8, [exe_dir]
    lea r9, [n_manager]
    call wsprintfW
    lea rcx, [p1]
    call file_exists
    test eax, eax
    jz .no
    lea rcx, [cmd_buf]
    lea rdx, [f_mgrcmd]
    lea r8, [exe_dir]
    lea r9, [s_optupdate]
    lea rax, [up_wres]
    mov [rsp+32], rax
    call wsprintfW
    lea rcx, [cmd_buf]
    lea rdx, [exe_dir]
    xor r8d, r8d
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .no
    mov [up_proc], rax
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN plat_up_poll
    mov rcx, [up_proc]
    call plat_proc_poll
END_FN

FN plat_up_kill
    mov rcx, [up_proc]
    call plat_proc_kill
    mov qword [up_proc], 0
END_FN

FN plat_up_read
    lea rcx, [up_wres]
    lea rdx, [p1]
    call wcopy
    call plat_load
END_FN

FN plat_chk_start
    lea rcx, [ck_wout]
    lea rdx, [f_cat]
    lea r8, [mod_dir]
    lea r9, [n_chkdl]
    call wsprintfW
    lea rcx, [ck_wout]
    call DeleteFileW
    lea rcx, [s_curl_path]
    lea rdx, [ck_wcurl]
    mov r8d, 1000
    call ExpandEnvironmentStringsW
    test eax, eax
    jz .no
    lea rcx, [ck_wcurl]
    call file_exists
    test eax, eax
    jz .no
    mov word [ck_wurl], 0
    lea rcx, [e_relurl]
    lea rdx, [ck_wurl]
    mov r8d, 500
    call GetEnvironmentVariableW
    test eax, eax
    jz .plain
    cmp eax, 490
    ja .plain
    lea rsi, [ck_wurl]
.q: movzx eax, word [rsi]
    test eax, eax
    jz .override
    cmp eax, '"'
    je .badurl
    add rsi, 2
    jmp .q
.badurl:
    mov word [ck_wurl], 0
.plain:
    lea rcx, [cmd_buf]
    lea rdx, [f_curlcmd]
    lea r8, [ck_wcurl]
    lea r9, [ck_wout]
    lea rax, [s_rel_url]
    mov [rsp+32], rax
    call wsprintfW
    jmp .go
.override:
    lea rcx, [cmd_buf]
    lea rdx, [f_curlcmd_o]
    lea r8, [ck_wcurl]
    lea r9, [ck_wout]
    lea rax, [ck_wurl]
    mov [rsp+32], rax
    call wsprintfW
.go:
    lea rcx, [cmd_buf]
    xor edx, edx
    xor r8d, r8d
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .no
    mov [ck_proc], rax
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN plat_chk_poll
    mov rcx, [ck_proc]
    call plat_proc_poll
END_FN

FN plat_chk_kill
    mov rcx, [ck_proc]
    call plat_proc_kill
    mov qword [ck_proc], 0
END_FN

FN plat_chk_read
    lea rcx, [ck_wout]
    lea rdx, [p1]
    call wcopy
    call plat_load
END_FN

FN plat_chk_clean
    lea rcx, [ck_wout]
    call DeleteFileW
END_FN

%include "updatecore.inc"
