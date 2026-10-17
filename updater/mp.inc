; Multiplayer part of the manager window

extern WSAStartup, socket, setsockopt, WSAPoll, recvfrom, sendto, closesocket, inet_addr
extern GetAdaptersInfo, GetTickCount64, GetWindowTextW, MessageBoxW, DestroyWindow, SetFocus
extern wsprintfA, lstrlenA, CoCreateGuid, UpdateWindow, GetModuleFileNameW
extern GetTempPathW, WaitForSingleObject, TerminateProcess, DeleteFileW, GetEnvironmentVariableW, EnableWindow

section .data
WSTR mp_join_class, "MistriMultiJoin"
WSTR mp_join_title, "Join a game"
WSTR mp_edit, "EDIT"
WSTR mp_listbox, "LISTBOX"
WSTR mp_t_hosts, "Hosts found on your network and on Tailscale:"
WSTR mp_t_refresh, "Refresh"
WSTR mp_t_joinsel, "Join selected"
WSTR mp_t_orip, "Or type the host's IP address:"
WSTR mp_t_joinip, "Join this IP"
WSTR mp_t_player, "Your player number (1-7):"
WSTR mp_t_room, "Room code (only if your host has one):"
WSTR mp_t_pass, "Room password (only if your host has one):"
WSTR mp_s_badpass, "The password must be 1 to 64 letters, digits or punctuation, without spaces or accents."
WSTR mp_s_needpass, "This host uses a room password. Ask them for it and type it below."
WSTR mp_t_hostbtn, "Host a game"
WSTR mp_t_joinbtn, "Join a game..."
WSTR mp_t_steambtn, "Steam setup..."
WSTR mp_s_ready, "Press Refresh to look for hosts."
WSTR mp_s_scanning, "Looking for hosts..."
WSTR mp_s_none, "No host found. Make sure your friend is hosting, then Refresh (or type the IP below)."
WSTR mp_s_found, "Select a host and press Join selected."
WSTR mp_s_badip, "That is not a valid IPv4 address (like 100.101.102.103)."
WSTR mp_s_badplayer, "The player number must be 1 to 7."
WSTR mp_s_badroom, "The room code must be 8 characters, 0-9 and a-f (or empty)."
WSTR mp_s_needroom, "This host uses a room code. Ask them for it and type it below."
WSTR mp_s_pick, "Select a host in the list first."
WSTR mp_s_nosave, "Could not save the setup."
WSTR mp_m_title, "MistriaMulti"
mp_f_list_a db '%s   -   %s%s',0
WSTR mp_f_ip, "%d.%d.%d.%d"
WSTR mp_f_cfgpath, "%s\FieldsOfMistria\mod_data\mistrimulti\launcher.cfg"
WSTR mp_f_tsexe, "%s\Tailscale\tailscale.exe"
WSTR mp_f_tscmd, `"%s" status --json`
WSTR mp_f_tmp, "%smistrimulti-ts.tmp"
WSTR mp_f_launcher, `"%s\\MistriMultiLauncher.exe" --steam `
WSTR mp_e_local, "LOCALAPPDATA"
WSTR mp_e_pf, "ProgramFiles"
WSTR mp_e_extra, "MISTRIMULTI_SCAN_EXTRA"
WSTR mp_e_openjoin, "MISTRIMULTI_OPEN_JOIN"
WSTR mp_s_command, "%command%"
WSTR s_scan, "--scan"
WSTR s_addrs, "--addrs"
WSTR s_fetch, "--fetch"
mp_t_world_later: dw __utf16__(`\r\n\r\nThe host's world is downloaded when the game starts, after the host has accepted you (it needs the host's password if there is one). Start the game from Steam and choose Multiplayer on New Game.`), 0
WSTR s_join, "--join"
mp_f_hostmsg: dw __utf16__(`You are set to host.\r\n\r\nTell your friends one of these addresses; they pick yours in the Join window or type it:\r\n\r\n`), 0
mp_f_hostend: dw __utf16__(`\r\nThen start the game from Steam and choose Multiplayer on New Game or Load Game.`), 0
WSTR mp_t_tailscale, "Tailscale:   "
WSTR mp_t_lan, "This network: "
WSTR mp_t_empty_w, ""
WSTR mp_t_crlf, `\r\n`
mp_f_joinmsg: dw __utf16__(`Saved. Now start Fields of Mistria from Steam and choose Multiplayer on New Game or Load Game.\r\n\r\nJoining: `), 0
mp_f_steammsg: dw __utf16__(`The launch line has been copied to your clipboard.\r\n\r\nOne time only: in Steam, right-click Fields of Mistria > Properties > Launch Options, press Ctrl+V, and close the window.\r\n\r\nFrom then on just press Play in Steam. In the game choose New Game or Load Game, then Multiplayer, then Host a game or Join a game: you do not need this window to host or join.`), 0
mp_f_cfg_join db 'mode=join',13,10,'host=%s',13,10,'port=%d',13,10,'player=%d',13,10,'room=%s',13,10,0
mp_f_cfg_pass db 'password=%s',13,10,0
mp_f_cfg_host_pass db 'mode=host',13,10,'port=7777',13,10,'player=0',13,10,'room=',13,10,'password=%s',13,10,0
mp_k_pass db 'password='
mp_k_pass_len equ $ - mp_k_pass
mp_f_cfg_host db 'mode=host',13,10,'port=7777',13,10,'player=0',13,10,'room=',13,10,0
mp_k_player db 'player='
mp_k_player_len equ $ - mp_k_player
mp_f_ascii_entry db '%s %d %d %s',13,10,0
mp_f_ascii_ip db '%d.%d.%d.%d',0
mp_f_addr_line db '%s',13,10,0
mp_t_custom db '   [needs a room code]',0
mp_t_pw db '   [needs a password]',0
mp_t_both db '   [needs a room code and a password]',0
align 8
mp_t_flagtext dq mp_t_empty, mp_t_custom, mp_t_pw, mp_t_both
mp_t_empty db 0
mp_t_ts db '"100.'
mp_t_ts_len equ $ - mp_t_ts
align 8

section .bss
mp_wsa resb 408
mp_wsa_ready resd 1
mp_sock resq 1
mp_pfd resb 16
mp_sa resb 32
mp_from resb 32
mp_fromlen resd 1
mp_query resb 64
mp_rbuf resb 128
mp_adsize resd 1
mp_adbuf resb 16384
mp_local_ips resd 32
mp_local_count resd 1
mp_tgt resd 64
mp_tgt_count resd 1
mp_host_count resd 1
mp_host_ip resd 32
mp_host_port resw 32
mp_host_flags resb 32
mp_host_name resb 1024
mp_ts_self resd 1
mp_sa_inherit resb 24
mp_text resb 600
mp_ascii resb 64
mp_one resd 1
h_join resq 1
h_list resq 1
h_ed_ip resq 1
h_ed_player resq 1
h_ed_room resq 1
h_ed_pass resq 1
mp_pass resb 72
h_join_status resq 1
cur_parent resq 1
mp_guid resb 16
mp_big resw 1500
mp_msg resw 1400
mp_scan_flag resd 1
mp_dump_len resd 1

section .text

FN mp_add_target
    mov edx, [mp_tgt_count]
    cmp edx, 60
    jae .d
    xor eax, eax
    lea r8, [mp_tgt]
.l: cmp eax, edx
    jae .add
    cmp [r8+rax*4], ecx
    je .d
    inc eax
    jmp .l
.add:
    mov [r8+rdx*4], ecx
    inc dword [mp_tgt_count]
.d:
END_FN

FN mp_is_local
    xor eax, eax
    mov edx, [mp_local_count]
    lea r8, [mp_local_ips]
.l: cmp eax, edx
    jae .no
    cmp [r8+rax*4], ecx
    je .yes
    inc eax
    jmp .l
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN mp_collect_adapters
    mov dword [mp_local_count], 0
    mov dword [mp_adsize], 16384
    lea rcx, [mp_adbuf]
    lea rdx, [mp_adsize]
    call GetAdaptersInfo
    test eax, eax
    jnz .d
    lea rbx, [mp_adbuf]
.adapter:
    test rbx, rbx
    jz .d
    lea r12, [rbx+440]
.addr:
    test r12, r12
    jz .nextad
    lea rcx, [r12+8]
    call inet_addr
    test eax, eax
    jz .nextaddr
    cmp eax, -1
    je .nextaddr
    mov r13d, eax
    mov ecx, [mp_local_count]
    cmp ecx, 30
    jae .nolocal
    lea rdx, [mp_local_ips]
    mov [rdx+rcx*4], r13d
    inc dword [mp_local_count]
.nolocal:
    lea rcx, [r12+24]
    call inet_addr
    cmp eax, -1
    je .nextaddr
    not eax
    or eax, r13d
    mov ecx, eax
    call mp_add_target
.nextaddr:
    mov r12, [r12]
    jmp .addr
.nextad:
    mov rbx, [rbx]
    jmp .adapter
.d:
END_FN

FN mp_tailscale
    mov dword [mp_ts_self], 0
    lea rcx, [mp_e_pf]
    lea rdx, [wpath1]
    mov r8d, 400
    call GetEnvironmentVariableW
    test eax, eax
    jz .d
    cmp eax, 400
    ja .d
    lea rcx, [wpath2]
    lea rdx, [mp_f_tsexe]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    call file_exists
    test eax, eax
    jz .d
    mov ecx, 400
    lea rdx, [wpath3]
    call GetTempPathW
    test eax, eax
    jz .d
    lea rcx, [wurl]
    lea rdx, [mp_f_tmp]
    lea r8, [wpath3]
    call wsprintfW
    mov dword [mp_sa_inherit], 24
    mov qword [mp_sa_inherit+8], 0
    mov dword [mp_sa_inherit+16], 1
    lea rcx, [wurl]
    mov edx, 0x40000000
    mov r8d, 1
    lea r9, [mp_sa_inherit]
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .d
    mov r12, rax
    lea rcx, [mp_big]
    lea rdx, [mp_f_tscmd]
    lea r8, [wpath2]
    call wsprintfW
    lea rcx, [mp_big]
    xor edx, edx
    mov r8, r12
    mov r9d, 0x08000000
    call spawn
    test rax, rax
    jz .closefile
    mov r13, rax
    mov rcx, r13
    mov edx, 4000
    call WaitForSingleObject
    test eax, eax
    jz .waited
    mov rcx, r13
    mov edx, 1
    call TerminateProcess
.waited:
    mov rcx, r13
    call CloseHandle
.closefile:
    mov rcx, r12
    call CloseHandle
    lea rcx, [wurl]
    lea rdx, [http_buf]
    mov r8d, 250000
    call read_file
    mov r14, rax
    lea rcx, [wurl]
    call DeleteFileW
    cmp r14, 8
    jl .d
    lea rax, [http_buf]
    mov byte [rax+r14], 0
    xor r12d, r12d
.scan:
    mov rax, r14
    sub rax, 24
    cmp r12, rax
    jae .d
    lea rcx, [http_buf]
    add rcx, r12
    cmp byte [rcx], '"'
    jne .next
    cmp dword [rcx+1], '100.'
    jne .next
    lea rsi, [rcx+1]
    lea rdi, [mp_ascii]
    xor ecx, ecx
.cp:
    movzx eax, byte [rsi+rcx]
    cmp al, '.'
    je .ok
    lea edx, [rax-'0']
    cmp edx, 9
    ja .endtok
.ok:
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 16
    jb .cp
    jmp .next
.endtok:
    cmp al, '"'
    jne .next
    mov byte [rdi+rcx], 0
    lea rcx, [mp_ascii]
    call v_ipv4
    test eax, eax
    jz .next
    lea rcx, [mp_ascii]
    call inet_addr
    mov ecx, eax
    movzx edx, ah
    cmp edx, 64
    jb .next
    cmp edx, 127
    ja .next
    cmp dword [mp_ts_self], 0
    jne .have_self
    mov [mp_ts_self], ecx
.have_self:
    call mp_add_target
.next:
    inc r12
    jmp .scan
.d:
END_FN

FN mp_scan
    mov dword [mp_host_count], 0
    mov dword [mp_tgt_count], 0
    cmp dword [mp_wsa_ready], 0
    jne .ws
    mov ecx, 0x0202
    lea rdx, [mp_wsa]
    call WSAStartup
    mov dword [mp_wsa_ready], 1
.ws:
    call mp_collect_adapters
    mov ecx, 0xFFFFFFFF
    call mp_add_target
    call mp_tailscale
    lea rcx, [mp_e_extra]
    lea rdx, [wpath1]
    mov r8d, 40
    call GetEnvironmentVariableW
    test eax, eax
    jz .noextra
    lea rcx, [mp_ascii]
    lea rdx, [wpath1]
    mov r8d, 40
    call wide_to_ascii
    lea rcx, [mp_ascii]
    call v_ipv4
    test eax, eax
    jz .noextra
    lea rcx, [mp_ascii]
    call inet_addr
    mov ecx, eax
    call mp_add_target
.noextra:
    mov ecx, 2
    mov edx, 2
    mov r8d, 17
    call socket
    cmp rax, -1
    je .d
    mov r12, rax
    mov dword [mp_one], 1
    mov rcx, r12
    mov edx, 0xFFFF
    mov r8d, 0x20
    lea r9, [mp_one]
    mov qword [rsp+32], 4
    call setsockopt
    lea rdi, [mp_query]
    xor eax, eax
    mov ecx, 64
    rep stosb
    mov dword [mp_query], 'MSDQ'
    mov byte [mp_query+4], 1
    xor r13d, r13d
.send:
    cmp r13d, [mp_tgt_count]
    jae .sent
    lea rdi, [mp_sa]
    xor eax, eax
    mov ecx, 16
    rep stosb
    mov word [mp_sa], 2
    mov word [mp_sa+2], 0x601E
    lea rax, [mp_tgt]
    mov eax, [rax+r13*4]
    mov [mp_sa+4], eax
    mov rcx, r12
    lea rdx, [mp_query]
    mov r8d, 64
    xor r9d, r9d
    lea rax, [mp_sa]
    mov [rsp+32], rax
    mov qword [rsp+40], 16
    call sendto
    inc r13d
    jmp .send
.sent:
    call GetTickCount64
    lea r14, [rax+1200]
.recv:
    call GetTickCount64
    cmp rax, r14
    jae .done
    mov [mp_pfd], r12
    mov word [mp_pfd+8], 0x0100
    mov word [mp_pfd+10], 0
    lea rcx, [mp_pfd]
    mov edx, 1
    mov r8d, 100
    call WSAPoll
    cmp eax, 1
    jne .recv
    mov dword [mp_fromlen], 32
    mov rcx, r12
    lea rdx, [mp_rbuf]
    mov r8d, 128
    xor r9d, r9d
    lea rax, [mp_from]
    mov [rsp+32], rax
    lea rax, [mp_fromlen]
    mov [rsp+40], rax
    call recvfrom
    cmp eax, 64
    jne .recv
    cmp dword [mp_rbuf], 'MSDR'
    jne .recv
    cmp byte [mp_rbuf+4], 1
    jne .recv
    mov r15d, [mp_from+4]
    mov ecx, r15d
    call mp_is_local
    test eax, eax
    jnz .recv
    xor eax, eax
    mov edx, [mp_host_count]
    cmp edx, 30
    jae .done
    lea r8, [mp_host_ip]
.dup:
    cmp eax, edx
    jae .newhost
    cmp [r8+rax*4], r15d
    je .recv
    inc eax
    jmp .dup
.newhost:
    mov [r8+rdx*4], r15d
    movzx eax, word [mp_rbuf+6]
    lea r8, [mp_host_port]
    mov [r8+rdx*2], ax
    movzx eax, byte [mp_rbuf+5]
    lea r8, [mp_host_flags]
    mov [r8+rdx], al
    mov eax, edx
    shl eax, 5
    lea rdi, [mp_host_name]
    add rdi, rax
    xor ecx, ecx
    lea r9, [mp_rbuf+8]
.nm:
    movzx eax, byte [r9+rcx]
    test eax, eax
    jz .nmend
    cmp eax, 32
    jb .bad
    cmp eax, 126
    jbe .okc
.bad:
    mov eax, '?'
.okc:
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 31
    jb .nm
.nmend:
    mov byte [rdi+rcx], 0
    inc dword [mp_host_count]
    jmp .recv
.done:
    mov rcx, r12
    call closesocket
.d:
END_FN

FN mp_ip_text
    mov r10, rdx
    movzx r8d, cl
    mov edx, ecx
    shr edx, 8
    movzx r9d, dl
    mov edx, ecx
    shr edx, 16
    movzx edx, dl
    mov [rsp+32], rdx
    mov edx, ecx
    shr edx, 24
    mov [rsp+40], rdx
    mov rcx, r10
    lea rdx, [mp_f_ascii_ip]
    call wsprintfA
END_FN

FN mp_set_status
    mov rdx, rcx
    mov rcx, [h_join_status]
    call SetWindowTextW
    mov rcx, [h_join_status]
    call UpdateWindow
END_FN

FN mp_fill_list
    mov rcx, [h_list]
    mov edx, 0x184
    xor r8d, r8d
    xor r9d, r9d
    call SendMessageW
    xor r12d, r12d
.l: cmp r12d, [mp_host_count]
    jae .d
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [mp_ascii]
    call mp_ip_text
    lea rax, [mp_host_flags]
    movzx eax, byte [rax+r12]
    and eax, 3
    lea rdx, [mp_t_flagtext]
    mov rdx, [rdx+rax*8]
    mov eax, r12d
    shl eax, 5
    lea r8, [mp_host_name]
    add r8, rax
    lea rcx, [mp_text]
    mov [rsp+32], rdx
    lea rdx, [mp_f_list_a]
    lea r9, [mp_ascii]
    call wsprintfA
    mov r8d, eax
    lea rcx, [mp_big]
    lea rdx, [mp_text]
    call ascii_to_wide
    mov rcx, [h_list]
    mov edx, 0x180
    xor r8d, r8d
    lea r9, [mp_big]
    call SendMessageW
    inc r12d
    jmp .l
.d:
END_FN

FN mp_refresh
    lea rcx, [mp_s_scanning]
    call mp_set_status
    call mp_scan
    call mp_fill_list
    lea rcx, [mp_s_found]
    cmp dword [mp_host_count], 0
    jne .s
    lea rcx, [mp_s_none]
.s: call mp_set_status
END_FN

FN mp_cfg_path
    lea rcx, [mp_e_local]
    lea rdx, [wpath1]
    mov r8d, 400
    call GetEnvironmentVariableW
    test eax, eax
    jz .bad
    cmp eax, 400
    ja .bad
    lea rcx, [wpath2]
    lea rdx, [mp_f_cfgpath]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    call ensure_dirs
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN mp_old_pass
    mov byte [mp_pass], 0
    lea rcx, [wpath2]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    cmp rax, 8
    jl .d
    mov r13, rax
    lea rcx, [file_buf]
    mov rdx, rax
    lea r8, [mp_k_pass]
    mov r9d, mp_k_pass_len
    call find_bytes
    test rax, rax
    jz .d
    lea rsi, [rax+mp_k_pass_len]
    lea rdi, [file_buf]
    add rdi, r13
    lea r8, [mp_pass]
    xor ecx, ecx
.c: cmp rsi, rdi
    jae .e
    movzx eax, byte [rsi]
    cmp al, 13
    je .e
    cmp al, 10
    je .e
    cmp ecx, 64
    jae .bad
    mov [r8+rcx], al
    inc ecx
    inc rsi
    jmp .c
.e: mov byte [r8+rcx], 0
    lea rcx, [mp_pass]
    call v_pass
    test eax, eax
    jnz .d
.bad:
    mov byte [mp_pass], 0
.d:
END_FN

FN mp_pick_player
    call mp_cfg_path
    test eax, eax
    jz .rand
    lea rcx, [wpath2]
    lea rdx, [file_buf]
    mov r8d, 4000
    call read_file
    cmp rax, 8
    jl .rand
    mov rdx, rax
    lea rcx, [file_buf]
    lea r8, [mp_k_player]
    mov r9d, mp_k_player_len
    call find_bytes
    test rax, rax
    jz .rand
    movzx eax, byte [rax+mp_k_player_len]
    sub eax, '0'
    cmp eax, 1
    jl .rand
    cmp eax, 7
    jg .rand
    jmp .d
.rand:
    lea rcx, [mp_guid]
    call CoCreateGuid
    movzx eax, byte [mp_guid]
    xor edx, edx
    mov ecx, 7
    div ecx
    lea eax, [rdx+1]
.d:
END_FN

FN mp_save_join
    mov r12, rcx
    mov r13d, edx
    mov r14d, r8d
    mov r15, r9
    call mp_cfg_path
    test eax, eax
    jz .bad
    lea rcx, [mp_text]
    lea rdx, [mp_f_cfg_join]
    mov r8, r12
    mov r9d, r13d
    mov eax, r14d
    mov [rsp+32], rax
    mov [rsp+40], r15
    call wsprintfA
    mov r12d, eax
    cmp byte [mp_pass], 0
    je .nopw
    lea rcx, [mp_text]
    add rcx, r12
    lea rdx, [mp_f_cfg_pass]
    lea r8, [mp_pass]
    call wsprintfA
    add r12d, eax
.nopw:
    mov r8d, r12d
    lea rcx, [wpath2]
    lea rdx, [mp_text]
    call write_file
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN mp_append_ip
    mov r12, rcx
    mov ecx, edx
    lea rdx, [mp_ascii]
    call mp_ip_text
    mov r8d, eax
    lea rcx, [wpath3]
    lea rdx, [mp_ascii]
    call ascii_to_wide
    lea rcx, [mp_msg]
    mov rdx, r12
    lea r8, [mp_msg]
    call join_wide
    lea rcx, [mp_msg]
    lea rdx, [wpath3]
    lea r8, [mp_msg]
    call join_wide
    lea rcx, [mp_msg]
    lea rdx, [mp_t_crlf]
    lea r8, [mp_msg]
    call join_wide
END_FN

FN mp_do_host
    call mp_cfg_path
    test eax, eax
    jz .fail
    call mp_old_pass
    cmp byte [mp_pass], 0
    jne .withpass
    lea rcx, [mp_f_cfg_host]
    call lstrlenA
    mov r8d, eax
    lea rcx, [wpath2]
    lea rdx, [mp_f_cfg_host]
    call write_file
    jmp .written
.withpass:
    lea rcx, [mp_text]
    lea rdx, [mp_f_cfg_host_pass]
    lea r8, [mp_pass]
    call wsprintfA
    mov r8d, eax
    lea rcx, [wpath2]
    lea rdx, [mp_text]
    call write_file
.written:
    test eax, eax
    jz .fail
    mov dword [mp_tgt_count], 0
    call mp_collect_adapters
    call mp_tailscale
    lea rcx, [mp_f_hostmsg]
    lea rdx, [mp_msg]
    call wcopy
    cmp dword [mp_ts_self], 0
    je .lan
    lea rcx, [mp_t_tailscale]
    mov edx, [mp_ts_self]
    call mp_append_ip
.lan:
    xor r12d, r12d
.l: cmp r12d, [mp_local_count]
    jae .end
    lea rax, [mp_local_ips]
    mov edx, [rax+r12*4]
    mov eax, edx
    and eax, 0xFFFF
    cmp eax, 0xFEA9
    je .nx
    lea rcx, [mp_t_lan]
    call mp_append_ip
.nx:
    inc r12d
    jmp .l
.end:
    lea rcx, [mp_msg]
    lea rdx, [mp_f_hostend]
    lea r8, [mp_msg]
    call join_wide
    mov rcx, [h_wnd]
    lea rdx, [mp_msg]
    lea r8, [mp_m_title]
    mov r9d, 0x40
    call MessageBoxW
    jmp .d
.fail:
    mov rcx, [h_wnd]
    lea rdx, [mp_s_nosave]
    lea r8, [mp_m_title]
    mov r9d, 0x10
    call MessageBoxW
.d:
END_FN

FN mp_do_steam
    xor ecx, ecx
    lea rdx, [wpath1]
    mov r8d, 520
    call GetModuleFileNameW
    test eax, eax
    jz .d
    lea rcx, [wpath1]
    call cut_last_component
    lea rcx, [wpath2]
    lea rdx, [mp_f_launcher]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    lea rdx, [mp_s_command]
    lea r8, [wpath3]
    call join_wide
    lea rcx, [wpath3]
    call clip_set
    mov rcx, [h_wnd]
    lea rdx, [mp_f_steammsg]
    lea r8, [mp_m_title]
    mov r9d, 0x40
    call MessageBoxW
.d:
END_FN

FN mp_finish_join
    mov r12, rcx
    mov r13d, edx
    mov r14d, r8d
    mov rcx, [h_ed_player]
    lea rdx, [wpath1]
    mov r8d, 8
    call GetWindowTextW
    lea rcx, [mp_ascii]
    lea rdx, [wpath1]
    mov r8d, 8
    call wide_to_ascii
    lea rcx, [mp_ascii]
    call a2i
    cmp eax, 1
    jl .badplayer
    cmp eax, 7
    jg .badplayer
    mov r15d, eax
    mov rcx, [h_ed_room]
    lea rdx, [wpath1]
    mov r8d, 20
    call GetWindowTextW
    lea rcx, [mp_ascii+16]
    lea rdx, [wpath1]
    mov r8d, 20
    call wide_to_ascii
    cmp byte [mp_ascii+16], 0
    jne .checkroom
    test r14d, 1
    jnz .needroom
    jmp .save
.checkroom:
    lea rcx, [mp_ascii+16]
    call v_room
    test eax, eax
    jz .badroom
.save:
    mov rcx, [h_ed_pass]
    lea rdx, [wpath1]
    mov r8d, 66
    call GetWindowTextW
    xor ecx, ecx
    lea rsi, [wpath1]
    lea rdi, [mp_pass]
.pw:
    movzx eax, word [rsi+rcx*2]
    test eax, eax
    jz .pwend
    cmp eax, 33
    jb .badpass
    cmp eax, 126
    ja .badpass
    cmp ecx, 64
    jae .badpass
    mov [rdi+rcx], al
    inc ecx
    jmp .pw
.pwend:
    mov byte [rdi+rcx], 0
    test ecx, ecx
    jnz .pwdone
    test r14d, 2
    jnz .needpass
.pwdone:
    mov rcx, r12
    mov edx, r13d
    mov r8d, r15d
    lea r9, [mp_ascii+16]
    call mp_save_join
    test eax, eax
    jz .nosave
    lea rcx, [mp_f_joinmsg]
    lea rdx, [mp_msg]
    call wcopy
    lea rcx, [wpath3]
    mov rdx, r12
    xor r8d, r8d
    call lstrlenA
    mov r8d, eax
    lea rcx, [wpath3]
    mov rdx, r12
    call ascii_to_wide
    lea rcx, [mp_msg]
    lea rdx, [wpath3]
    lea r8, [mp_msg]
    call join_wide
    lea rdx, [mp_t_world_later]
    lea rcx, [mp_msg]
    lea r8, [mp_msg]
    call join_wide
    mov rcx, [h_join]
    lea rdx, [mp_msg]
    lea r8, [mp_m_title]
    mov r9d, 0x40
    call MessageBoxW
    mov rcx, [h_join]
    call DestroyWindow
    jmp .d
.badplayer:
    lea rcx, [mp_s_badplayer]
    jmp .st
.badroom:
    lea rcx, [mp_s_badroom]
    jmp .st
.needroom:
    lea rcx, [mp_s_needroom]
    jmp .st
.badpass:
    lea rcx, [mp_s_badpass]
    jmp .st
.needpass:
    lea rcx, [mp_s_needpass]
    jmp .st
.nosave:
    lea rcx, [mp_s_nosave]
.st:
    call mp_set_status
.d:
END_FN

FN mp_join_selected
    mov rcx, [h_list]
    mov edx, 0x188
    xor r8d, r8d
    xor r9d, r9d
    call SendMessageW
    cmp eax, -1
    je .none
    cmp eax, [mp_host_count]
    jae .none
    mov r12d, eax
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [mp_ascii+32]
    call mp_ip_text
    lea rax, [mp_host_port]
    movzx edx, word [rax+r12*2]
    lea rax, [mp_host_flags]
    movzx r8d, byte [rax+r12]
    lea rcx, [mp_ascii+32]
    call mp_finish_join
    jmp .d
.none:
    lea rcx, [mp_s_pick]
    call mp_set_status
.d:
END_FN

FN mp_join_ip
    mov rcx, [h_ed_ip]
    lea rdx, [wpath1]
    mov r8d, 40
    call GetWindowTextW
    lea rcx, [mp_ascii+32]
    lea rdx, [wpath1]
    mov r8d, 20
    call wide_to_ascii
    lea rcx, [mp_ascii+32]
    call v_ipv4
    test eax, eax
    jz .bad
    lea rcx, [mp_ascii+32]
    mov edx, 7777
    xor r8d, r8d
    call mp_finish_join
    jmp .d
.bad:
    lea rcx, [mp_s_badip]
    call mp_set_status
.d:
END_FN

FN join_proc
    cmp edx, 0x111
    je .cmd
    cmp edx, 0x10
    je .close
    cmp edx, 2
    je .destroy
    call DefWindowProcW
    jmp .d
.cmd:
    movzx eax, r8w
    cmp eax, 11
    je .refresh
    cmp eax, 12
    je .joinsel
    cmp eax, 14
    je .joinip
    xor eax, eax
    jmp .d
.refresh:
    call mp_refresh
    xor eax, eax
    jmp .d
.joinsel:
    call mp_join_selected
    xor eax, eax
    jmp .d
.joinip:
    call mp_join_ip
    xor eax, eax
    jmp .d
.close:
    call DestroyWindow
    xor eax, eax
    jmp .d
.destroy:
    mov qword [h_join], 0
    xor eax, eax
.d:
END_FN

FN mp_open_join
    cmp qword [h_join], 0
    je .create
    mov rcx, [h_join]
    call SetFocus
    jmp .d
.create:
    xor ecx, ecx
    lea rdx, [mp_join_class]
    lea r8, [mp_join_title]
    mov r9d, 0x10CA0000
    mov dword [rsp+32], 0x80000000
    mov dword [rsp+40], 0x80000000
    mov qword [rsp+48], 480
    mov qword [rsp+56], 476
    mov qword [rsp+64], 0
    mov qword [rsp+72], 0
    mov rax, [h_inst]
    mov [rsp+80], rax
    mov qword [rsp+88], 0
    call CreateWindowExW
    test rax, rax
    jz .d
    mov [h_join], rax
    mov [cur_parent], rax
    lea rcx, [cls_static]
    lea rdx, [mp_t_hosts]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 10
    mov r13d, 440
    mov r14d, 18
    mov r15d, 30
    call make_child
    lea rcx, [mp_listbox]
    lea rdx, [mp_t_empty_w]
    mov r8d, 0x50A10001
    mov r9d, 14
    mov r12d, 32
    mov r13d, 440
    mov r14d, 150
    mov r15d, 20
    call make_child
    mov [h_list], rax
    lea rcx, [cls_button]
    lea rdx, [mp_t_refresh]
    mov r8d, 0x50010000
    mov r9d, 14
    mov r12d, 190
    mov r13d, 100
    mov r14d, 26
    mov r15d, 11
    call make_child
    lea rcx, [cls_button]
    lea rdx, [mp_t_joinsel]
    mov r8d, 0x50010000
    mov r9d, 124
    mov r12d, 190
    mov r13d, 130
    mov r14d, 26
    mov r15d, 12
    call make_child
    lea rcx, [cls_static]
    lea rdx, [mp_t_orip]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 232
    mov r13d, 300
    mov r14d, 18
    mov r15d, 31
    call make_child
    lea rcx, [mp_edit]
    lea rdx, [mp_t_empty_w]
    mov r8d, 0x50810080
    mov r9d, 14
    mov r12d, 252
    mov r13d, 220
    mov r14d, 24
    mov r15d, 13
    call make_child
    mov [h_ed_ip], rax
    lea rcx, [cls_button]
    lea rdx, [mp_t_joinip]
    mov r8d, 0x50010000
    mov r9d, 244
    mov r12d, 251
    mov r13d, 110
    mov r14d, 26
    mov r15d, 14
    call make_child
    lea rcx, [cls_static]
    lea rdx, [mp_t_player]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 294
    mov r13d, 200
    mov r14d, 18
    mov r15d, 32
    call make_child
    lea rcx, [mp_edit]
    lea rdx, [mp_t_empty_w]
    mov r8d, 0x50810080
    mov r9d, 220
    mov r12d, 291
    mov r13d, 40
    mov r14d, 24
    mov r15d, 15
    call make_child
    mov [h_ed_player], rax
    lea rcx, [cls_static]
    lea rdx, [mp_t_room]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 326
    mov r13d, 260
    mov r14d, 18
    mov r15d, 33
    call make_child
    lea rcx, [mp_edit]
    lea rdx, [mp_t_empty_w]
    mov r8d, 0x50810080
    mov r9d, 280
    mov r12d, 323
    mov r13d, 110
    mov r14d, 24
    mov r15d, 16
    call make_child
    mov [h_ed_room], rax
    lea rcx, [cls_static]
    lea rdx, [mp_t_pass]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 358
    mov r13d, 270
    mov r14d, 18
    mov r15d, 34
    call make_child
    lea rcx, [mp_edit]
    lea rdx, [mp_t_empty_w]
    mov r8d, 0x508100A0
    mov r9d, 290
    mov r12d, 355
    mov r13d, 110
    mov r14d, 24
    mov r15d, 18
    call make_child
    mov [h_ed_pass], rax
    lea rcx, [cls_static]
    lea rdx, [mp_s_ready]
    mov r8d, 0x50000000
    mov r9d, 14
    mov r12d, 394
    mov r13d, 440
    mov r14d, 36
    mov r15d, 17
    call make_child
    mov [h_join_status], rax
    mov rax, [h_wnd]
    mov [cur_parent], rax
    call mp_pick_player
    lea rcx, [mp_ascii]
    mov byte [rcx], al
    add byte [rcx], '0'
    mov byte [rcx+1], 0
    lea rcx, [wpath1]
    lea rdx, [mp_ascii]
    mov r8d, 1
    call ascii_to_wide
    mov rcx, [h_ed_player]
    lea rdx, [wpath1]
    call SetWindowTextW
    call mp_refresh
.d:
END_FN

FN mp_dump_scan
    mov r14, rcx
    lea rax, [http_buf]
    mov byte [rax], 0
    xor r12d, r12d
    xor r13d, r13d
.l: cmp r12d, [mp_host_count]
    jae .write
    lea rax, [mp_host_ip]
    mov ecx, [rax+r12*4]
    lea rdx, [mp_ascii]
    call mp_ip_text
    mov eax, r12d
    shl eax, 5
    lea r10, [mp_host_name]
    add r10, rax
    lea rax, [mp_host_port]
    movzx r9d, word [rax+r12*2]
    lea rax, [mp_host_flags]
    movzx eax, byte [rax+r12]
    lea rcx, [http_buf]
    add rcx, r13
    lea rdx, [mp_f_ascii_entry]
    lea r8, [mp_ascii]
    mov [rsp+32], rax
    mov [rsp+40], r10
    call wsprintfA
    add r13d, eax
    inc r12d
    jmp .l
.write:
    mov rcx, r14
    lea rdx, [http_buf]
    mov r8d, r13d
    call write_file
END_FN

FN mp_emit_addr
    lea rdx, [mp_ascii]
    call mp_ip_text
    lea rcx, [http_buf]
    mov eax, [mp_dump_len]
    add rcx, rax
    lea rdx, [mp_f_addr_line]
    lea r8, [mp_ascii]
    call wsprintfA
    add [mp_dump_len], eax
END_FN

FN mp_dump_addrs
    mov r14, rcx
    mov dword [mp_tgt_count], 0
    mov dword [mp_dump_len], 0
    call mp_collect_adapters
    call mp_tailscale
    mov ecx, [mp_ts_self]
    test ecx, ecx
    jz .locals
    call mp_emit_addr
.locals:
    xor r12d, r12d
.l: cmp r12d, [mp_local_count]
    jae .write
    cmp dword [mp_dump_len], 3000
    jae .write
    lea rax, [mp_local_ips]
    mov ecx, [rax+r12*4]
    mov eax, ecx
    and eax, 0xFFFF
    cmp eax, 0xFEA9
    je .nx
    cmp ecx, [mp_ts_self]
    je .nx
    call mp_emit_addr
.nx:
    inc r12d
    jmp .l
.write:
    mov rcx, r14
    lea rdx, [http_buf]
    mov r8d, [mp_dump_len]
    call write_file
END_FN
