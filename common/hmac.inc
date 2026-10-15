; HMAC-SHA256 (RFC 2104) for the launchers, the managers and the updater, built on their own sha256_raw
; (bcrypt on Windows, linux/sha256.inc on Linux). Same primitive as the helper's join handshake (helper/include/auth.inc).
HMAC_MAX equ 256                       ; longest message

section .bss
hm2_in resb 64+HMAC_MAX
hm2_out resb 96
hm2_mid resb 32

section .text
; rcx key (32 bytes), rdx message, r8 length (at most HMAC_MAX), r9 = 32-byte output -> eax 1 ok / 0 too long or hash failure
FN hmac_sha256
    cmp r8, HMAC_MAX
    ja .fail
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    mov r15, r9
    lea rdi, [hm2_in]
    xor ecx, ecx
.ipad:
    movzx eax, byte [r12+rcx]
    xor al, 0x36
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 32
    jb .ipad
.ipad2:
    mov byte [rdi+rcx], 0x36
    inc ecx
    cmp ecx, 64
    jb .ipad2
    lea rdi, [hm2_in+64]
    mov rsi, r13
    mov rcx, r14
    cld
    rep movsb
    lea rcx, [hm2_in]
    lea rdx, [r14+64]
    lea r8, [hm2_mid]
    call sha256_raw
    test eax, eax
    jz .fail
    lea rdi, [hm2_out]
    xor ecx, ecx
.opad:
    movzx eax, byte [r12+rcx]
    xor al, 0x5C
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 32
    jb .opad
.opad2:
    mov byte [rdi+rcx], 0x5C
    inc ecx
    cmp ecx, 64
    jb .opad2
    lea rdi, [hm2_out+64]
    lea rsi, [hm2_mid]
    mov ecx, 32
    rep movsb
    lea rcx, [hm2_out]
    mov edx, 96
    mov r8, r15
    call sha256_raw
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN
