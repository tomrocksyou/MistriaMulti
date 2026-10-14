; Native Linux x86-64 layer. Linux syscalls only: no libc, Wine, or Proton.
bits 64
default rel
%include "abi.inc"
section .bss
platform_argc resq 1
platform_argv resq 1
platform_time resq 2
poll_record resb 8
from_length resd 1
atomic_path resb 4096
section .data
tmp_suffix db '.tmp',0
section .text
global _start
_start:
    mov rax, [rsp]
    mov [platform_argc], rax
    lea rax, [rsp+8]
    mov [platform_argv], rax
    and rsp, -16
    sub rsp, 8
    jmp mistria_main

FN pl_args_init
    mov rax, [platform_argc]
END_FN
FN pl_arg
    cmp rcx, [platform_argc]
    jae .bad
    mov rax, [platform_argv]
    mov rax, [rax+rcx*8]
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN
FN pl_socket
    mov eax, 41
    mov edi, 2
    mov esi, 2 | 0x800 | 0x80000
    xor edx, edx
    syscall
END_FN
FN pl_bind
    mov rdi, rcx
    mov rsi, rdx
    mov edx, 16
    mov eax, 49
    syscall
END_FN
FN pl_recv
    mov rdi, rcx
    mov rsi, rdx
    mov rdx, r8
    mov r8, r9
    mov r10d, 0x40
    lea r9, [from_length]
    mov dword [r9], 16
    mov eax, 45
    syscall
END_FN
FN pl_send
    mov rdi, rcx
    mov rsi, rdx
    mov rdx, r8
    mov r8, r9
    mov r9d, 16
    xor r10d, r10d
    mov eax, 44
    syscall
END_FN
FN pl_poll
    mov [poll_record], ecx
    mov word [poll_record+4], 1
    mov word [poll_record+6], 0
    lea rdi, [poll_record]
    mov esi, 1
    mov eax, 7
    syscall
END_FN
FN pl_ticks
    mov eax, 228
    mov edi, 1
    lea rsi, [platform_time]
    syscall
    test rax, rax
    js .bad
    imul rbx, [platform_time], 1000
    mov rax, [platform_time+8]
    xor edx, edx
    mov ecx, 1000000
    div rcx
    add rax, rbx
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN
FN pl_read
    mov r12, rdx
    mov r13, r8
    mov rdi, rcx
    xor esi, esi
    xor edx, edx
    mov eax, 2
    syscall
    test rax, rax
    js .done
    mov rbx, rax
    xor r14d, r14d
.read:
    xor eax, eax
    mov rdi, rbx
    lea rsi, [r12+r14]
    mov rdx, r13
    sub rdx, r14
    syscall
    cmp rax, -4
    je .read
    test rax, rax
    js .close_bad
    jz .close
    add r14, rax
    cmp r14, r13
    jb .read
.close:
    mov eax, 3
    mov rdi, rbx
    syscall
    mov rax, r14
    jmp .done
.close_bad:
    mov eax, 3
    mov rdi, rbx
    syscall
    mov rax, -1
.done:
END_FN
FN pl_exists
    mov rdi, rcx
    xor esi, esi
    mov eax, 21
    syscall
    test rax, rax
    sete al
    movzx eax, al
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
    lea rdi, [atomic_path]
    mov esi, 0x80241
    mov edx, 0600o
    mov eax, 2
    syscall
    test rax, rax
    js .bad
    mov rbx, rax
.write:
    mov eax, 1
    mov rdi, rbx
    mov rsi, r13
    mov rdx, r14
    syscall
    cmp rax, -4
    je .write
    test rax, rax
    jle .close_bad
    add r13, rax
    sub r14, rax
    jnz .write
    mov eax, 3
    mov rdi, rbx
    syscall
    mov eax, 82
    lea rdi, [atomic_path]
    mov rsi, r12
    syscall
    test rax, rax
    sete al
    movzx eax, al
    jmp .done
.close_bad:
    mov eax, 3
    mov rdi, rbx
    syscall
.bad:
    xor eax, eax
.done:
END_FN
; RCX buffer, RDX length -> EAX 1 when filled with system randomness (getrandom)
FN pl_random
    mov r12, rcx
    mov r13, rdx
.again:
    test r13, r13
    jz .ok
    mov rdi, r12
    mov rsi, r13
    xor edx, edx
    mov eax, 318
    syscall
    cmp rax, -4
    je .again
    test rax, rax
    jle .bad
    add r12, rax
    sub r13, rax
    jmp .again
.ok:
    mov eax, 1
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN
FN pl_print
    mov r12, rcx
    call text_length
    mov rdx, rax
    mov rsi, r12
    mov edi, 1
    mov eax, 1
    syscall
END_FN
FN pl_exit
    mov rdi, rcx
    mov eax, 60
    syscall
END_FN
%include "core.inc"
section .note.GNU-stack noalloc noexec nowrite progbits
