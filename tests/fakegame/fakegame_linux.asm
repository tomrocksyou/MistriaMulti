; Test stand-in for the Linux game

bits 64
default rel
section .data
name db 'ran.txt',0
nl db 10
quick db '--quick',0
slow db '--slow',0
section .bss
argc resq 1
argv resq 1
fd resq 1
ts resq 2
section .text
global _start
_start:
    mov rax, [rsp]
    mov [argc], rax
    lea rax, [rsp+8]
    mov [argv], rax
    lea rdi, [name]
    mov esi, 0x241
    mov edx, 0644o
    mov eax, 2
    syscall
    mov [fd], rax
    mov r12d, 3000
    xor r13d, r13d
.arg:
    cmp r13, [argc]
    jae .written
    mov rax, [argv]
    mov rbx, [rax+r13*8]
    xor edx, edx
.len:
    cmp byte [rbx+rdx], 0
    je .got
    inc rdx
    jmp .len
.got:
    mov rdi, [fd]
    mov rsi, rbx
    mov eax, 1
    syscall
    mov rdi, [fd]
    lea rsi, [nl]
    mov edx, 1
    mov eax, 1
    syscall
    lea rsi, [quick]
    mov rdi, rbx
    call same
    test eax, eax
    jz .notq
    mov r12d, 0
.notq:
    lea rsi, [slow]
    mov rdi, rbx
    call same
    test eax, eax
    jz .nots
    mov r12d, 12000
.nots:
    inc r13
    jmp .arg
.written:
    mov rdi, [fd]
    mov eax, 3
    syscall
    test r12d, r12d
    jz .exit
    mov eax, r12d
    xor edx, edx
    mov ecx, 1000
    div ecx
    mov [ts], rax
    imul edx, edx, 1000000
    mov [ts+8], rdx
    lea rdi, [ts]
    xor esi, esi
    mov eax, 35
    syscall
.exit:
    mov edi, 7
    mov eax, 231
    syscall

same:
.l: mov al, [rdi]
    cmp al, [rsi]
    jne .no
    test al, al
    jz .yes
    inc rdi
    inc rsi
    jmp .l
.yes:
    mov eax, 1
    ret
.no:
    xor eax, eax
    ret
section .note.GNU-stack noalloc noexec nowrite progbits
