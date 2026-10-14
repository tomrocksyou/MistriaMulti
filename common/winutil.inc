; Shared Windows helpers for the updater and the launcher (NASM, Windows x64, wide strings).
; The including program must define:  q_len resd 1  (scratch) and declare WSTR-style data itself.
extern GetFileAttributesW, CreateDirectoryW, CreateFileW, WriteFile, CloseHandle, ReadFile
extern CreateProcessW, lstrlenW, GlobalAlloc, GlobalLock, GlobalUnlock
extern CreateWindowExW, OpenClipboard, EmptyClipboard, SetClipboardData, CloseClipboard
; The including program must also define:  sinfo resb 104, pinfo resb 24  and  clip_static: dw __utf16__("STATIC"), 0

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

FN a_equal                      ; rcx, rdx ASCII strings -> eax 1 if equal
.l: mov al, [rcx]
    cmp al, [rdx]
    jne .no
    test al, al
    jz .yes
    inc rcx
    inc rdx
    jmp .l
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

FN a2i                          ; rcx ASCII decimal (digits only, 1-6) -> eax, or -1
    xor eax, eax
    xor edx, edx
.l: movzx r8d, byte [rcx]
    test r8d, r8d
    jz .e
    sub r8d, '0'
    cmp r8d, 9
    ja .bad
    imul eax, eax, 10
    add eax, r8d
    inc edx
    cmp edx, 6
    ja .bad
    inc rcx
    jmp .l
.e: test edx, edx
    jnz .d
.bad:
    mov eax, -1
.d:
END_FN

FN v_ipv4                       ; rcx ASCII -> eax 1 if a.b.c.d with each part 0-255
    xor r8d, r8d
.group:
    xor edx, edx
    xor eax, eax
.dg:
    movzx r9d, byte [rcx]
    lea r10d, [r9-'0']
    cmp r10d, 9
    ja .sep
    imul eax, eax, 10
    add eax, r10d
    inc edx
    cmp edx, 3
    ja .bad
    cmp eax, 255
    ja .bad
    inc rcx
    jmp .dg
.sep:
    test edx, edx
    jz .bad
    inc r8d
    cmp r9d, '.'
    je .dot
    test r9d, r9d
    jnz .bad
    cmp r8d, 4
    jne .bad
    mov eax, 1
    jmp .d
.dot:
    cmp r8d, 4
    jae .bad
    inc rcx
    jmp .group
.bad:
    xor eax, eax
.d:
END_FN

FN v_room                       ; rcx ASCII -> eax 1 if exactly 8 hex digits
    xor edx, edx
.l: movzx eax, byte [rcx+rdx]
    test al, al
    jz .e
    cmp al, '0'
    jb .bad
    cmp al, '9'
    jbe .ok
    or al, 32
    cmp al, 'a'
    jb .bad
    cmp al, 'f'
    ja .bad
.ok:
    inc edx
    cmp edx, 8
    ja .bad
    jmp .l
.e: cmp edx, 8
    sete al
    movzx eax, al
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; ---------------- processes ----------------
; rcx = writable command line (wide), rdx = working directory (wide) or 0, r8 = inheritable stdout handle or 0, r9d = creation flags
; -> rax = process handle, 0 on failure
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
    mov dword [sinfo+60], 0x100           ; STARTF_USESTDHANDLES
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
    mov [rsp+32], rax                  ; bInheritHandles
    mov eax, r15d
    mov [rsp+40], rax                  ; creation flags
    mov qword [rsp+48], 0              ; environment
    mov [rsp+56], r13                  ; working directory
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

FN wide_to_ascii                ; rcx dst ascii, rdx src wide, r8 max bytes incl. NUL; non-ASCII becomes '?'
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

; Puts the wide string in rcx on the clipboard (owner: a hidden message-only window). eax=1 on success.
FN clip_set
    mov r14, rcx
    call lstrlenW
    lea r13, [rax*2+2]
    mov ecx, 2                      ; GMEM_MOVEABLE
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
    mov qword [rsp+64], -3          ; HWND_MESSAGE
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
    mov ecx, 13                     ; CF_UNICODETEXT
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

FN cut_last_component           ; rcx wide path: truncate at the last '\' or '/'
    mov rsi, rcx
    xor r8, r8                  ; position of last separator + 1
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

; ---------------- small utilities ----------------
FN to_forward                   ; rcx wide string: '\' -> '/' in place
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
