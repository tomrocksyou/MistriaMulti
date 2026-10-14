; Shared Windows helpers for the updater and the launcher (NASM, Windows x64, wide strings).
; The including program must define:  q_len resd 1  (scratch) and declare WSTR-style data itself.
extern GetFileAttributesW, CreateDirectoryW, CreateFileW, WriteFile, CloseHandle, ReadFile

; rcx = wide string, rdx = out buffer (wide)  -> copy zero-terminated wide string
FN wcopy
    mov rsi, rcx
    mov rdi, rdx
.l: lodsw
    stosw
    test ax, ax
    jnz .l
END_FN

; returns rax = pointer to first occurrence of needle in hay, or 0. rcx=hay, rdx=hay_len, r8=needle, r9=needle_len
FN find_bytes
    mov rsi, rcx
    mov rbx, rdx
    sub rbx, r9
    jb .none
    xor r10, r10
.outer:
    cmp r10, rbx
    ja .none
    xor r11, r11
.inner:
    cmp r11, r9
    je .found
    lea rax, [rsi+r10]
    mov al, [rax+r11]
    cmp al, [r8+r11]
    jne .next
    inc r11
    jmp .inner
.next:
    inc r10
    jmp .outer
.found:
    lea rax, [rsi+r10]
    jmp .done
.none:
    xor eax, eax
.done:
END_FN

; Does file (wide path in rcx) exist? rax = 1/0
FN file_exists
    call GetFileAttributesW
    cmp eax, -1
    setne al
    movzx eax, al
END_FN

; r8 = out = wide(rcx) + wide(rdx)
FN join_wide
    mov r12, r8
    mov r13, rdx
    mov rdx, r12
    call wcopy               ; out = first
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

; ---------- small helpers ----------
FN w2i                      ; rcx wide decimal -> eax
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

FN wequal                   ; rcx, rdx wide strings -> eax 1 if equal
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

FN ascii_to_wide            ; rcx dst wide, rdx src bytes, r8 count
    xor r9d, r9d
.l: cmp r9, r8
    jae .e
    movzx eax, byte [rdx+r9]
    mov [rcx+r9*2], ax
    inc r9
    jmp .l
.e: mov word [rcx+r9*2], 0
END_FN

; creates every missing directory in the wide path rcx (the file name itself is not created)
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

FN write_file               ; rcx path, rdx data, r8 length -> eax 1 ok
    mov r12, rdx
    mov r13, r8
    mov edx, 0x40000000     ; GENERIC_WRITE
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 2   ; CREATE_ALWAYS
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

; rcx path (wide), rdx buffer, r8 max bytes -> rax = bytes read, or -1 on failure. Never reads more than r8.
FN read_file
    mov r12, rdx
    mov r13, r8
    mov edx, 0x80000000          ; GENERIC_READ
    mov r8d, 3                   ; FILE_SHARE_READ | FILE_SHARE_WRITE
    xor r9d, r9d
    mov qword [rsp+32], 3        ; OPEN_EXISTING
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
