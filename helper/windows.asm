; Windows platform layer

bits 64
default rel
%define WINDOWS 1
%include "abi.inc"
extern GetCommandLineW, CommandLineToArgvW, WideCharToMultiByte, MultiByteToWideChar
extern GetTickCount64, GetStdHandle, CreateFileW, ReadFile, WriteFile, CloseHandle
extern MoveFileExW, GetFileAttributesW, ExitProcess, LocalFree
extern WSAStartup, WSACleanup, socket, bind, ioctlsocket, closesocket
extern recvfrom, sendto, WSAPoll, BCryptGenRandom

section .bss
platform_argc resd 1
platform_argv resq 1
arg_utf8 resb 4096
path_wide resw 4096
temp_wide resw 4096
atomic_path resb 4096
wsa_data resb 408
poll_record resb 16
platform_count resd 1
from_length resd 1
section .data
nonblocking dd 1
tmp_suffix db '.tmp',0

section .text
FN pl_args_init
    call GetCommandLineW
    mov rcx, rax
    lea rdx, [platform_argc]
    call CommandLineToArgvW
    mov [platform_argv], rax
    test rax, rax
    jz .bad
    mov eax, [platform_argc]
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN

FN pl_arg
    cmp ecx, [platform_argc]
    jae .bad
    mov rax, [platform_argv]
    mov r8, [rax+rcx*8]
    mov ecx, 65001
    xor edx, edx
    mov r9d, -1
    lea rax, [arg_utf8]
    mov [rsp+32], rax
    mov qword [rsp+40], 4096
    mov qword [rsp+48], 0
    mov qword [rsp+56], 0
    call WideCharToMultiByte
    test eax, eax
    jz .bad
    lea rax, [arg_utf8]
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN

FN pl_path
    mov r8, rcx
    mov ecx, 65001
    mov edx, 8
    mov r9d, -1
    lea rax, [path_wide]
    mov [rsp+32], rax
    mov qword [rsp+40], 4096
    call MultiByteToWideChar
    test eax, eax
    jz .done
    lea rax, [path_wide]
.done:
END_FN

FN pl_socket
    mov ecx, 0x202
    lea rdx, [wsa_data]
    call WSAStartup
    test eax, eax
    jnz .bad
    mov ecx, 2
    mov edx, 2
    mov r8d, 17
    call socket
    cmp rax, -1
    je .bad
    mov rbx, rax
    mov rcx, rax
    mov edx, 0x8004667e
    lea r8, [nonblocking]
    call ioctlsocket
    test eax, eax
    jnz .close
    mov rax, rbx
    jmp .done
.close:
    mov rcx, rbx
    call closesocket
.bad:
    mov rax, -1
.done:
END_FN

FN pl_bind
    mov r8d, 16
    call bind
    movsxd rax, eax
END_FN

FN pl_recv
    mov [rsp+32], r9
    lea rax, [from_length]
    mov dword [rax], 16
    mov [rsp+40], rax
    xor r9d, r9d
    call recvfrom
    movsxd rax, eax
END_FN

FN pl_send
    mov [rsp+32], r9
    mov qword [rsp+40], 16
    xor r9d, r9d
    call sendto
    movsxd rax, eax
END_FN

FN pl_poll
    mov [poll_record], rcx
    mov word [poll_record+8], 0x0100
    mov word [poll_record+10], 0
    mov r8d, edx
    mov edx, 1
    lea rcx, [poll_record]
    call WSAPoll
    movsxd rax, eax
END_FN

FN pl_ticks
    call GetTickCount64
END_FN

FN pl_read
    mov r12, rdx
    mov r13, r8
    call pl_path
    test rax, rax
    jz .bad
    mov rcx, rax
    mov edx, 0x80000000
    mov r8d, 7
    xor r9d, r9d
    mov qword [rsp+32], 3
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .bad
    mov rbx, rax
    mov rcx, rax
    mov rdx, r12
    mov r8, r13
    lea r9, [platform_count]
    mov dword [r9], 0
    mov qword [rsp+32], 0
    call ReadFile
    mov r14d, eax
    mov r15d, [platform_count]
    mov rcx, rbx
    call CloseHandle
    test r14d, r14d
    jz .bad
    mov eax, r15d
    jmp .done
.bad:
    mov rax, -1
.done:
END_FN

FN pl_exists
    call pl_path
    test rax, rax
    jz .done
    mov rcx, rax
    call GetFileAttributesW
    cmp eax, -1
    setne al
    movzx eax, al
.done:
END_FN

FN pl_atomic
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    lea rcx, [atomic_path]
    mov rdx, r12
    call text_copy
    mov rcx, rax
    lea rdx, [tmp_suffix]
    call text_copy
    lea rcx, [atomic_path]
    call pl_path
    test rax, rax
    jz .bad
    lea rcx, [temp_wide]
    mov rdx, rax
    mov r8d, 8192
    call bytes_copy
    lea rcx, [temp_wide]
    mov edx, 0x40000000
    mov r8d, 7
    xor r9d, r9d
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .bad
    mov rbx, rax
.write:
    mov rcx, rbx
    mov rdx, r13
    mov r8, r14
    lea r9, [platform_count]
    mov dword [r9], 0
    mov qword [rsp+32], 0
    call WriteFile
    test eax, eax
    jz .close_bad
    mov eax, [platform_count]
    test eax, eax
    jz .close_bad
    add r13, rax
    sub r14, rax
    jnz .write
    mov rcx, rbx
    call CloseHandle
    mov rcx, r12
    call pl_path
    test rax, rax
    jz .bad
    mov rdx, rax
    lea rcx, [temp_wide]
    mov r8d, 1
    call MoveFileExW
    jmp .done
.close_bad:
    mov rcx, rbx
    call CloseHandle
.bad:
    xor eax, eax
.done:
END_FN

FN pl_random
    mov r8d, edx
    mov rdx, rcx
    xor ecx, ecx
    mov r9d, 2
    call BCryptGenRandom
    test eax, eax
    sete al
    movzx eax, al
END_FN

FN pl_print
    mov r12, rcx
    call text_length
    mov r13, rax
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    mov rdx, r12
    mov r8, r13
    lea r9, [platform_count]
    mov qword [rsp+32], 0
    call WriteFile
END_FN

FN pl_exit
    mov r12d, ecx
    mov rcx, [udp_socket]
    cmp rcx, -1
    je .no_socket
    call closesocket
    call WSACleanup
.no_socket:
    mov rcx, [platform_argv]
    test rcx, rcx
    jz .exit
    call LocalFree
.exit:
    mov ecx, r12d
    call ExitProcess
END_FN

%include "core.inc"
