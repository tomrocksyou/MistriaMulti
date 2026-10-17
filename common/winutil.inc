; Shared Windows helpers

extern GetFileAttributesW, CreateDirectoryW, CreateFileW, WriteFile, CloseHandle, ReadFile
extern CreateProcessW, lstrlenW, GlobalAlloc, GlobalLock, GlobalUnlock
extern CreateWindowExW, OpenClipboard, EmptyClipboard, SetClipboardData, CloseClipboard
%include "textutil.inc"

FN wcopy
    mov rsi, rcx
    mov rdi, rdx
.l: lodsw
    stosw
    test ax, ax
    jnz .l
END_FN

FN file_exists
    call GetFileAttributesW
    cmp eax, -1
    setne al
    movzx eax, al
END_FN

FN join_wide
    mov r12, r8
    mov r13, rdx
    mov rdx, r12
    call wcopy
    mov rdi, r12
.find_end:
    cmp word [rdi], 0
    je .at_end
    add rdi, 2
    jmp .find_end
.at_end:
    mov rsi, r13
.cp: lodsw
    stosw
    test ax, ax
    jnz .cp
END_FN

FN w2i
    xor eax, eax
.l: movzx edx, word [rcx]
    sub edx, '0'
    cmp edx, 9
    ja .d
    imul eax, eax, 10
    add eax, edx
    add rcx, 2
    jmp .l
.d:
END_FN

FN wequal
.l: mov ax, [rcx]
    cmp ax, [rdx]
    jne .no
    test ax, ax
    jz .yes
    add rcx, 2
    add rdx, 2
    jmp .l
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN ascii_to_wide
    xor r9d, r9d
.l: cmp r9, r8
    jae .e
    movzx eax, byte [rdx+r9]
    mov [rcx+r9*2], ax
    inc r9
    jmp .l
.e: mov word [rcx+r9*2], 0
END_FN

FN ensure_dirs
    mov rsi, rcx
    mov r12d, 3
.l: movzx eax, word [rsi+r12*2]
    test ax, ax
    jz .d
    cmp ax, '\'
    jne .n
    mov word [rsi+r12*2], 0
    mov rcx, rsi
    xor edx, edx
    call CreateDirectoryW
    mov word [rsi+r12*2], '\'
.n: inc r12d
    jmp .l
.d:
END_FN

FN write_file
    mov r12, rdx
    mov r13, r8
    mov edx, 0x40000000
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 2
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .fail
    mov rbx, rax
    mov rcx, rbx
    mov rdx, r12
    mov r8, r13
    lea r9, [q_len]
    mov qword [rsp+32], 0
    call WriteFile
    mov r14d, eax
    mov rcx, rbx
    call CloseHandle
    test r14d, r14d
    jz .fail
    mov eax, [q_len]
    cmp rax, r13
    jne .fail
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN read_file
    mov r12, rdx
    mov r13, r8
    mov edx, 0x80000000
    mov r8d, 3
    xor r9d, r9d
    mov qword [rsp+32], 3
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .fail
    mov rbx, rax
    mov rcx, rbx
    mov rdx, r12
    mov r8, r13
    lea r9, [q_len]
    mov qword [rsp+32], 0
    call ReadFile
    mov r14d, eax
    mov rcx, rbx
    call CloseHandle
    test r14d, r14d
    jz .fail
    mov eax, [q_len]
    jmp .d
.fail:
    mov rax, -1
.d:
END_FN

FN spawn
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    mov r15d, r9d
    lea rdi, [sinfo]
    xor eax, eax
    mov ecx, 104
    rep stosb
    mov dword [sinfo], 104
    test r14, r14
    jz .nostd
    mov dword [sinfo+60], 0x100
    mov [sinfo+88], r14
    mov [sinfo+96], r14
.nostd:
    xor ecx, ecx
    mov rdx, r12
    xor r8d, r8d
    xor r9d, r9d
    xor eax, eax
    test r14, r14
    setnz al
    mov [rsp+32], rax
    mov eax, r15d
    mov [rsp+40], rax
    mov qword [rsp+48], 0
    mov [rsp+56], r13
    lea rax, [sinfo]
    mov [rsp+64], rax
    lea rax, [pinfo]
    mov [rsp+72], rax
    call CreateProcessW
    test eax, eax
    jz .fail
    mov rcx, [pinfo+8]
    call CloseHandle
    mov rax, [pinfo]
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN wide_to_ascii
    xor r9d, r9d
    dec r8
.l: cmp r9, r8
    jae .e
    movzx eax, word [rdx+r9*2]
    test eax, eax
    jz .e
    cmp eax, 126
    jbe .ok
    mov eax, '?'
.ok:
    mov [rcx+r9], al
    inc r9
    jmp .l
.e: mov byte [rcx+r9], 0
END_FN

FN clip_set
    mov r14, rcx
    call lstrlenW
    lea r13, [rax*2+2]
    mov ecx, 2
    mov rdx, r13
    call GlobalAlloc
    test rax, rax
    jz .bad
    mov r12, rax
    mov rcx, r12
    call GlobalLock
    test rax, rax
    jz .bad
    mov rdi, rax
    mov rsi, r14
    mov rcx, r13
    rep movsb
    mov rcx, r12
    call GlobalUnlock
    xor ecx, ecx
    lea rdx, [clip_static]
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 0
    mov qword [rsp+40], 0
    mov qword [rsp+48], 0
    mov qword [rsp+56], 0
    mov qword [rsp+64], -3
    mov qword [rsp+72], 0
    mov qword [rsp+80], 0
    mov qword [rsp+88], 0
    call CreateWindowExW
    test rax, rax
    jz .bad
    mov rbx, rax
    mov rcx, rbx
    call OpenClipboard
    test eax, eax
    jz .bad
    call EmptyClipboard
    mov ecx, 13
    mov rdx, r12
    call SetClipboardData
    mov r15d, eax
    call CloseClipboard
    test r15, r15
    setnz al
    movzx eax, al
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

FN cut_last_component
    mov rsi, rcx
    xor r8, r8
    xor r9d, r9d
.l: movzx eax, word [rsi+r9*2]
    test ax, ax
    jz .e
    cmp ax, '\'
    je .s
    cmp ax, '/'
    jne .n
.s: lea r8, [r9+1]
.n: inc r9
    jmp .l
.e: test r8, r8
    jz .d
    dec r8
    mov word [rsi+r8*2], 0
.d:
END_FN

FN to_forward
.l: movzx eax, word [rcx]
    test ax, ax
    jz .d
    cmp ax, '\'
    jne .n
    mov word [rcx], '/'
.n: add rcx, 2
    jmp .l
.d:
END_FN
