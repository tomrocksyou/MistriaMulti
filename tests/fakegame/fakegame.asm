; Test stand-in for FieldsOfMistria.exe: writes its command line to ran.txt (in its working directory),
; sleeps three seconds, exits with code 7.
bits 64
default rel
extern GetCommandLineW, CreateFileW, WriteFile, CloseHandle, Sleep, ExitProcess, lstrlenW
section .data
name dw __utf16__("ran.txt"), 0
section .bss
written resd 1
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
    ; "--quick" anywhere on the command line skips the sleep
    mov rsi, rbx
.scan:
    cmp word [rsi], 0
    je .sleep
    cmp dword [rsi], '-' | ('-' << 16)
    jne .next
    cmp dword [rsi+4], 'q' | ('u' << 16)
    jne .next
    cmp dword [rsi+8], 'i' | ('c' << 16)
    jne .next
    cmp word [rsi+12], 'k'
    je .exit
.next:
    add rsi, 2
    jmp .scan
.sleep:
    mov ecx, 3000
    call Sleep
.exit:
    mov ecx, 7
    call ExitProcess
