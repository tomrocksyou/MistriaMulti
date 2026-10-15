; SHA-256 in plain assembly (FIPS 180-4). Linux has no system hash function reachable without libc, so the world
; transfer checks its files with this one. Windows uses bcrypt for the same job (common/world.inc).
section .data
align 16
sha_k:
    dd 0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5
    dd 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174
    dd 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da
    dd 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967
    dd 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85
    dd 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070
    dd 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3
    dd 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
sha_init:
    dd 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19

section .bss
sha_h resd 8
sha_w resd 64
sha_tail resb 128

section .text
; Compresses the 64 byte block at rcx into sha_h.
FN sha_block
    mov r11, rcx
    lea rsi, [sha_w]
    xor r8d, r8d
.ld:mov eax, [r11+r8*4]
    bswap eax
    mov [rsi+r8*4], eax
    inc r8d
    cmp r8d, 16
    jb .ld
.ex:mov eax, [rsi+r8*4-8]           ; W[t-2]
    mov edx, eax
    ror edx, 17
    mov ecx, eax
    ror ecx, 19
    xor edx, ecx
    shr eax, 10
    xor edx, eax                    ; small sigma 1
    mov eax, [rsi+r8*4-60]          ; W[t-15]
    mov ecx, eax
    ror ecx, 7
    mov r9d, eax
    ror r9d, 18
    xor ecx, r9d
    shr eax, 3
    xor ecx, eax                    ; small sigma 0
    add edx, ecx
    add edx, [rsi+r8*4-28]          ; W[t-7]
    add edx, [rsi+r8*4-64]          ; W[t-16]
    mov [rsi+r8*4], edx
    inc r8d
    cmp r8d, 64
    jb .ex
    lea rdi, [sha_k]
    lea r9, [sha_h]
    mov r8d, [r9]
    mov r10d, [r9+8]
    mov r11d, [r9+12]
    mov r12d, [r9+16]
    mov r13d, [r9+20]
    mov r14d, [r9+24]
    mov r15d, [r9+28]
    mov r9d, [r9+4]                 ; a=r8 b=r9 c=r10 d=r11 e=r12 f=r13 g=r14 h=r15
    xor ebx, ebx
.rd:mov eax, r12d                   ; big sigma 1 of e: ror6(e ^ ror5(e ^ ror14(e)))
    ror eax, 14
    xor eax, r12d
    ror eax, 5
    xor eax, r12d
    ror eax, 6
    add eax, r15d
    mov ecx, r13d                   ; Ch(e,f,g) = g ^ (e & (f ^ g))
    xor ecx, r14d
    and ecx, r12d
    xor ecx, r14d
    add eax, ecx
    add eax, [rdi+rbx*4]
    add eax, [rsi+rbx*4]
    mov [rsp+48], eax               ; T1
    mov ecx, r8d                    ; big sigma 0 of a: ror2(a ^ ror11(a ^ ror9(a)))
    ror ecx, 9
    xor ecx, r8d
    ror ecx, 11
    xor ecx, r8d
    ror ecx, 2
    mov eax, r8d                    ; Maj(a,b,c) = b ^ ((a ^ b) & (b ^ c))
    xor eax, r9d
    mov edx, r9d
    xor edx, r10d
    and eax, edx
    xor eax, r9d
    add ecx, eax                    ; T2
    mov eax, [rsp+48]
    mov r15d, r14d
    mov r14d, r13d
    mov r13d, r12d
    lea r12d, [r11+rax]
    mov r11d, r10d
    mov r10d, r9d
    mov r9d, r8d
    lea r8d, [rax+rcx]
    inc ebx
    cmp ebx, 64
    jb .rd
    lea rax, [sha_h]
    add [rax], r8d
    add [rax+4], r9d
    add [rax+8], r10d
    add [rax+12], r11d
    add [rax+16], r12d
    add [rax+20], r13d
    add [rax+24], r14d
    add [rax+28], r15d
END_FN

; rcx data, rdx length, r8 = 32 byte output -> eax 1 (cannot fail)
FN sha256_raw
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    lea rsi, [sha_init]
    lea rdi, [sha_h]
    mov ecx, 8
    rep movsd
    mov r15, r13
    shr r15, 6                      ; full blocks
.blocks:
    test r15, r15
    jz .tail
    mov rcx, r12
    call sha_block
    add r12, 64
    dec r15
    jmp .blocks
.tail:
    mov rcx, r13
    and ecx, 63                     ; bytes left over
    mov ebx, ecx
    lea rdi, [sha_tail]
    mov rsi, r12
    rep movsb                       ; rcx = leftover count (set above)
    lea rdi, [sha_tail]
    mov byte [rdi+rbx], 0x80
    lea rcx, [rbx+1]
    lea rdi, [sha_tail]
    lea rdi, [rdi+rbx+1]
    xor eax, eax
    mov edx, 128
    sub edx, ecx
    mov ecx, edx
    rep stosb
    mov r15d, 64                    ; blocks in the tail: one if the length fits behind the 0x80 byte, else two
    cmp ebx, 56
    jb .one
    mov r15d, 128
.one:
    lea rdi, [sha_tail]
    mov rax, r13
    shl rax, 3
    bswap rax
    mov [rdi+r15-8], rax
    xor r12d, r12d
.t: lea rcx, [sha_tail]
    add rcx, r12
    call sha_block
    add r12d, 64
    cmp r12d, r15d
    jb .t
    lea rsi, [sha_h]
    xor ecx, ecx
.out:
    mov eax, [rsi+rcx*4]
    bswap eax
    mov [r14+rcx*4], eax
    inc ecx
    cmp ecx, 8
    jb .out
    mov eax, 1
END_FN
