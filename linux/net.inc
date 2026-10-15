; Networking shared by the Linux launcher and manager: addresses, the world download client (protocol: docs/PROTOCOL.md)
; and the host scan (broadcast on every local network plus the Tailscale peer list). Raw syscalls, no libc.
;   client and host first run the challenge and response of worldauth.inc (proof of the join session's key), then
;   host -> client   144-byte header: "MSWR", version 2, status (0 ok, 1 no world, 2 cannot send, 3 refused),
;                    file length u32 @8, SHA-256 @12 (32 bytes), file name @48 (64 bytes, NUL padded), tag @112 (32 bytes);
;                    then the file bytes

%define WF_PORT_NET 0x5F1E              ; TCP 7775 in network byte order
%define WF_MAX_FILE 209715200           ; 200 MB
%define DISC_PORT_NET 0x601E            ; UDP 7776

section .bss
wf_sock resq 1
wf_hdr resb 160
wf_req resb 64
wf_keybuf resb 1100
wf_sa resb 16
wf_pfd resb 8
wf_one resd 1
wf_digest resb 32
wf_connect_ms resd 1
wf_path1 resb 1100
wf_path2 resb 1100
ifc_req resb 16
ifc_buf resb 1280
ifr_tmp resb 40
mp_sock resq 1
mp_pfd resb 8
mp_sa resb 16
mp_from resb 16
mp_fromlen resd 1
mp_query resb 64
mp_rbuf resb 128
mp_one resd 1
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
mp_ascii resb 64
ts_out resb 262144
ts_pipe resd 2
dev_null resq 1

section .data
s_devnull db '/dev/null',0
s_ts_env db 'MISTRIMULTI_TAILSCALE',0
s_ts_name db 'tailscale',0
s_ts_status db 'status',0
s_ts_json db '--json',0
s_scan_extra db 'MISTRIMULTI_SCAN_EXTRA',0
s_part db '.part',0
s_wkey1 db '/world_',0
s_wkey2 db '.key',0
s_slash db '/',0
align 8

section .text
; ---------------- addresses ----------------
FN ip_parse                     ; rcx dotted ASCII (already checked with v_ipv4) -> eax IPv4 in network byte order (as in memory)
    mov rsi, rcx
    xor eax, eax
    xor r8d, r8d                    ; shift
.g: xor edx, edx
.d: movzx r9d, byte [rsi]
    sub r9d, '0'
    cmp r9d, 9
    ja .e
    imul edx, edx, 10
    add edx, r9d
    inc rsi
    jmp .d
.e: mov ecx, r8d
    shl edx, cl
    or eax, edx
    add r8d, 8
    cmp r8d, 32
    jae .done
    inc rsi                         ; skip the dot
    jmp .g
.done:
END_FN

FN ip_text                      ; ecx IPv4 (network order), rdx out buffer (>= 16 bytes) -> writes dotted text and a NUL
    mov rdi, rdx
    mov ebx, ecx
    mov r9d, 10
    xor r8d, r8d
.b: movzx eax, bl
    cmp eax, 100
    jb .lt100
    xor edx, edx
    mov ecx, 100
    div ecx
    add al, '0'
    stosb
    mov eax, edx
    xor edx, edx
    div r9d
    add al, '0'
    stosb
    mov eax, edx
    jmp .last
.lt100:
    cmp eax, 10
    jb .last
    xor edx, edx
    div r9d
    add al, '0'
    stosb
    mov eax, edx
.last:
    add al, '0'
    stosb
    shr ebx, 8
    inc r8d
    cmp r8d, 4
    jae .end
    mov al, '.'
    stosb
    jmp .b
.end:
    mov byte [rdi], 0
END_FN

; ---------------- sockets ----------------
FN wf_recv_exact                ; rcx buffer, edx byte count, r8d timeout per wait (ms), reads from [wf_sock] -> eax 1 ok
    mov rsi, rcx
    mov r12d, edx
    mov r13d, r8d
    xor r14d, r14d
.loop:
    cmp r14d, r12d
    jae .ok
    mov rax, [wf_sock]
    mov [wf_pfd], eax
    mov word [wf_pfd+4], POLLIN
    mov word [wf_pfd+6], 0
    lea rcx, [wf_pfd]
    mov edx, 1
    mov r8d, r13d
    call sys_poll
    cmp rax, EINTR
    je .loop
    cmp eax, 1
    jne .fail
    mov rcx, [wf_sock]
    lea rdx, [rsi+r14]
    mov r8d, r12d
    sub r8d, r14d
    call sys_read
    cmp rax, EINTR
    je .loop
    test rax, rax
    jle .fail
    add r14d, eax
    jmp .loop
.ok:
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN wf_send_all                  ; rcx buffer, edx byte count, sends on [wf_sock] (never raises SIGPIPE) -> eax 1 ok
    mov rsi, rcx
    mov r12d, edx
    xor r14d, r14d
.loop:
    cmp r14d, r12d
    jae .ok
    mov r8d, r12d
    sub r8d, r14d
    cmp r8d, 65536
    jbe .sz
    mov r8d, 65536
.sz:
    mov rcx, [wf_sock]
    lea rdx, [rsi+r14]
    mov r9d, MSG_NOSIGNAL
    mov qword [rsp+32], 0
    mov qword [rsp+40], 0
    call sys_sendto
    cmp rax, EINTR
    je .loop
    test rax, rax
    jle .fail
    add r14d, eax
    jmp .loop
.ok:
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN fill_sockaddr                ; rcx destination (16 bytes), edx port in network order, r8d IPv4 in network order
    mov qword [rcx], 0
    mov qword [rcx+8], 0
    mov word [rcx], 2
    mov [rcx+2], dx
    mov [rcx+4], r8d
END_FN

; ---------------- world download ----------------
FN wf_random                    ; rcx buffer, edx count (<= 256) -> eax 1
    call random_bytes
    mov eax, 1
END_FN

FN wf_key_path                  ; rcx output (1100 bytes), rdx bridge folder, r8d slot: the key file the helper writes for a join session
    mov r12, rdx
    mov r13d, r8d
    mov edx, 1100
    call pb_start
    mov rcx, r12
    call pb_str
    lea rcx, [s_wkey1]
    call pb_str
    mov ecx, r13d
    call pb_int
    lea rcx, [s_wkey2]
    call pb_str
    call pb_end
END_FN

FN world_use_session            ; rcx bridge folder, edx this computer's slot (1-7): the download proves the helper's join session in that folder
    mov [wf_slot], edx
    mov r8d, edx
    mov rdx, rcx
    lea rcx, [wf_keybuf]
    call wf_key_path
    cmp eax, -1
    je .d
    lea rax, [wf_keybuf]
    mov [wf_keypath], rax
.d:
END_FN

; ecx = host IPv4 (network order), rdx = destination folder. Downloads the host's world into that folder; needs
; world_use_session first (the host releases the world only to a joined player).
; Returns 0 ok, 1 cannot connect, 2 host has no world to give, 3 invalid reply, 4 checksum mismatch, 5 cannot write, 6 out of memory,
; 7 refused (no joined session, wrong proof, or a host that does not speak the authenticated protocol)
FN world_fetch
    mov r12d, ecx
    mov r13, rdx
    xor r15d, r15d                     ; memory block
    xor ebx, ebx                       ; result: a socket may not exist yet
    mov qword [wf_sock], 0
    mov rcx, [wf_keypath]
    test rcx, rcx
    jz .refused
    call wa_load_key
    test eax, eax
    jz .refused
    cmp dword [wf_connect_ms], 0
    jne .have_ms
    mov dword [wf_connect_ms], 3000
.have_ms:
    mov ecx, 2
    mov edx, 1 | 0x800 | 0x80000       ; SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC: every wait below is a timed poll
    xor r8d, r8d
    call sys_socket
    test rax, rax
    js .noconn
    mov [wf_sock], rax
    lea rcx, [wf_sa]
    mov edx, WF_PORT_NET
    mov r8d, r12d
    call fill_sockaddr
    mov rcx, [wf_sock]
    lea rdx, [wf_sa]
    mov r8d, 16
    call sys_connect
    test rax, rax
    jz .connected
    cmp rax, EINPROGRESS
    jne .noconn
    mov rax, [wf_sock]
    mov [wf_pfd], eax
    mov word [wf_pfd+4], POLLOUT
    mov word [wf_pfd+6], 0
    lea rcx, [wf_pfd]
    mov edx, 1
    mov r8d, [wf_connect_ms]
    call sys_poll
    cmp eax, 1
    jne .noconn
    test word [wf_pfd+6], POLLERR | POLLHUP | POLLNVAL
    jnz .noconn
    mov dword [wf_one], 4
    mov dword [wf_digest], 0
    mov rcx, [wf_sock]
    mov edx, 1                         ; SOL_SOCKET
    mov r8d, 4                         ; SO_ERROR
    lea r9, [wf_digest]
    lea rax, [wf_one]
    mov [rsp+32], rax
    call sys_getsockopt
    cmp dword [wf_digest], 0
    jne .noconn
.connected:
    call wa_client_hello
    test eax, eax
    jz .refused
    lea rcx, [wf_hdr]
    mov edx, 144
    mov r8d, 5000
    call wf_recv_exact
    test eax, eax
    jz .refused
    cmp dword [wf_hdr], 'MSWR'
    jne .refused
    cmp byte [wf_hdr+4], 2
    jne .refused
    cmp byte [wf_hdr+5], 3
    je .refused
    call wa_check_header               ; nothing below is believed unless the host proved the session key too
    test eax, eax
    jz .refused
    movzx eax, byte [wf_hdr+5]
    test eax, eax
    jz .status_ok
    cmp eax, 1
    jne .bad
    mov r14d, 2
    jmp .close
.status_ok:
    mov r14d, [wf_hdr+8]
    test r14d, r14d
    jz .bad
    cmp r14d, WF_MAX_FILE
    ja .bad
    mov byte [wf_hdr+111], 0           ; the name must end inside the header
    lea rcx, [wf_hdr+48]
    call wf_valid_name
    test eax, eax
    jz .bad
    xor ecx, ecx
    mov edx, r14d
    mov r8d, 3                         ; PROT_READ | PROT_WRITE
    mov r9d, 0x22                      ; MAP_PRIVATE | MAP_ANONYMOUS
    mov qword [rsp+32], -1
    mov qword [rsp+40], 0
    call sys_mmap
    cmp rax, -4096
    ja .nomem
    mov r15, rax
    mov rcx, r15
    mov edx, r14d
    mov r8d, 15000
    call wf_recv_exact
    test eax, eax
    jz .bad
    mov rcx, r15
    mov edx, r14d
    lea r8, [wf_digest]
    call sha256_raw
    lea rsi, [wf_digest]
    lea rdi, [wf_hdr+12]
    mov ecx, 32
    repe cmpsb
    jne .badsum
    lea rcx, [wf_path1]
    mov edx, 1100
    call pb_start
    mov rcx, r13
    call pb_str
    lea rcx, [s_slash]
    call pb_str
    lea rcx, [wf_hdr+48]
    call pb_str
    call pb_end
    cmp eax, -1
    je .nowrite_nofile
    lea rcx, [wf_path2]
    lea rdx, [wf_path1]
    call str_copy
    mov rcx, rax
    lea rdx, [s_part]
    call str_copy
    lea rcx, [wf_path2]
    call ensure_dirs
    lea rcx, [wf_path2]
    mov rdx, r15
    mov r8d, r14d
    call write_plain
    test eax, eax
    jz .nowrite
    lea rcx, [wf_path2]
    lea rdx, [wf_path1]
    call sys_rename
    test rax, rax
    jnz .nowrite
    xor r14d, r14d
    jmp .close
.nowrite:
    lea rcx, [wf_path2]
    call sys_unlink
.nowrite_nofile:
    mov r14d, 5
    jmp .close
.badsum:
    mov r14d, 4
    jmp .close
.nomem:
    mov r14d, 6
    jmp .close
.refused:
    mov r14d, 7
    jmp .close
.bad:
    mov r14d, 3
    jmp .close
.noconn:
    mov r14d, 1
.close:
    test r15, r15
    jz .nofree
    mov rcx, r15
    mov edx, [wf_hdr+8]
    call sys_munmap
.nofree:
    mov rcx, [wf_sock]
    test rcx, rcx
    jz .done
    call sys_close
    mov qword [wf_sock], 0
.done:
    mov eax, r14d
END_FN

; ---------------- local networks ----------------
FN mp_add_target                ; ecx = IPv4 (network order)
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

FN mp_is_local                  ; ecx = IPv4 -> eax 1 if it is one of this computer's own addresses
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

; Reads this computer's IPv4 addresses (SIOCGIFCONF); the directed broadcast of each network becomes a scan target.
; Loopback addresses are not listed: a host on this very computer (tests) must still be found.
FN mp_collect_adapters
    mov dword [mp_local_count], 0
    mov ecx, 2
    mov edx, 2 | 0x80000
    xor r8d, r8d
    call sys_socket
    test rax, rax
    js .d
    mov r15, rax
    mov dword [ifc_req], 1280
    lea rax, [ifc_buf]
    mov [ifc_req+8], rax
    mov rcx, r15
    mov edx, 0x8912                    ; SIOCGIFCONF
    lea r8, [ifc_req]
    call sys_ioctl
    test rax, rax
    jnz .close
    mov r12d, [ifc_req]
    xor r13d, r13d
.entry:
    lea eax, [r13+40]
    cmp eax, r12d
    ja .close
    lea rsi, [ifc_buf]
    add rsi, r13
    cmp word [rsi+16], 2
    jne .next
    mov r14d, [rsi+20]
    cmp r14b, 127
    je .next
    mov ecx, [mp_local_count]
    cmp ecx, 30
    jae .next
    lea rdx, [mp_local_ips]
    mov [rdx+rcx*4], r14d
    inc dword [mp_local_count]
    lea rdi, [ifr_tmp]
    mov ecx, 5
    rep movsq
    mov rcx, r15
    mov edx, 0x891b                    ; SIOCGIFNETMASK
    lea r8, [ifr_tmp]
    call sys_ioctl
    test rax, rax
    jnz .next
    mov eax, [ifr_tmp+20]
    cmp eax, -1
    je .next                           ; a /32 (such as the Tailscale interface) has no broadcast address
    not eax
    or eax, r14d
    mov ecx, eax
    call mp_add_target
.next:
    add r13d, 40
    jmp .entry
.close:
    mov rcx, r15
    call sys_close
.d:
END_FN

FN open_devnull                 ; -> rax descriptor of /dev/null (opened once), or -1
    mov rax, [dev_null]
    test rax, rax
    jnz .d
    lea rcx, [s_devnull]
    mov edx, 2 | O_CLOEXEC             ; O_RDWR
    xor r8d, r8d
    call sys_open
    test rax, rax
    jns .ok
    mov rax, -1
.ok:
    mov [dev_null], rax
.d:
END_FN

; Runs "tailscale status --json" when Tailscale is installed (MISTRIMULTI_TAILSCALE overrides the program) and adds
; every peer's 100.x address as a scan target. The first 100.x address in the output is this computer's own (mp_ts_self).
FN mp_tailscale
    mov dword [mp_ts_self], 0
    lea rcx, [ts_pipe]
    mov edx, O_CLOEXEC
    call sys_pipe2
    test rax, rax
    jnz .d
    lea rcx, [s_ts_env]
    call env_get
    test rax, rax
    jz .default
    cmp byte [rax], 0
    jne .have
.default:
    lea rax, [s_ts_name]
.have:
    mov [rsp+48], rax                  ; argv[0] / program
    lea rax, [s_ts_status]
    mov [rsp+56], rax
    lea rax, [s_ts_json]
    mov [rsp+64], rax
    mov qword [rsp+72], 0
    call open_devnull
    mov r12, rax
    mov rcx, [rsp+48]
    lea rdx, [rsp+48]
    mov r8, r12
    mov r9d, [ts_pipe+4]
    mov [rsp+32], r12
    mov qword [rsp+40], 2              ; search PATH
    call spawn
    mov r13, rax
    mov ecx, [ts_pipe+4]
    call sys_close
    test r13, r13
    js .closer
    xor r14d, r14d                     ; bytes read
    call ticks_ms
    lea r15, [rax+4000]
.rd:
    mov eax, [ts_pipe]
    mov [mp_pfd], eax
    mov word [mp_pfd+4], POLLIN
    mov word [mp_pfd+6], 0
    lea rcx, [mp_pfd]
    mov edx, 1
    mov r8d, 100
    call sys_poll
    cmp eax, 1
    jne .chk
    mov ecx, [ts_pipe]
    lea rdx, [ts_out]
    add rdx, r14
    mov r8d, 262143
    sub r8, r14
    jbe .reap
    call sys_read
    test rax, rax
    jle .reap
    add r14, rax
    jmp .rd
.chk:
    call ticks_ms
    cmp rax, r15
    jb .rd
.reap:
    mov rcx, r13
    call proc_kill
    mov ecx, [ts_pipe]
    call sys_close
    cmp r14, 8
    jl .d
    lea rax, [ts_out]
    mov byte [rax+r14], 0
    xor r12d, r12d                     ; scan position
.scan:
    mov rax, r14
    sub rax, 5                        ; enough room for "100. (the buffer ends with a NUL)
    cmp r12, rax
    jae .d
    lea rcx, [ts_out]
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
    cmp ecx, 16                       ; 15 characters is the longest address; the 16th must be the closing quote
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
    call ip_parse
    mov ecx, eax
    movzx edx, ah                      ; second octet: Tailscale uses 100.64.0.0/10
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
.closer:
    mov ecx, [ts_pipe]
    call sys_close
.d:
END_FN

; Sends a discovery query to every target and collects the answers for about 1.2 seconds.
FN mp_scan
    mov dword [mp_host_count], 0
    mov dword [mp_tgt_count], 0
    call mp_collect_adapters
    mov ecx, 0xFFFFFFFF
    call mp_add_target
    call mp_tailscale
    ; optional extra target for tests: MISTRIMULTI_SCAN_EXTRA=<ipv4>
    lea rcx, [s_scan_extra]
    call env_get
    test rax, rax
    jz .noextra
    mov r12, rax
    mov rcx, rax
    call v_ipv4
    test eax, eax
    jz .noextra
    mov rcx, r12
    call ip_parse
    mov ecx, eax
    call mp_add_target
.noextra:
    mov ecx, 2
    mov edx, 2 | 0x80000 | 0x800
    xor r8d, r8d
    call sys_socket
    test rax, rax
    js .d
    mov r12, rax
    mov dword [mp_one], 1
    mov rcx, r12
    mov edx, 1                         ; SOL_SOCKET
    mov r8d, 6                         ; SO_BROADCAST
    lea r9, [mp_one]
    mov qword [rsp+32], 4
    call sys_setsockopt
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
    lea rax, [mp_tgt]
    mov r8d, [rax+r13*4]
    lea rcx, [mp_sa]
    mov edx, DISC_PORT_NET
    call fill_sockaddr
    mov rcx, r12
    lea rdx, [mp_query]
    mov r8d, 64
    xor r9d, r9d
    lea rax, [mp_sa]
    mov [rsp+32], rax
    mov qword [rsp+40], 16
    call sys_sendto
    inc r13d
    jmp .send
.sent:
    call ticks_ms
    lea r14, [rax+1200]
.recv:
    call ticks_ms
    cmp rax, r14
    jae .done
    mov [mp_pfd], r12d
    mov word [mp_pfd+4], POLLIN
    mov word [mp_pfd+6], 0
    lea rcx, [mp_pfd]
    mov edx, 1
    mov r8d, 100
    call sys_poll
    cmp eax, 1
    jne .recv
    mov dword [mp_fromlen], 16
    mov rcx, r12
    lea rdx, [mp_rbuf]
    mov r8d, 128
    xor r9d, r9d
    lea rax, [mp_from]
    mov [rsp+32], rax
    lea rax, [mp_fromlen]
    mov [rsp+40], rax
    call sys_recvfrom
    cmp rax, 64
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
    call sys_close
.d:
END_FN

%include "worldauth.inc"
