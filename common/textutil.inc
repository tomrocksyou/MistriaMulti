; Text and number helpers shared by the Windows and Linux programs (NASM, x86-64, ASCII only; no operating-system calls).
; Included by common/winutil.inc (Windows) and linux/lib.inc (Linux). Uses the FN/END_FN macros from abi.inc.

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

FN v_pass                       ; rcx ASCII -> eax 1 if empty (no password) or 1 to 64 printable ASCII characters without spaces
    xor edx, edx
.l: movzx eax, byte [rcx+rdx]
    test al, al
    jz .ok
    cmp al, 33
    jb .bad
    cmp al, 126
    ja .bad
    inc edx
    cmp edx, 64
    jbe .l
.bad:
    xor eax, eax
    jmp .d
.ok:
    mov eax, 1
.d:
END_FN

; rcx = ASCII file name -> eax 1 only for  game-<digits>-(autosave|<digits>).sav  (nothing else: no paths, no ".old.sav")
FN wf_valid_name
    mov rsi, rcx
    cmp dword [rsi], 'game'
    jne .no
    cmp byte [rsi+4], '-'
    jne .no
    add rsi, 5
    xor ecx, ecx
.d1:
    movzx eax, byte [rsi+rcx]
    sub eax, '0'
    cmp eax, 9
    ja .d1end
    inc ecx
    cmp ecx, 12
    jbe .d1
    jmp .no
.d1end:
    test ecx, ecx
    jz .no
    cmp byte [rsi+rcx], '-'
    jne .no
    lea rsi, [rsi+rcx+1]
    cmp dword [rsi], 'auto'
    jne .digits
    cmp dword [rsi+4], 'save'
    jne .no
    add rsi, 8
    jmp .ext
.digits:
    xor ecx, ecx
.d2:
    movzx eax, byte [rsi+rcx]
    sub eax, '0'
    cmp eax, 9
    ja .d2end
    inc ecx
    cmp ecx, 12
    jbe .d2
    jmp .no
.d2end:
    test ecx, ecx
    jz .no
    add rsi, rcx
.ext:
    cmp dword [rsi], '.sav'
    jne .no
    cmp byte [rsi+4], 0
    jne .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN
