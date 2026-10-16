; Test stand-in for curl.exe (Windows): finds  -o "<file>"  in its command line, writes "version 0.4.7" there (the first line of a release
; list) and its own command line, as UTF-16, to "<file>.args". Exit code 0. Used by tests/test_launcher.py: the Windows launcher runs
; %SystemRoot%\System32\curl.exe for the daily release check, and the test puts this program there.
bits 64
default rel
extern GetCommandLineW, CreateFileW, WriteFile, CloseHandle, ExitProcess, lstrlenW
section .data
body db 'version 0.4.7', 10
body_len equ $ - body
suffix dw __utf16__(".args"), 0
section .bss
buf resw 1100
nwritten resd 1
section .text
global start
start:
    sub rsp, 8
    and rsp, -16
    sub rsp, 96
    call GetCommandLineW
    mov rbx, rax
    mov rsi, rbx
.scan:
    movzx eax, word [rsi]
    test eax, eax
    jz .done
    cmp ax, '-'
    jne .next
    cmp word [rsi+2], 'o'
    jne .next
    cmp word [rsi+4], ' '
    jne .next
    cmp word [rsi+6], '"'
    je .found
.next:
    add rsi, 2
    jmp .scan
.found:
    add rsi, 8
    lea rdi, [buf]
.copy:
    movzx eax, word [rsi]
    test eax, eax
    jz .done
    cmp ax, '"'
    je .copied
    mov [rdi], ax
    add rsi, 2
    add rdi, 2
    jmp .copy
.copied:
    mov word [rdi], 0
    mov r12, rdi                        ; end of the path
    lea rcx, [buf]
    lea rdx, [body]
    mov r8d, body_len
    call write_out
    lea rsi, [suffix]                   ; <file>.args
    mov rdi, r12
.sfx:
    lodsw
    stosw
    test ax, ax
    jnz .sfx
    mov rcx, rbx
    call lstrlenW
    lea r8d, [rax*2]
    lea rcx, [buf]
    mov rdx, rbx
    call write_out
.done:
    xor ecx, ecx
    call ExitProcess

write_out:                              ; rcx = wide path, rdx = data, r8d = byte count
    push rbx
    push rsi
    sub rsp, 104
    mov rsi, rdx
    mov ebx, r8d
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .out
    mov rdi, rax
    mov rcx, rdi
    mov rdx, rsi
    mov r8d, ebx
    lea r9, [nwritten]
    mov qword [rsp+32], 0
    call WriteFile
    mov rcx, rdi
    call CloseHandle
.out:
    add rsp, 104
    pop rsi
    pop rbx
    ret
