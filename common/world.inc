; Host-world transfer: shared pieces and the download client (NASM, Windows x64).  Protocol: docs/PROTOCOL.md
;   client and host first run the challenge and response of worldauth.inc (proof of the join session's key), then
;   host -> client   144-byte header: "MSWR", version 2, status (0 ok, 1 no world, 2 cannot send, 3 refused),
;                    file length u32 @8, SHA-256 @12 (32 bytes), file name @48 (64 bytes, NUL padded), tag @112 (32 bytes);
;                    then the file bytes
; The including program defines nothing extra but must include winutil.inc first and link ws2_32, bcrypt, kernel32.
extern ioctlsocket, connect, send, recv, closesocket, socket, WSAPoll, WSAStartup, shutdown
extern VirtualAlloc, VirtualFree, MoveFileExW, DeleteFileW, wsprintfW
extern BCryptOpenAlgorithmProvider, BCryptHash, BCryptCloseAlgorithmProvider, BCryptGenRandom

WF_PORT_NET equ 0x5F1E              ; TCP 7775 in network byte order
WF_MAX_FILE equ 209715200           ; 200 MB

section .data
wf_alg: dw __utf16__("SHA256"), 0
wf_f_part: dw __utf16__("%s\%S.part"), 0
wf_f_final: dw __utf16__("%s\%S"), 0
wf_f_key: dw __utf16__("%s\world_%d.key"), 0

section .bss
wf_sock resq 1
wf_wsa resb 408
wf_wsa_ready resd 1
wf_hdr resb 160
wf_req resb 64
wf_keybuf resw 1040
wf_sa resb 16
wf_pfd resb 16
wf_one resd 1
wf_halg resq 1
wf_digest resb 32
wf_connect_ms resd 1
wf_path1 resw 1040
wf_path2 resw 1040

section .text

; rcx data, rdx length, r8 = 32-byte output -> eax 1 ok
FN sha256_raw
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    lea rcx, [wf_halg]
    lea rdx, [wf_alg]
    xor r8d, r8d
    xor r9d, r9d
    call BCryptOpenAlgorithmProvider
    test eax, eax
    jnz .fail
    mov rcx, [wf_halg]
    xor edx, edx
    xor r8d, r8d
    mov r9, r12
    mov [rsp+32], r13
    mov [rsp+40], r14
    mov qword [rsp+48], 32
    call BCryptHash
    mov ebx, eax
    mov rcx, [wf_halg]
    xor edx, edx
    call BCryptCloseAlgorithmProvider
    test ebx, ebx
    jnz .fail
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN


; Reads exactly edx bytes from [wf_sock] into rcx; every wait is at most r8d milliseconds. eax 1 ok / 0 fail
FN wf_recv_exact
    mov rsi, rcx
    mov r12d, edx
    mov r13d, r8d
    xor r14d, r14d
.loop:
    cmp r14d, r12d
    jae .ok
    mov rax, [wf_sock]
    mov [wf_pfd], rax
    mov word [wf_pfd+8], 0x0100
    mov word [wf_pfd+10], 0
    lea rcx, [wf_pfd]
    mov edx, 1
    mov r8d, r13d
    call WSAPoll
    cmp eax, 1
    jne .fail
    mov rcx, [wf_sock]
    lea rdx, [rsi+r14]
    mov r8d, r12d
    sub r8d, r14d
    xor r9d, r9d
    call recv
    test eax, eax
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

; Sends exactly edx bytes from rcx on [wf_sock]. eax 1 ok / 0 fail
FN wf_send_all
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
    xor r9d, r9d
    call send
    test eax, eax
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

; rcx buffer, edx count -> eax 1 filled with system randomness
FN wf_random
    mov r8, rdx
    mov rdx, rcx
    xor ecx, ecx
    mov r9d, 2                         ; BCRYPT_USE_SYSTEM_PREFERRED_RNG
    call BCryptGenRandom
    test eax, eax
    sete al
    movzx eax, al
END_FN

; rcx = output (wide, 1040 characters), rdx = bridge folder (wide), r8d = slot: the key file the helper writes for a join session
FN wf_key_path
    mov r9d, r8d
    mov r8, rdx
    lea rdx, [wf_f_key]
    call wsprintfW
END_FN

; rcx = bridge folder (wide), edx = this computer's slot (1-7): the download proves the helper's join session in that folder
FN world_use_session
    mov [wf_slot], edx
    mov r8d, edx
    mov rdx, rcx
    lea rcx, [wf_keybuf]
    call wf_key_path
    lea rax, [wf_keybuf]
    mov [wf_keypath], rax
END_FN

; ecx = host IPv4 (network order), rdx = destination folder (wide). Downloads the host's world into that folder; needs
; world_use_session first (the host releases the world only to a joined player).
; Returns 0 ok, 1 cannot connect, 2 host has no world to give, 3 invalid reply, 4 checksum mismatch, 5 cannot write, 6 out of memory,
; 7 refused (no joined session, wrong proof, or a host that does not speak the authenticated protocol)
FN world_fetch
    mov r12d, ecx
    mov r13, rdx
    xor r15d, r15d                     ; memory block
    mov qword [wf_sock], 0
    mov rcx, [wf_keypath]
    test rcx, rcx
    jz .refused
    call wa_load_key
    test eax, eax
    jz .refused
    cmp dword [wf_wsa_ready], 0
    jne .ws
    mov ecx, 0x0202
    lea rdx, [wf_wsa]
    call WSAStartup
    mov dword [wf_wsa_ready], 1
.ws:
    cmp dword [wf_connect_ms], 0
    jne .have_ms
    mov dword [wf_connect_ms], 3000
.have_ms:
    mov ecx, 2
    mov edx, 1                         ; SOCK_STREAM
    mov r8d, 6                         ; IPPROTO_TCP
    call socket
    cmp rax, -1
    je .noconn
    mov [wf_sock], rax
    mov dword [wf_one], 1
    mov rcx, [wf_sock]
    mov edx, 0x8004667E                ; FIONBIO: non-blocking, every wait below is a timed poll
    lea r8, [wf_one]
    call ioctlsocket
    lea rdi, [wf_sa]
    xor eax, eax
    mov ecx, 16
    rep stosb
    mov word [wf_sa], 2
    mov word [wf_sa+2], WF_PORT_NET
    mov [wf_sa+4], r12d
    mov rcx, [wf_sock]
    lea rdx, [wf_sa]
    mov r8d, 16
    call connect
    mov rax, [wf_sock]
    mov [wf_pfd], rax
    mov word [wf_pfd+8], 0x0010        ; POLLWRNORM
    mov word [wf_pfd+10], 0
    lea rcx, [wf_pfd]
    mov edx, 1
    mov r8d, [wf_connect_ms]
    call WSAPoll
    cmp eax, 1
    jne .noconn
    test word [wf_pfd+10], 0x0007      ; POLLERR / POLLHUP / POLLNVAL: not connected
    jnz .noconn
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
    mov r8d, 0x3000                    ; MEM_COMMIT | MEM_RESERVE
    mov r9d, 4                         ; PAGE_READWRITE
    call VirtualAlloc
    test rax, rax
    jz .nomem
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
    test eax, eax
    jz .badsum
    lea rsi, [wf_digest]
    lea rdi, [wf_hdr+12]
    mov ecx, 32
    repe cmpsb
    jne .badsum
    lea rcx, [wf_path1]
    lea rdx, [wf_f_part]
    mov r8, r13
    lea r9, [wf_hdr+48]
    call wsprintfW
    lea rcx, [wf_path2]
    lea rdx, [wf_f_final]
    mov r8, r13
    lea r9, [wf_hdr+48]
    call wsprintfW
    lea rcx, [wf_path1]
    call ensure_dirs
    lea rcx, [wf_path1]
    mov rdx, r15
    mov r8d, r14d
    call write_file
    test eax, eax
    jz .nowrite
    lea rcx, [wf_path1]
    lea rdx, [wf_path2]
    mov r8d, 1                         ; MOVEFILE_REPLACE_EXISTING
    call MoveFileExW
    test eax, eax
    jz .nowrite
    xor r14d, r14d
    jmp .close
.nowrite:
    lea rcx, [wf_path1]
    call DeleteFileW
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
    xor edx, edx
    mov r8d, 0x8000                    ; MEM_RELEASE
    call VirtualFree
.nofree:
    mov rcx, [wf_sock]
    test rcx, rcx
    jz .done
    call closesocket
    mov qword [wf_sock], 0
.done:
    mov eax, r14d
END_FN

%include "worldauth.inc"
