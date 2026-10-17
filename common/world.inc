; Host-world transfer

extern ioctlsocket, connect, send, recv, closesocket, socket, WSAPoll, WSAStartup, shutdown
extern VirtualAlloc, VirtualFree, MoveFileExW, DeleteFileW, wsprintfW
extern BCryptOpenAlgorithmProvider, BCryptHash, BCryptCloseAlgorithmProvider, BCryptGenRandom

WF_PORT_NET equ 0x5F1E
WF_MAX_FILE equ 209715200

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
wf_host_flags resd 1
wf_host_id resd 1
wf_got_id resd 1
wf_path1 resw 1040
wf_path2 resw 1040

section .text

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

FN wf_random
    mov r8, rdx
    mov rdx, rcx
    xor ecx, ecx
    mov r9d, 2
    call BCryptGenRandom
    test eax, eax
    sete al
    movzx eax, al
END_FN

FN wf_key_path
    mov r9d, r8d
    mov r8, rdx
    lea rdx, [wf_f_key]
    call wsprintfW
END_FN

FN world_use_session
    mov [wf_slot], edx
    mov r8d, edx
    mov rdx, rcx
    lea rcx, [wf_keybuf]
    call wf_key_path
    lea rax, [wf_keybuf]
    mov [wf_keypath], rax
END_FN

FN world_fetch
    mov r12d, ecx
    mov r13, rdx
    mov dword [wf_host_flags], 0
    mov dword [wf_host_id], 0
    mov dword [wf_got_id], 0
    xor r15d, r15d
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
    mov edx, 1
    mov r8d, 6
    call socket
    cmp rax, -1
    je .noconn
    mov [wf_sock], rax
    mov dword [wf_one], 1
    mov rcx, [wf_sock]
    mov edx, 0x8004667E
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
    mov word [wf_pfd+8], 0x0010
    mov word [wf_pfd+10], 0
    lea rcx, [wf_pfd]
    mov edx, 1
    mov r8d, [wf_connect_ms]
    call WSAPoll
    cmp eax, 1
    jne .noconn
    test word [wf_pfd+10], 0x0007
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
    call wa_check_header
    test eax, eax
    jz .refused
    movzx eax, byte [wf_hdr+6]
    mov [wf_host_flags], eax
    mov eax, [wf_hdr+44]
    mov [wf_host_id], eax
    movzx eax, byte [wf_hdr+5]
    test eax, eax
    jz .status_ok
    cmp eax, 4
    je .unsaved
    cmp eax, 1
    jne .bad
    mov r14d, 2
    jmp .close
.unsaved:
    mov r14d, 8
    jmp .close
.status_ok:
    mov r14d, [wf_hdr+8]
    test r14d, r14d
    jz .bad
    cmp r14d, WF_MAX_FILE
    ja .bad
    mov byte [wf_hdr+111], 0
    lea rcx, [wf_hdr+48]
    call wf_valid_name
    test eax, eax
    jz .bad
    xor ecx, ecx
    mov edx, r14d
    mov r8d, 0x3000
    mov r9d, 4
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
    mov r8d, 1
    call MoveFileExW
    test eax, eax
    jz .nowrite
    lea rcx, [wf_hdr+48]
    call wf_name_id
    mov [wf_got_id], eax
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
    mov r8d, 0x8000
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
