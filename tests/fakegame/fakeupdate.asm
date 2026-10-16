; Test stand-in for MistriMulti.exe --update <result file> (the update program the launcher runs when the in-game Update button is
; pressed). It reads fakeupdate.cfg from its working directory (the launcher's folder):
;     <exit code> <sleep ms>\n<result file text>
; writes the text to the result file at once, sleeps, and exits with the code. Used by tests/test_launcher.py (Windows launcher).
bits 64
default rel
extern GetCommandLineW, CommandLineToArgvW, CreateFileW, ReadFile, WriteFile, CloseHandle, Sleep, ExitProcess
section .data
cfgname dw __utf16__("fakeupdate.cfg"), 0
section .bss
argc resd 1
nread resd 1
buf resb 2048
section .text
global start
start:
    sub rsp, 8
    and rsp, -16
    sub rsp, 96
    call GetCommandLineW
    mov rcx, rax
    lea rdx, [argc]
    call CommandLineToArgvW
    mov r15, rax
    cmp dword [argc], 3
    jb .bad
    mov r14, [r15+16]                   ; the result file
    lea rcx, [cfgname]
    mov edx, 0x80000000
    mov r8d, 3
    xor r9d, r9d
    mov qword [rsp+32], 3
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .bad
    mov rbx, rax
    mov rcx, rbx
    lea rdx, [buf]
    mov r8d, 2000
    lea r9, [nread]
    mov qword [rsp+32], 0
    call ReadFile
    mov rcx, rbx
    call CloseHandle
    lea rsi, [buf]
    xor r12d, r12d                      ; exit code
.d1:movzx eax, byte [rsi]
    sub eax, '0'
    cmp eax, 9
    ja .s1
    imul r12d, r12d, 10
    add r12d, eax
    inc rsi
    jmp .d1
.s1:inc rsi
    xor r13d, r13d                      ; sleep ms
.d2:movzx eax, byte [rsi]
    sub eax, '0'
    cmp eax, 9
    ja .s2
    imul r13d, r13d, 10
    add r13d, eax
    inc rsi
    jmp .d2
.s2:inc rsi                             ; the line end
    lea rdi, [buf]
    mov eax, [nread]
    add rdi, rax
    sub rdi, rsi                        ; length of the text
    jbe .nobody
    mov rcx, r14
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .nobody
    mov rbx, rax
    mov rcx, rbx
    mov rdx, rsi
    mov r8, rdi
    lea r9, [nread]
    mov qword [rsp+32], 0
    call WriteFile
    mov rcx, rbx
    call CloseHandle
.nobody:
    mov ecx, r13d
    call Sleep
    mov ecx, r12d
    call ExitProcess
.bad:
    mov ecx, 99
    call ExitProcess
