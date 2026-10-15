; MistriaMulti join authentication, identity keys and abuse limits (docs/SECURITY.md).
;
; Layer choice: the UDP helper is the only code that sees every datagram, so slot admission and per-packet
; authentication live here, in assembly, on top of the SHA-256 the launchers already use (linux/sha256.inc).
; The game's GML has no hash function and no randomness it could trust.
;
; Join handshake (all integers little-endian; every packet starts 'MSAU', type byte, version byte 1):
;   HELLO     guest -> host  128 bytes  session code, slot, 16 byte client nonce (padded so no reply is larger)
;   CHALLENGE host  -> guest  64 bytes  flags (bit 0: password), window id, stateless cookie, host fingerprint
;   PROOF     guest -> host  128 bytes  cookie echo, guest fingerprint, masked key, 16 byte tag
;   WELCOME   host  -> guest  48 bytes  16 byte tag proving the host knows the same keys
;   REJECT / RESYNC (16 bytes): why the join failed / "I do not know you, say HELLO again" (not authenticated)
; Keys: IK is a random per-install secret (a file). The guest's key for one host is K = HMAC(IK, "MMBIND1" | host
; fingerprint), so a host that learns K cannot impersonate the guest to another host. The guest fingerprint is
; SHA256("MMFP2" | K)[0:16]: it names K, so nobody can claim a fingerprint without knowing its key. PWK is the
; stretched room password (32 zero bytes when there is none). AK = HMAC(PWK, K) is the authentication key.
; The first time a host sees a fingerprint, the guest sends K masked with HMAC(PWK, ...): with a password only
; a password holder can read it; without one it is in the clear (trust on first use, documented).
; After the handshake every game datagram ('MSMP' version 2) carries a 16 byte HMAC tag under the session key.

%include "sha256.inc"

section .data
lbl_fp1 db 'MMFP1',0
lbl_fp2 db 'MMFP2',0
lbl_bind db 'MMBIND1',0
lbl_reg db 'MMREG1',0
lbl_proof db 'MMPROOF1',0
lbl_sk db 'MMSK1',0
lbl_welcome db 'MMWELCOME1',0
lbl_world db 'MMWORLD1',0
lbl_ck db 'MMCK1',0
hex_digits db '0123456789abcdef'
auth_cfg_suffix db '/auth.cfg',0
auth_json_suffix db '/auth_0.json',0
world_key_suffix db '/world_0.key',0
pfx_key db 'key=',0
pfx_keys db 'keys=',0
pfx_deny db 'deny=',0
pfx_pass db 'pass=',0
j_auth_fp db '{"fp":"',0
j_auth_gen db '","gen":',0
j_auth_state db ',"state":',0
j_auth_reject db ',"reject":',0
j_auth_end db '}',0
status_auth db ',"auth":',0
status_reject db ',"reject":',0
status_limited db ',"limited":',0
status_authfail db ',"authfail":',0
status_denied db ',"denied":',0
status_unknown db ',"unknown":',0
bad_password db 'Invalid host password in auth.cfg (1 to 64 printable characters, no spaces).',10,0
random_error db 'The system random number generator is unavailable.',10,0
align 8
cfg_table:
    dq pfx_key, key_path, 1024
    dq pfx_keys, keys_path, 1024
    dq pfx_deny, deny_path, 1024
    dq pfx_pass, pass_text, 65

section .bss
align 16
hm_in resb 64+HM_MAX+16
hm_mid resb 32
hm_out resb 96
hm_res resb 32
mb_len resd 1
mb_over resd 1
sc resb 16
install_key resb 32
my_fp resb 16
cookie_secret resb 32
pwk resb 32
pw_buf resb 128
pass_text resb 72
pass_len resd 1
key_path resb 1032
keys_path resb 1032
deny_path resb 1032
auth_cfg_path resb 2112
cfg_bytes resb CFG_BYTES+8
auth_tab resb A_SIZE*MAX_PLAYERS
auth_out resb 160
ks_count resd 1
ks_tab resb KS_MAX*KS_ENTRY
ks_text resb KS_TEXT
dn_fp_count resd 1
dn_ip_count resd 1
dn_fp resb 16*DN_MAX
dn_ip resd DN_MAX
dn_text resb 8200
dn_token resb 72
replay_ring resb 16*8
replay_next resd 1
gb_tokens resd 2
gb_last resq 2
k_buf resb 32
ak_buf resb 32
m_buf resb 32
t_fp resb 16
is_new resd 1
g_state resd 1
g_reject resd 1
g_gen resd 1
g_last_hello resq 1
g_last_rx resq 1
g_proof_at resq 1
g_welcomed resq 1
g_cnonce resb 16
g_sk resb 32
g_wtag resb 16
g_hfp resb 16
g_pwk resb 32
g_pwk_for resb 16
g_pwk_valid resd 1
resync_last resq 1
limited_packets resq 1
auth_failures resq 1
denied_joins resq 1
unknown_sources resq 1
auth_json resb 160
auth_path resb 2112
world_key resb 32
world_path resb 2112

section .text
; ---------------------------------------------------------------------------------------------------------
; small helpers

; slot ECX -> auth record in RAX
FN auth_pointer
    imul rax, rcx, A_SIZE
    lea rdx, [auth_tab]
    add rax, rdx
END_FN

; RCX a, RDX b, R8 length -> EAX 1 if equal; the running time does not depend on where they differ
FN ct_equal
    xor eax, eax
    xor r9d, r9d
.loop:
    cmp r9, r8
    jae .done
    movzx r10d, byte [rcx+r9]
    xor r10b, [rdx+r9]
    or al, r10b
    inc r9
    jmp .loop
.done:
    test al, al
    sete al
    movzx eax, al
END_FN

; Message builder for HMAC and SHA input: it lives in hm_in+64 so hashing needs no further copy.
FN mb_add
    mov eax, [mb_len]
    mov r8d, eax
    add r8d, edx
    cmp r8d, HM_MAX
    ja .over
    lea rdi, [hm_in+64]
    add rdi, rax
    mov rsi, rcx
    mov ecx, edx
    cld
    rep movsb
    mov [mb_len], r8d
    jmp .done
.over:
    mov dword [mb_over], 1
.done:
END_FN

; NUL terminated string RCX
FN mb_str
    mov r12, rcx
    call text_length
    mov rcx, r12
    mov edx, eax
    call mb_add
END_FN

; HMAC-SHA256 with the 32 byte key RCX over the message built so far -> 32 bytes at RDX
FN mb_hmac
    mov r12, rcx
    mov r13, rdx
    lea rdi, [hm_in]
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
    lea rcx, [hm_in]
    mov edx, [mb_len]
    add edx, 64
    lea r8, [hm_mid]
    call sha256_raw
    lea rdi, [hm_out]
    xor ecx, ecx
.opad:
    movzx eax, byte [r12+rcx]
    xor al, 0x5c
    mov [rdi+rcx], al
    inc ecx
    cmp ecx, 32
    jb .opad
.opad2:
    mov byte [rdi+rcx], 0x5c
    inc ecx
    cmp ecx, 64
    jb .opad2
    lea rsi, [hm_mid]
    lea rdi, [hm_out+64]
    mov ecx, 32
    cld
    rep movsb
    lea rcx, [hm_out]
    mov edx, 96
    mov r8, r13
    call sha256_raw
END_FN

; SHA-256 of label (RCX, NUL terminated) | data (RDX, length R8) -> first 16 bytes to R9
FN make_fp
    mov r12, rdx
    mov r13, r8
    mov r14, r9
    mov r15, rcx
    mov dword [mb_len], 0
    mov rcx, r15
    call mb_str
    mov rcx, r12
    mov edx, r13d
    call mb_add
    lea rcx, [hm_in+64]
    mov edx, [mb_len]
    lea r8, [hm_res]
    call sha256_raw
    mov rcx, r14
    lea rdx, [hm_res]
    mov r8d, 16
    call bytes_copy
END_FN

; RCX destination, RDX source, R8 byte count -> lower-case hex and a NUL; RAX = the NUL
FN hex_put
    lea r9, [hex_digits]
.loop:
    test r8, r8
    jz .done
    movzx eax, byte [rdx]
    mov r10d, eax
    shr eax, 4
    mov al, [r9+rax]
    mov [rcx], al
    and r10d, 15
    mov al, [r9+r10]
    mov [rcx+1], al
    add rcx, 2
    inc rdx
    dec r8
    jmp .loop
.done:
    mov byte [rcx], 0
    mov rax, rcx
END_FN

; RCX text (exactly 2*R8 hex digits), RDX destination, R8 byte count -> EAX 1 if valid
FN hex_get
    xor r9d, r9d
.loop:
    cmp r9, r8
    jae .good
    movzx eax, byte [rcx+r9*2]
    cmp eax, '0'
    jb .bad
    cmp eax, '9'
    jbe .hd
    or eax, 32
    cmp eax, 'a'
    jb .bad
    cmp eax, 'f'
    ja .bad
    sub eax, 'a'-10
    jmp .hs
.hd:
    sub eax, '0'
.hs:
    shl eax, 4
    mov r10d, eax
    movzx eax, byte [rcx+r9*2+1]
    cmp eax, '0'
    jb .bad
    cmp eax, '9'
    jbe .ld
    or eax, 32
    cmp eax, 'a'
    jb .bad
    cmp eax, 'f'
    ja .bad
    sub eax, 'a'-10
    jmp .ls
.ld:
    sub eax, '0'
.ls:
    or eax, r10d
    mov [rdx+r9], al
    inc r9
    jmp .loop
.good:
    mov eax, 1
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN

; Dotted IPv4 text RCX -> EAX in network memory order; carry set when invalid
FN parse_ip4
    lea rdi, [sc+8]
    xor r8d, r8d
.octet:
    xor eax, eax
    xor r9d, r9d
.digit:
    movzx edx, byte [rcx]
    cmp edx, '0'
    jb .end_octet
    cmp edx, '9'
    ja .end_octet
    sub edx, '0'
    imul eax, 10
    add eax, edx
    cmp eax, 255
    ja .bad
    inc r9d
    cmp r9d, 3
    ja .bad
    inc rcx
    jmp .digit
.end_octet:
    test r9d, r9d
    jz .bad
    mov [rdi+r8], al
    inc r8d
    cmp r8d, 4
    je .finish
    cmp byte [rcx], '.'
    jne .bad
    inc rcx
    jmp .octet
.finish:
    cmp byte [rcx], 0
    jne .bad
    mov eax, [sc+8]
    clc
    jmp .done
.bad:
    stc
.done:
END_FN

; RCX string, RDX prefix (both NUL terminated) -> EAX prefix length if the string starts with it, else 0
FN prefix_len
    xor eax, eax
.loop:
    mov r8b, [rdx+rax]
    test r8b, r8b
    jz .done
    cmp r8b, [rcx+rax]
    jne .no
    inc eax
    jmp .loop
.no:
    xor eax, eax
.done:
END_FN

; RCX destination, RDX length: fills with system randomness, EAX 1 on success (platform call, see linux/windows.asm)

; ---------------------------------------------------------------------------------------------------------
; password stretching: x = SHA256(x | hfp | password), PW_ROUNDS times (RCX host fingerprint, RDX 32 byte output)
FN pwk_derive
    mov r12, rdx
    mov r13, rcx
    lea rdi, [pw_buf]
    xor eax, eax
    mov ecx, 32
    cld
    rep stosb
    mov rsi, r13
    mov ecx, 16
    rep movsb
    lea rsi, [pass_text]
    mov ecx, [pass_len]
    rep movsb
    mov r13d, [pass_len]
    add r13d, 48
    mov ebx, PW_ROUNDS
.round:
    lea rcx, [pw_buf]
    mov edx, r13d
    lea r8, [pw_buf]
    call sha256_raw
    dec ebx
    jnz .round
    mov rcx, r12
    lea rdx, [pw_buf]
    mov r8d, 32
    call bytes_copy
END_FN

; ---------------------------------------------------------------------------------------------------------
; token buckets (abuse limits). Time is the helper's monotonic clock in milliseconds.

; RCX auth record: refills 40 packet tokens and 3 frame tokens per 100 ms (capped at 800 and 60)
FN bucket_refill
    mov rax, [now_ms]
    sub rax, [rcx+A_LAST]
    jb .reset
    cmp rax, 100
    jb .done
    xor edx, edx
    mov r8d, 100
    div r8
    mov r9, [now_ms]
    sub r9, rdx
    mov [rcx+A_LAST], r9
    cmp rax, 20
    jbe .steps
    mov eax, 20
.steps:
    imul r8d, eax, PKT_BUCKET_ADD
    add r8d, [rcx+A_PKT]
    cmp r8d, PKT_BUCKET_CAP
    jbe .pkt
    mov r8d, PKT_BUCKET_CAP
.pkt:
    mov [rcx+A_PKT], r8d
    imul r8d, eax, FRM_BUCKET_ADD
    add r8d, [rcx+A_FRM]
    cmp r8d, FRM_BUCKET_CAP
    jbe .frm
    mov r8d, FRM_BUCKET_CAP
.frm:
    mov [rcx+A_FRM], r8d
    jmp .done
.reset:
    mov rax, [now_ms]
    mov [rcx+A_LAST], rax
.done:
END_FN

; RCX auth record -> EAX 1 and one packet token spent, or 0
FN bucket_packet
    mov r12, rcx
    call bucket_refill
    mov eax, [r12+A_PKT]
    test eax, eax
    jz .no
    dec eax
    mov [r12+A_PKT], eax
    mov eax, 1
    jmp .done
.no:
    xor eax, eax
.done:
END_FN

; RCX auth record -> EAX 1 and one completed-frame token spent, or 0
FN bucket_frame
    mov r12, rcx
    call bucket_refill
    mov eax, [r12+A_FRM]
    test eax, eax
    jz .no
    dec eax
    mov [r12+A_FRM], eax
    mov eax, 1
    jmp .done
.no:
    xor eax, eax
.done:
END_FN

; Handshake packets from strangers: ECX 0 (HELLO) or 1 (PROOF), each with its own bucket of 30 per second (burst 30),
; so a flood of HELLOs cannot stop a player who already holds a cookie from finishing the join.
FN take_global
    lea r10, [gb_tokens]
    lea r11, [gb_last]
    lea r10, [r10+rcx*4]
    lea r11, [r11+rcx*8]
    mov rax, [now_ms]
    sub rax, [r11]
    jb .reset
    cmp rax, 100
    jb .take
    xor edx, edx
    mov r8d, 100
    div r8
    mov r9, [now_ms]
    sub r9, rdx
    mov [r11], r9
    cmp rax, 10
    jbe .add
    mov eax, 10
.add:
    lea eax, [rax+rax*2]
    add eax, [r10]
    cmp eax, 30
    jbe .store
    mov eax, 30
.store:
    mov [r10], eax
    jmp .take
.reset:
    mov rax, [now_ms]
    mov [r11], rax
.take:
    mov eax, [r10]
    test eax, eax
    jz .no
    dec eax
    mov [r10], eax
    mov eax, 1
    jmp .done
.no:
    inc qword [limited_packets]
    xor eax, eax
.done:
END_FN

; ---------------------------------------------------------------------------------------------------------
; configuration, keys, deny list

; Reads <bridge>/auth.cfg (written by the launcher): key=, keys=, deny=, pass= lines.
FN auth_cfg_load
    lea rcx, [auth_cfg_path]
    lea rdx, [auth_cfg_suffix]
    call make_path
    lea rcx, [auth_cfg_path]
    lea rdx, [cfg_bytes]
    mov r8d, CFG_BYTES
    call pl_read
    cmp rax, 0
    jle .done
    lea rsi, [cfg_bytes]
    mov byte [rsi+rax], 0
.line:
    cmp byte [rsi], 0
    je .done
    xor ebx, ebx
.try:
    cmp ebx, 4
    jae .skip
    lea r12, [cfg_table]
    imul rax, rbx, 24
    add r12, rax
    mov rcx, rsi
    mov rdx, [r12]
    call prefix_len
    test eax, eax
    jnz .match
    inc ebx
    jmp .try
.match:
    lea r13, [rsi+rax]
    xor ecx, ecx
.measure:
    movzx eax, byte [r13+rcx]
    test eax, eax
    jz .measured
    cmp eax, 13
    je .measured
    cmp eax, 10
    je .measured
    inc ecx
    jmp .measure
.measured:
    mov r8, [r12+16]
    mov rdi, [r12+8]
    mov byte [rdi], 0
    cmp rcx, r8
    jae .toolong
    mov r9, rcx
    mov rdx, r13
    mov r10, rdi
.copy:
    test r9, r9
    jz .copied
    mov al, [rdx]
    mov [r10], al
    inc rdx
    inc r10
    dec r9
    jmp .copy
.copied:
    mov byte [r10], 0
    jmp .skip
.toolong:
    cmp ebx, 3
    jne .skip
    mov dword [pass_len], -1
.skip:
    cmp byte [rsi], 0
    je .done
    cmp byte [rsi], 10
    je .next
    inc rsi
    jmp .skip
.next:
    inc rsi
    jmp .line
.done:
END_FN

; RCX entry fingerprint (16 bytes) -> RAX pointer to its 48 byte entry (fingerprint, key) or 0
FN ks_find
    mov r12, rcx
    xor ebx, ebx
.loop:
    cmp ebx, [ks_count]
    jae .none
    imul rax, rbx, KS_ENTRY
    lea r13, [ks_tab]
    add r13, rax
    mov rcx, r12
    mov rdx, r13
    mov r8d, 16
    call ct_equal
    test eax, eax
    jnz .found
    inc ebx
    jmp .loop
.found:
    mov rax, r13
    jmp .done
.none:
    xor eax, eax
.done:
END_FN

; Serialises the key store to keys_path (best effort): "<32 hex> <64 hex>\n" per entry
FN ks_save
    cmp byte [keys_path], 0
    je .done
    lea rcx, [ks_text]
    xor ebx, ebx
    mov r12, rcx
.loop:
    cmp ebx, [ks_count]
    jae .write
    imul rax, rbx, KS_ENTRY
    lea rdx, [ks_tab]
    add rdx, rax
    mov rcx, r12
    mov r8d, 16
    mov r13, rdx
    call hex_put
    mov byte [rax], ' '
    lea rcx, [rax+1]
    lea rdx, [r13+16]
    mov r8d, 32
    call hex_put
    mov byte [rax], 10
    lea r12, [rax+1]
    inc ebx
    jmp .loop
.write:
    lea rdx, [ks_text]
    mov r8, r12
    sub r8, rdx
    jz .done
    lea rcx, [keys_path]
    call pl_atomic
.done:
END_FN

FN ks_load
    mov dword [ks_count], 0
    cmp byte [keys_path], 0
    je .done
    lea rcx, [keys_path]
    lea rdx, [ks_text]
    mov r8d, KS_TEXT-8
    call pl_read
    cmp rax, 0
    jle .done
    lea r12, [ks_text]
    lea r13, [r12+rax]
.line:
    lea rax, [r12+97]
    cmp rax, r13
    ja .done
    cmp dword [ks_count], KS_MAX
    jae .done
    mov eax, [ks_count]
    imul rax, rax, KS_ENTRY
    lea r14, [ks_tab]
    add r14, rax
    mov rcx, r12
    mov rdx, r14
    mov r8d, 16
    call hex_get
    test eax, eax
    jz .skip
    cmp byte [r12+32], ' '
    jne .skip
    lea rcx, [r12+33]
    lea rdx, [r14+16]
    mov r8d, 32
    call hex_get
    test eax, eax
    jz .skip
    inc dword [ks_count]
.skip:
    cmp r12, r13
    jae .done
    cmp byte [r12], 10
    je .adv
    inc r12
    jmp .skip
.adv:
    inc r12
    jmp .line
.done:
END_FN

; RCX fingerprint (16 bytes, may be 0), EDX address (network memory order) -> EAX 1 if on the deny list
FN deny_match
    mov r12, rcx
    mov r13d, edx
    xor ebx, ebx
    test r12, r12
    jz .ips
.fps:
    cmp ebx, [dn_fp_count]
    jae .ips
    mov eax, ebx
    shl eax, 4
    lea rdx, [dn_fp]
    add rdx, rax
    mov rcx, r12
    mov r8d, 16
    call ct_equal
    test eax, eax
    jnz .yes
    inc ebx
    jmp .fps
.ips:
    xor ebx, ebx
    lea r14, [dn_ip]
.ipl:
    cmp ebx, [dn_ip_count]
    jae .no
    cmp [r14+rbx*4], r13d
    je .yes
    inc ebx
    jmp .ipl
.yes:
    mov eax, 1
    jmp .done
.no:
    xor eax, eax
.done:
END_FN

; Re-reads deny.txt: lines of a 32 digit fingerprint or a dotted IPv4 address; '#' starts a comment.
FN deny_load
    mov dword [dn_fp_count], 0
    mov dword [dn_ip_count], 0
    cmp byte [deny_path], 0
    je .done
    lea rcx, [deny_path]
    lea rdx, [dn_text]
    mov r8d, 8192
    call pl_read
    cmp rax, 0
    jle .done
    lea rsi, [dn_text]
    mov byte [rsi+rax], 0
.line:
    movzx eax, byte [rsi]
    test eax, eax
    jz .done
    cmp eax, 33
    jb .space
    cmp eax, '#'
    je .comment
    xor ecx, ecx
    lea rdi, [dn_token]
.token:
    movzx eax, byte [rsi]
    cmp eax, 33
    jb .tokend
    cmp ecx, 64
    jae .skiptoken
    mov [rdi+rcx], al
    inc ecx
    inc rsi
    jmp .token
.skiptoken:
    inc rsi
    movzx eax, byte [rsi]
    cmp eax, 33
    jae .skiptoken
    jmp .line
.tokend:
    mov byte [rdi+rcx], 0
    cmp ecx, 32
    jne .asip
    cmp dword [dn_fp_count], DN_MAX
    jae .line
    mov eax, [dn_fp_count]
    shl eax, 4
    lea rdx, [dn_fp]
    add rdx, rax
    lea rcx, [dn_token]
    mov r8d, 16
    call hex_get
    test eax, eax
    jz .line
    inc dword [dn_fp_count]
    jmp .line
.asip:
    cmp dword [dn_ip_count], DN_MAX
    jae .line
    lea rcx, [dn_token]
    call parse_ip4
    jc .line
    mov ecx, [dn_ip_count]
    lea rdx, [dn_ip]
    mov [rdx+rcx*4], eax
    inc dword [dn_ip_count]
    jmp .line
.space:
    inc rsi
    jmp .line
.comment:
    cmp byte [rsi], 0
    je .done
    cmp byte [rsi], 10
    je .line
    inc rsi
    jmp .comment
.done:
END_FN

; ---------------------------------------------------------------------------------------------------------
; startup

FN auth_init
    mov dword [pass_len], 0
    mov byte [key_path], 0
    mov byte [keys_path], 0
    mov byte [deny_path], 0
    mov byte [pass_text], 0
    call auth_cfg_load
    ; The password is checked now: a malformed one must stop the helper, never silently open the room.
    cmp dword [pass_len], -1
    je .badpass
    lea rcx, [pass_text]
    call text_length
    mov [pass_len], eax
    xor ebx, ebx
.pwchars:
    cmp ebx, [pass_len]
    jae .pwok
    lea rax, [pass_text]
    movzx eax, byte [rax+rbx]
    cmp eax, 33
    jb .badpass
    cmp eax, 126
    ja .badpass
    inc ebx
    jmp .pwchars
.pwok:
    ; install key: read it, or make and save a new one
    xor r12d, r12d
    cmp byte [key_path], 0
    je .generate
    lea rcx, [key_path]
    lea rdx, [install_key]
    mov r8d, 33
    call pl_read
    cmp rax, 32
    je .have_key
.generate:
    lea rcx, [install_key]
    mov edx, 32
    call pl_random
    test eax, eax
    jz .norandom
    cmp byte [key_path], 0
    je .have_key
    lea rcx, [key_path]
    lea rdx, [install_key]
    mov r8d, 32
    call pl_atomic
.have_key:
    lea rcx, [lbl_fp1]
    lea rdx, [install_key]
    mov r8d, 32
    lea r9, [my_fp]
    call make_fp
    lea rcx, [cookie_secret]
    mov edx, 32
    call pl_random
    test eax, eax
    jz .norandom
    lea rdi, [pwk]
    xor eax, eax
    mov ecx, 32
    cld
    rep stosb
    cmp dword [mode_host], 0
    je .done
    cmp dword [pass_len], 0
    je .nopw
    lea rcx, [my_fp]
    lea rdx, [pwk]
    call pwk_derive
.nopw:
    call ks_load
    call deny_load
    mov dword [gb_tokens], 30
    mov dword [gb_tokens+4], 30
    xor ebx, ebx
.slots:
    cmp ebx, MAX_PLAYERS
    jae .done
    mov ecx, ebx
    call auth_pointer
    mov dword [rax+A_PKT], PKT_BUCKET_CAP
    mov dword [rax+A_FRM], FRM_BUCKET_CAP
    inc ebx
    jmp .slots
.badpass:
    lea rcx, [bad_password]
    call pl_print
    mov ecx, 4
    call pl_exit
.norandom:
    lea rcx, [random_error]
    call pl_print
    mov ecx, 5
    call pl_exit
.done:
END_FN

; ---------------------------------------------------------------------------------------------------------
; sending

; RCX buffer, EDX length, R8 destination sockaddr
FN send_raw
    mov r9, r8
    mov r8d, edx
    mov rdx, rcx
    mov rcx, [udp_socket]
    call pl_send
END_FN

; Fills the 8 byte header of auth_out: 'MSAU', type EDX, version 1
FN auth_header
    mov dword [auth_out], 'MSAU'
    mov byte [auth_out+4], dl
    mov byte [auth_out+5], 1
    mov word [auth_out+6], 0
END_FN

; ECX reason -> REJECT to the current source
FN send_reject
    mov r12d, ecx
    lea rdi, [auth_out]
    xor eax, eax
    mov ecx, 16
    cld
    rep stosb
    mov edx, 5
    call auth_header
    mov [auth_out+8], r12d
    mov eax, [session_code]
    mov [auth_out+12], eax
    lea rcx, [auth_out]
    mov edx, 16
    lea r8, [source_address]
    call send_raw
END_FN

; ---------------------------------------------------------------------------------------------------------
; host side

; ECX window id, EDX slot, R8 client nonce, R9 16 byte output: the stateless cookie for the current source
FN make_cookie
    mov r12, r9
    mov r13, r8
    mov [sc], ecx
    mov [sc+4], edx
    mov dword [mb_len], 0
    lea rcx, [lbl_ck]
    call mb_str
    lea rcx, [sc]
    mov edx, 4
    call mb_add
    lea rcx, [source_address+2]
    mov edx, 6
    call mb_add
    lea rcx, [sc+4]
    mov edx, 4
    call mb_add
    mov rcx, r13
    mov edx, 16
    call mb_add
    lea rcx, [cookie_secret]
    lea rdx, [hm_res]
    call mb_hmac
    mov rcx, r12
    lea rdx, [hm_res]
    mov r8d, 16
    call bytes_copy
END_FN

; Current cookie window id -> EAX
FN window_now
    mov rax, [now_ms]
    xor edx, edx
    mov ecx, WINDOW_MS
    div rcx
END_FN

; HELLO (128 bytes) in packet_in
FN host_hello
    mov eax, [packet_in+8]
    cmp eax, [session_code]
    jne .bad
    mov r12d, [packet_in+12]
    test r12d, r12d
    jz .bad
    cmp r12d, MAX_PLAYERS
    jae .bad
    xor ecx, ecx
    call take_global
    test eax, eax
    jz .done
    xor ecx, ecx
    mov edx, [source_address+4]
    call deny_match
    test eax, eax
    jnz .denied
    call window_now
    mov ebx, eax
    mov ecx, ebx
    mov edx, r12d
    lea r8, [packet_in+16]
    lea r9, [auth_out+16]
    call make_cookie
    mov edx, 2
    call auth_header
    xor eax, eax
    cmp dword [pass_len], 0
    setne al
    mov [auth_out+8], eax
    mov [auth_out+12], ebx
    lea rsi, [my_fp]
    lea rdi, [auth_out+32]
    mov ecx, 16
    cld
    rep movsb
    lea rsi, [packet_in+16]
    lea rdi, [auth_out+48]
    mov ecx, 16
    rep movsb
    lea rcx, [auth_out]
    mov edx, 64
    lea r8, [source_address]
    call send_raw
    jmp .done
.denied:
    inc qword [denied_joins]
    mov ecx, 2
    call send_reject
    jmp .done
.bad:
    inc qword [bad_packets]
.done:
END_FN

; PROOF (128 bytes) in packet_in
FN host_proof
    mov eax, [packet_in+8]
    cmp eax, [session_code]
    jne .bad
    mov r12d, [packet_in+12]
    test r12d, r12d
    jz .bad
    cmp r12d, MAX_PLAYERS
    jae .bad
    mov ecx, 1
    call take_global
    test eax, eax
    jz .done
    call window_now
    mov ecx, [packet_in+32]
    cmp ecx, eax
    je .window_ok
    inc ecx
    cmp ecx, eax
    jne .bad
.window_ok:
    mov ecx, [packet_in+32]
    mov edx, r12d
    lea r8, [packet_in+16]
    lea r9, [m_buf]
    call make_cookie
    lea rcx, [m_buf]
    lea rdx, [packet_in+36]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .bad
    xor ecx, ecx
    mov edx, [source_address+4]
    call deny_match
    test eax, eax
    jnz .denied
    ; the key: stored for this fingerprint, or unmasked from the registration
    lea rcx, [packet_in+52]
    call ks_find
    mov r13, rax
    test r13, r13
    jz .register
    lea rsi, [r13+16]
    lea rdi, [k_buf]
    mov ecx, 32
    cld
    rep movsb
    mov dword [is_new], 0
    jmp .have_key
.register:
    mov dword [mb_len], 0
    lea rcx, [lbl_reg]
    call mb_str
    lea rcx, [packet_in+36]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [pwk]
    lea rdx, [m_buf]
    call mb_hmac
    xor ecx, ecx
.unmask:
    lea rax, [packet_in+68]
    movzx eax, byte [rax+rcx]
    lea rdx, [m_buf]
    xor al, [rdx+rcx]
    lea rdx, [k_buf]
    mov [rdx+rcx], al
    inc ecx
    cmp ecx, 32
    jb .unmask
    lea rcx, [lbl_fp2]
    lea rdx, [k_buf]
    mov r8d, 32
    lea r9, [t_fp]
    call make_fp
    lea rcx, [t_fp]
    lea rdx, [packet_in+52]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .authfail
    mov dword [is_new], 1
.have_key:
    mov dword [mb_len], 0
    lea rcx, [k_buf]
    mov edx, 32
    call mb_add
    lea rcx, [pwk]
    lea rdx, [ak_buf]
    call mb_hmac
    mov dword [mb_len], 0
    lea rcx, [lbl_proof]
    call mb_str
    lea rcx, [packet_in+8]
    mov edx, 92
    call mb_add
    lea rcx, [my_fp]
    mov edx, 16
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [hm_res]
    call mb_hmac
    lea rcx, [hm_res]
    lea rdx, [packet_in+100]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .authfail
    ; a captured PROOF must not open a second session
    xor ebx, ebx
    lea r14, [replay_ring]
.replay:
    mov eax, ebx
    shl eax, 4
    lea rcx, [r14+rax]
    lea rdx, [packet_in+16]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jnz .done
    inc ebx
    cmp ebx, 8
    jb .replay
    lea rcx, [packet_in+52]
    mov edx, [source_address+4]
    call deny_match
    test eax, eax
    jnz .denied
    mov ecx, r12d
    call peer_pointer
    mov r14, rax
    mov ecx, r12d
    call auth_pointer
    mov r15, rax
    ; the slot belongs to someone else while that player is live?
    cmp dword [r14+P_PRESENT], 0
    je .slot_free
    cmp dword [r15+A_STATE], 1
    jne .slot_free
    lea rcx, [r15+A_FP]
    lea rdx, [packet_in+52]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .busy
.slot_free:
    ; the same install live in another slot?
    mov ebx, 1
.elsewhere:
    cmp ebx, MAX_PLAYERS
    jae .admit
    cmp ebx, r12d
    je .next_slot
    mov ecx, ebx
    call auth_pointer
    cmp dword [rax+A_STATE], 1
    jne .next_slot
    mov r13, rax
    lea rcx, [rax+A_FP]
    lea rdx, [packet_in+52]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .next_slot
    jmp .busy
.next_slot:
    inc ebx
    jmp .elsewhere
.admit:
    cmp dword [is_new], 0
    je .store_done
    cmp dword [ks_count], KS_MAX
    jae .full
    mov eax, [ks_count]
    imul rax, rax, KS_ENTRY
    lea rdi, [ks_tab]
    add rdi, rax
    lea rsi, [packet_in+52]
    mov ecx, 16
    cld
    rep movsb
    lea rsi, [k_buf]
    mov ecx, 32
    rep movsb
    inc dword [ks_count]
    call ks_save
.store_done:
    ; remember the nonce
    mov eax, [replay_next]
    and eax, 7
    shl eax, 4
    lea rdi, [replay_ring]
    add rdi, rax
    lea rsi, [packet_in+16]
    mov ecx, 16
    cld
    rep movsb
    inc dword [replay_next]
    ; session key
    mov dword [mb_len], 0
    lea rcx, [lbl_sk]
    call mb_str
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+36]
    mov edx, 16
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [r15+A_SK]
    call mb_hmac
    ; the WELCOME tag
    mov dword [mb_len], 0
    lea rcx, [lbl_welcome]
    call mb_str
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+36]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+12]
    mov edx, 4
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [hm_res]
    call mb_hmac
    ; the slot
    mov rax, [source_address]
    mov [r14+P_ADDR], rax
    mov rax, [source_address+8]
    mov [r14+P_ADDR+8], rax
    mov rax, [now_ms]
    mov [r14+P_SEEN], rax
    mov [r15+A_LAST], rax
    mov dword [r14+P_PRESENT], 1
    mov dword [r14+P_COMPLETE], 0
    mov dword [r14+P_BITS], 0
    mov dword [r14+P_EPOCH], 0
    mov dword [r15+A_STATE], 1
    inc dword [r15+A_GEN]
    mov dword [r15+A_PKT], PKT_BUCKET_CAP
    mov dword [r15+A_FRM], FRM_BUCKET_CAP
    lea rsi, [packet_in+52]
    lea rdi, [r15+A_FP]
    mov ecx, 16
    cld
    rep movsb
    lea rsi, [packet_in+16]
    lea rdi, [r15+A_CN]
    mov ecx, 16
    rep movsb
    mov ecx, r12d
    call publish_auth
    ; WELCOME
    lea rdi, [auth_out]
    xor eax, eax
    mov ecx, 48
    cld
    rep stosb
    mov edx, 4
    call auth_header
    mov eax, [session_code]
    mov [auth_out+8], eax
    mov [auth_out+12], r12d
    lea rsi, [hm_res]
    lea rdi, [auth_out+16]
    mov ecx, 16
    rep movsb
    mov eax, [is_new]
    mov [auth_out+32], eax
    lea rcx, [auth_out]
    mov edx, 48
    lea r8, [source_address]
    call send_raw
    jmp .done
.authfail:
    inc qword [auth_failures]
    mov ecx, 1
    call send_reject
    jmp .done
.denied:
    inc qword [denied_joins]
    mov ecx, 2
    call send_reject
    jmp .done
.busy:
    mov ecx, 3
    call send_reject
    jmp .done
.full:
    mov ecx, 4
    call send_reject
    jmp .done
.bad:
    inc qword [bad_packets]
.done:
END_FN

; Hint to an unknown source that sends game data: say HELLO again (unauthenticated, 16 bytes, twice a second at most)
FN send_resync
    mov rax, [now_ms]
    sub rax, [resync_last]
    cmp rax, 500
    jb .done
    mov rax, [now_ms]
    mov [resync_last], rax
    lea rdi, [auth_out]
    xor eax, eax
    mov ecx, 16
    cld
    rep stosb
    mov edx, 6
    call auth_header
    lea rcx, [auth_out]
    mov edx, 16
    lea r8, [source_address]
    call send_raw
.done:
END_FN

; ---------------------------------------------------------------------------------------------------------
; guest side

FN guest_from_host
    mov rax, [source_address]
    cmp rax, [host_address]
    sete al
    movzx eax, al
END_FN

; CHALLENGE (64 bytes) in packet_in
FN guest_challenge
    cmp dword [g_state], 1
    jne .done
    call guest_from_host
    test eax, eax
    jz .done
    lea rcx, [packet_in+48]
    lea rdx, [g_cnonce]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .done
    mov r12d, [packet_in+8]
    lea rsi, [packet_in+32]
    lea rdi, [g_hfp]
    mov ecx, 16
    cld
    rep movsb
    ; PWK: stretched when the host asks for a password, zero otherwise
    lea rdi, [g_pwk]
    xor eax, eax
    mov ecx, 32
    rep stosb
    test r12d, 1
    jz .keys
    cmp dword [pass_len], 0
    je .nopass
    cmp dword [g_pwk_valid], 0
    je .stretch
    lea rcx, [g_hfp]
    lea rdx, [g_pwk_for]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jnz .cached
.stretch:
    lea rcx, [g_hfp]
    lea rdx, [g_pwk]
    call pwk_derive
    lea rsi, [g_hfp]
    lea rdi, [g_pwk_for]
    mov ecx, 16
    cld
    rep movsb
    lea rsi, [g_pwk]
    lea rdi, [pwk]
    mov ecx, 32
    rep movsb
    mov dword [g_pwk_valid], 1
    jmp .keys
.cached:
    lea rsi, [pwk]
    lea rdi, [g_pwk]
    mov ecx, 32
    cld
    rep movsb
.keys:
    ; K = HMAC(IK, "MMBIND1" | host fingerprint)
    mov dword [mb_len], 0
    lea rcx, [lbl_bind]
    call mb_str
    lea rcx, [g_hfp]
    mov edx, 16
    call mb_add
    lea rcx, [install_key]
    lea rdx, [k_buf]
    call mb_hmac
    lea rcx, [lbl_fp2]
    lea rdx, [k_buf]
    mov r8d, 32
    lea r9, [t_fp]
    call make_fp
    mov dword [mb_len], 0
    lea rcx, [lbl_reg]
    call mb_str
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [g_cnonce]
    mov edx, 16
    call mb_add
    lea rcx, [g_pwk]
    lea rdx, [m_buf]
    call mb_hmac
    mov dword [mb_len], 0
    lea rcx, [k_buf]
    mov edx, 32
    call mb_add
    lea rcx, [g_pwk]
    lea rdx, [ak_buf]
    call mb_hmac
    ; the PROOF packet
    lea rdi, [auth_out]
    xor eax, eax
    mov ecx, 128
    cld
    rep stosb
    mov edx, 3
    call auth_header
    mov eax, [session_code]
    mov [auth_out+8], eax
    mov eax, [local_id]
    mov [auth_out+12], eax
    lea rsi, [g_cnonce]
    lea rdi, [auth_out+16]
    mov ecx, 16
    rep movsb
    mov eax, [packet_in+12]
    mov [auth_out+32], eax
    lea rsi, [packet_in+16]
    lea rdi, [auth_out+36]
    mov ecx, 16
    rep movsb
    lea rsi, [t_fp]
    lea rdi, [auth_out+52]
    mov ecx, 16
    rep movsb
    xor ecx, ecx
.mask:
    lea rax, [k_buf]
    movzx eax, byte [rax+rcx]
    lea rdx, [m_buf]
    xor al, [rdx+rcx]
    lea rdx, [auth_out+68]
    mov [rdx+rcx], al
    inc ecx
    cmp ecx, 32
    jb .mask
    mov dword [mb_len], 0
    lea rcx, [lbl_proof]
    call mb_str
    lea rcx, [auth_out+8]
    mov edx, 92
    call mb_add
    lea rcx, [g_hfp]
    mov edx, 16
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [hm_res]
    call mb_hmac
    lea rsi, [hm_res]
    lea rdi, [auth_out+100]
    mov ecx, 16
    cld
    rep movsb
    ; session key and the WELCOME tag we expect
    mov dword [mb_len], 0
    lea rcx, [lbl_sk]
    call mb_str
    lea rcx, [g_cnonce]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [g_sk]
    call mb_hmac
    mov dword [mb_len], 0
    lea rcx, [lbl_welcome]
    call mb_str
    lea rcx, [g_cnonce]
    mov edx, 16
    call mb_add
    lea rcx, [packet_in+16]
    mov edx, 16
    call mb_add
    lea rcx, [local_id]
    mov edx, 4
    call mb_add
    lea rcx, [ak_buf]
    lea rdx, [hm_res]
    call mb_hmac
    lea rsi, [hm_res]
    lea rdi, [g_wtag]
    mov ecx, 16
    cld
    rep movsb
    lea rcx, [auth_out]
    mov edx, 128
    lea r8, [host_address]
    call send_raw
    mov dword [g_state], 3
    mov rax, [now_ms]
    mov [g_proof_at], rax
    jmp .done
.nopass:
    mov dword [g_reject], 6
    mov dword [g_state], 0
    mov rax, [now_ms]
    mov [g_last_hello], rax
    xor ecx, ecx
    call publish_auth
.done:
END_FN

; WELCOME (48 bytes) in packet_in
FN guest_welcome
    cmp dword [g_state], 3
    jne .done
    call guest_from_host
    test eax, eax
    jz .done
    mov eax, [packet_in+8]
    cmp eax, [session_code]
    jne .done
    mov eax, [packet_in+12]
    cmp eax, [local_id]
    jne .done
    lea rcx, [packet_in+16]
    lea rdx, [g_wtag]
    mov r8d, 16
    call ct_equal
    test eax, eax
    jz .done
    mov dword [g_state], 2
    mov dword [g_reject], 0
    inc dword [g_gen]
    mov rax, [now_ms]
    mov [g_last_rx], rax
    mov [g_welcomed], rax
    xor ecx, ecx
    call peer_pointer
    mov dword [rax+P_EPOCH], 0
    mov dword [rax+P_COMPLETE], 0
    mov dword [rax+P_BITS], 0
    xor ecx, ecx
    call publish_auth
.done:
END_FN

; REJECT (16 bytes) in packet_in
FN guest_reject
    call guest_from_host
    test eax, eax
    jz .done
    mov eax, [packet_in+12]
    cmp eax, [session_code]
    jne .done
    mov eax, [g_state]
    cmp eax, 1
    je .take
    cmp eax, 3
    jne .done
.take:
    mov eax, [packet_in+8]
    cmp eax, 1
    jb .done
    cmp eax, 255
    ja .done
    mov [g_reject], eax
    mov dword [g_state], 0
    mov rax, [now_ms]
    mov [g_last_hello], rax
    xor ecx, ecx
    call publish_auth
.done:
END_FN

; RESYNC (16 bytes): the host lost us (restart, expiry)
FN guest_resync
    cmp dword [g_state], 2
    jne .done
    call guest_from_host
    test eax, eax
    jz .done
    mov rax, [now_ms]
    sub rax, [g_welcomed]
    cmp rax, 1000
    jb .done
    mov dword [g_state], 0
    mov qword [g_last_hello], 0
    mov dword [g_reject], 0
    xor ecx, ecx
    call publish_auth
.done:
END_FN

; Once per main loop pass on a guest: sends HELLO, and drops back to HELLO after a silent host
FN auth_tick
    cmp dword [mode_host], 0
    jne .done
    mov eax, [g_state]
    cmp eax, 2
    je .established
    cmp eax, 3
    je .proofwait
    mov rax, [now_ms]
    sub rax, [g_last_hello]
    mov edx, 1000
    cmp dword [g_reject], 0
    je .due
    mov edx, 3000
.due:
    cmp rax, rdx
    jb .done
    lea rcx, [g_cnonce]
    mov edx, 16
    call pl_random
    test eax, eax
    jz .done
    lea rdi, [auth_out]
    xor eax, eax
    mov ecx, 128
    cld
    rep stosb
    mov edx, 1
    call auth_header
    mov eax, [session_code]
    mov [auth_out+8], eax
    mov eax, [local_id]
    mov [auth_out+12], eax
    lea rsi, [g_cnonce]
    lea rdi, [auth_out+16]
    mov ecx, 16
    rep movsb
    lea rcx, [auth_out]
    mov edx, 128
    lea r8, [host_address]
    call send_raw
    mov dword [g_state], 1
    mov rax, [now_ms]
    mov [g_last_hello], rax
    jmp .done
.proofwait:
    mov rax, [now_ms]
    sub rax, [g_proof_at]
    cmp rax, 1500
    jb .done
    mov dword [g_state], 0
    jmp .done
.established:
    mov rax, [now_ms]
    sub rax, [g_last_rx]
    cmp rax, 5000
    jb .done
    mov dword [g_state], 0
    mov qword [g_last_hello], 0
    xor ecx, ecx
    call publish_auth
.done:
END_FN

; ---------------------------------------------------------------------------------------------------------
; receive dispatch for 'MSAU' packets: ECX datagram length (strict per type)

FN auth_receive
    mov r12d, ecx
    cmp byte [packet_in+5], 1
    jne .bad
    movzx eax, byte [packet_in+4]
    cmp eax, 1
    je .hello
    cmp eax, 3
    je .proof
    cmp eax, 2
    je .challenge
    cmp eax, 4
    je .welcome
    cmp eax, 5
    je .reject
    cmp eax, 6
    je .resync
    jmp .bad
.hello:
    cmp dword [mode_host], 0
    je .bad
    cmp r12d, 128
    jne .bad
    call host_hello
    jmp .done
.proof:
    cmp dword [mode_host], 0
    je .bad
    cmp r12d, 128
    jne .bad
    call host_proof
    jmp .done
.challenge:
    cmp dword [mode_host], 0
    jne .bad
    cmp r12d, 64
    jne .bad
    call guest_challenge
    jmp .done
.welcome:
    cmp dword [mode_host], 0
    jne .bad
    cmp r12d, 48
    jne .bad
    call guest_welcome
    jmp .done
.reject:
    cmp dword [mode_host], 0
    jne .bad
    cmp r12d, 16
    jne .bad
    call guest_reject
    jmp .done
.resync:
    cmp dword [mode_host], 0
    jne .bad
    cmp r12d, 16
    jne .bad
    call guest_resync
    jmp .done
.bad:
    inc qword [bad_packets]
.done:
END_FN

; ECX plain length (header and payload), RDX 32 byte key, R8D direction (0 guest to host, 1 host to guest)
; -> EAX 1 if the 16 byte tag after the plain bytes in packet_in is valid
FN verify_packet
    mov r12d, ecx
    mov r13, rdx
    mov [sc], r8b
    mov dword [mb_len], 0
    lea rcx, [sc]
    mov edx, 1
    call mb_add
    lea rcx, [packet_in]
    mov edx, r12d
    call mb_add
    mov rcx, r13
    lea rdx, [hm_res]
    call mb_hmac
    lea rcx, [packet_in]
    add rcx, r12
    lea rdx, [hm_res]
    mov r8d, TAG
    call ct_equal
END_FN

; ---------------------------------------------------------------------------------------------------------
; peers leaving, published authentication state

; Slot ECX is gone (expired, kicked): clears its record and publishes the inactive state
FN peer_drop
    mov ebx, ecx
    call peer_pointer
    mov r12, rax
    mov dword [r12+P_PRESENT], 0
    mov dword [r12+P_COMPLETE], 0
    mov dword [r12+P_BITS], 0
    mov dword [r12+P_EPOCH], 0
    lea rcx, [r12+P_CACHE]
    lea rdx, [inactive_json]
    call text_copy
    mov dword [r12+P_LENGTH], 16
    mov ecx, ebx
    call auth_pointer
    mov dword [rax+A_STATE], 0
    mov ecx, ebx
    mov rdx, r12
    call publish_record
    cmp dword [mode_host], 0
    jne .publish
    test ebx, ebx                       ; a guest only publishes the state of the host (slot 0)
    jnz .done
.publish:
    mov ecx, ebx
    call publish_auth
.done:
END_FN

; Writes <bridge>/world_<slot>.key for ECX = slot (a guest: its own slot): WK = HMAC(SK, "MMWORLD1") while that session is
; established, 32 zero bytes otherwise. The launcher of the same computer reads it to run the world download's challenge and
; response (docs/PROTOCOL.md): only a party that completed this join handshake can answer it. The file is created 0600 on Linux.
FN publish_world_key
    mov ebx, ecx
    cmp dword [mode_host], 0
    je .guest
    mov r13d, ebx
    mov ecx, ebx
    call auth_pointer
    cmp dword [rax+A_STATE], 1
    jne .none
    lea r12, [rax+A_SK]
    jmp .have
.guest:
    mov r13d, [local_id]
    cmp dword [g_state], 2
    jne .none
    lea r12, [g_sk]
.have:
    mov dword [mb_len], 0
    lea rcx, [lbl_world]
    call mb_str
    mov rcx, r12
    lea rdx, [world_key]
    call mb_hmac
    jmp .write
.none:
    lea rdi, [world_key]
    xor eax, eax
    mov ecx, 32
    cld
    rep stosb
.write:
    lea rcx, [world_path]
    lea rdx, [world_key_suffix]
    call make_path
    lea rcx, [base_dir]
    call text_length
    lea rdx, [world_path]
    mov ecx, r13d
    and cl, 7
    add cl, '0'
    mov [rdx+rax+7], cl
    lea rcx, [world_path]
    lea rdx, [world_key]
    mov r8d, 32
    call pl_atomic
END_FN

; Writes <bridge>/auth_<slot>.json: {"fp":"..","gen":N,"state":S,"reject":R}. Hosts publish the verified
; fingerprint of each guest; a guest publishes the host's fingerprint (slot 0) and why a join was rejected.
FN publish_auth
    mov ebx, ecx
    call publish_world_key              ; first: whoever sees the new state can already use the key
    mov ecx, ebx
    lea rcx, [auth_path]
    lea rdx, [auth_json_suffix]
    call make_path
    lea rcx, [base_dir]
    call text_length
    lea rdx, [auth_path]
    mov ecx, ebx
    add cl, '0'
    mov [rdx+rax+6], cl
    lea rcx, [auth_json]
    lea rdx, [j_auth_fp]
    call text_copy
    mov r12, rax
    cmp dword [mode_host], 0
    je .guest
    mov ecx, ebx
    call auth_pointer
    mov r13, rax
    cmp dword [r13+A_STATE], 1
    jne .nofp
    mov rcx, r12
    lea rdx, [r13+A_FP]
    mov r8d, 16
    call hex_put
    mov r12, rax
.nofp:
    mov r14d, [r13+A_GEN]
    mov r15d, [r13+A_STATE]
    xor esi, esi
    jmp .build
.guest:
    mov r14d, [g_gen]
    mov r15d, [g_state]
    mov esi, [g_reject]
    cmp dword [g_state], 2
    jb .build
    mov rcx, r12
    lea rdx, [g_hfp]
    mov r8d, 16
    call hex_put
    mov r12, rax
.build:
    mov rcx, r12
    lea rdx, [j_auth_gen]
    call text_copy
    mov rdx, rax
    mov ecx, r14d
    call append_number
    mov rcx, rax
    lea rdx, [j_auth_state]
    call text_copy
    mov rdx, rax
    mov ecx, r15d
    call append_number
    mov rcx, rax
    lea rdx, [j_auth_reject]
    call text_copy
    mov rdx, rax
    mov ecx, esi
    call append_number
    mov rcx, rax
    lea rdx, [j_auth_end]
    call text_copy
    lea rdx, [auth_json]
    sub rax, rdx
    mov r8, rax
    lea rcx, [auth_path]
    call pl_atomic
END_FN

; Once a second on a host: re-read deny.txt and remove players who are on it
FN auth_second
    cmp dword [mode_host], 0
    je .done
    call deny_load
    mov ebx, 1
.slot:
    cmp ebx, MAX_PLAYERS
    jae .done
    mov ecx, ebx
    call auth_pointer
    cmp dword [rax+A_STATE], 1
    jne .next
    mov r12, rax
    mov ecx, ebx
    call peer_pointer
    mov edx, [rax+P_ADDR+4]
    lea rcx, [r12+A_FP]
    call deny_match
    test eax, eax
    jz .next
    inc qword [denied_joins]
    mov ecx, ebx
    call peer_drop
.next:
    inc ebx
    jmp .slot
.done:
END_FN
