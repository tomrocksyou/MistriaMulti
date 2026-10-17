; Test stand-in for FieldsOfMistria.exe

bits 64
default rel
extern GetEnvironmentVariableW, GetCommandLineW, CreateFileW, WriteFile, CloseHandle, Sleep, ExitProcess, lstrlenW
section .data
name dw __utf16__("ran.txt"), 0
envname dw __utf16__("EXIT_ON_COMPLETE"), 0
section .bss
written resd 1
envbuf resw 16
section .text
global start
start:
    sub rsp, 8
    and rsp, -16
    sub rsp, 96
    call GetCommandLineW
    mov rbx, rax
    mov rcx, rbx
    call lstrlenW
    lea r12d, [rax*2]
    lea rcx, [name]
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    mov rsi, rax
    mov rcx, rsi
    mov rdx, rbx
    mov r8d, r12d
    lea r9, [written]
    mov qword [rsp+32], 0
    call WriteFile
    mov rcx, rsi
    call CloseHandle
    mov rsi, rbx
.cli:
    cmp word [rsi], 0
    je .nocli
    cmp dword [rsi], '-' | ('c' << 16)
    jne .clinext
    cmp dword [rsi+4], 'l' | ('i' << 16)
    je .iscli
.clinext:
    add rsi, 2
    jmp .cli
.iscli:
    cmp dword [rsi+8], '-' | ('f' << 16)
    je .exit5
    lea rcx, [envname]
    lea rdx, [envbuf]
    mov r8d, 8
    call GetEnvironmentVariableW
    cmp eax, 4
    jne .exit9
    cmp dword [envbuf], 't' | ('r' << 16)
    jne .exit9
    cmp dword [envbuf+4], 'u' | ('e' << 16)
    jne .exit9
    xor ecx, ecx
    call ExitProcess
.exit5:
    mov ecx, 5
    call ExitProcess
.exit9:
    mov ecx, 9
    call ExitProcess
.nocli:
    mov rsi, rbx
    mov r12d, 3000
.scan:
    cmp word [rsi], 0
    je .sleep
    cmp dword [rsi], '-' | ('-' << 16)
    jne .next
    cmp dword [rsi+4], 'q' | ('u' << 16)
    jne .tryslow
    cmp dword [rsi+8], 'i' | ('c' << 16)
    jne .next
    cmp word [rsi+12], 'k'
    je .exit
    jmp .next
.tryslow:
    cmp dword [rsi+4], 's' | ('l' << 16)
    jne .next
    cmp dword [rsi+8], 'o' | ('w' << 16)
    jne .next
    mov r12d, 12000
.next:
    add rsi, 2
    jmp .scan
.sleep:
    mov ecx, r12d
    call Sleep
.exit:
    mov ecx, 7
    call ExitProcess
