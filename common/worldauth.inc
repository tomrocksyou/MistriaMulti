; Authenticated world transfer (TCP 7775), the part shared by every program on both systems. Protocol: docs/PROTOCOL.md.
; The download is released only to a client that proves it holds the key of a join session the host's helper has
; authenticated (the same HMAC-SHA256 handshake as the UDP join; the helper writes WK = HMAC(SK, "MMWORLD1") for each
; session into <bridge>/world_<slot>.key). No byte of the world is sent before the proof is checked.
;   client -> host   REQUEST  64 bytes: "MSWQ", version 2, slot, 10 zero bytes, client nonce @16, zero
;   host -> client   CHALLENGE 32 bytes: "MSWC", version 2, status 0, 10 zero bytes, host nonce @16 (fresh for every connection)
;   client -> host   PROOF    48 bytes: "MSWP", version 2, 12 zero bytes, tag @16 = HMAC(WK, "MMWORLDQ1" | slot | client nonce | host nonce)
;   host -> client   144-byte header: the 112-byte "MSWR" header (version 2; status 0 ok, 1 no world, 2 cannot send, 3 refused)
;                    then tag @112 = HMAC(WK, "MMWORLDR1" | slot | client nonce | host nonce | header bytes 0..111), then the file
; The including program provides wf_sock, wf_hdr (160 bytes), wf_req (64 bytes), wf_recv_exact, wf_send_all, wf_random
; (rcx buffer, edx count -> eax 1) and read_file. The host half (the launchers only) is worldserve.inc.
%include "hmac.inc"

section .data
wa_lbl_q db 'MMWORLDQ1'
wa_lbl_r db 'MMWORLDR1'

section .bss
wa_key resb 32
wa_cn resb 16
wa_hn resb 16
wa_slot resd 1
wa_ok resd 1
wa_tag resb 32
wa_msg resb 160
wf_slot resd 1                         ; the client's own slot (1-7)
wf_keypath resq 1                      ; the client's key file, or 0: world_fetch then refuses without connecting

section .text
; rcx = path -> eax 1 if wa_key now holds a usable key (exactly 32 bytes, not all zero: the helper writes zeros when there is no session)
FN wa_load_key
    mov r12, rcx
    lea rdi, [wa_key]
    xor eax, eax
    mov ecx, 4
    cld
    rep stosq
    mov rcx, r12
    lea rdx, [wa_key]
    mov r8d, 33
    call read_file
    cmp rax, 32
    jne .no
    lea rsi, [wa_key]
    mov rax, [rsi]
    or rax, [rsi+8]
    or rax, [rsi+16]
    or rax, [rsi+24]
    jz .no
    mov eax, 1
    jmp .d
.no:
    lea rdi, [wa_key]
    xor eax, eax
    mov ecx, 4
    rep stosq
    xor eax, eax
.d:
END_FN

; rcx a, rdx b, r8d length -> eax 1 if equal; the time does not depend on where they differ
FN wa_ct_equal
    xor eax, eax
    xor r9d, r9d
.loop:
    cmp r9d, r8d
    jae .done
    movzx r10d, byte [rcx+r9]
    xor r10b, [rdx+r9]
    or al, r10b
    inc r9d
    jmp .loop
.done:
    test al, al
    sete al
    movzx eax, al
END_FN

; ecx 0: proof tag; 1: reply tag (also covers the 112 header bytes in wf_hdr). Fills wa_tag from wa_key, wa_slot and both nonces -> eax 1
FN wa_make_tag
    mov r12d, ecx
    lea rdi, [wa_msg]
    lea rsi, [wa_lbl_q]
    test r12d, r12d
    jz .label
    lea rsi, [wa_lbl_r]
.label:
    mov ecx, 9
    cld
    rep movsb
    mov eax, [wa_slot]
    stosb
    lea rsi, [wa_cn]
    mov ecx, 16
    rep movsb
    lea rsi, [wa_hn]
    mov ecx, 16
    rep movsb
    test r12d, r12d
    jz .go
    lea rsi, [wf_hdr]
    mov ecx, 112
    rep movsb
.go:
    lea rdx, [wa_msg]
    mov r8, rdi
    sub r8, rdx
    lea rcx, [wa_key]
    lea r9, [wa_tag]
    call hmac_sha256
END_FN

; Client: connected on [wf_sock], wa_key and wf_slot are set. Sends the request, answers the challenge. eax 1 if the proof was sent
FN wa_client_hello
    mov eax, [wf_slot]
    mov [wa_slot], eax
    lea rcx, [wa_cn]
    mov edx, 16
    call wf_random
    test eax, eax
    jz .fail
    lea rdi, [wf_req]
    xor eax, eax
    mov ecx, 8
    cld
    rep stosq
    mov dword [wf_req], 'MSWQ'
    mov byte [wf_req+4], 2
    mov eax, [wa_slot]
    mov [wf_req+5], al
    lea rsi, [wa_cn]
    lea rdi, [wf_req+16]
    mov ecx, 16
    rep movsb
    lea rcx, [wf_req]
    mov edx, 64
    call wf_send_all
    test eax, eax
    jz .fail
    lea rcx, [wf_hdr]
    mov edx, 32
    mov r8d, 5000
    call wf_recv_exact
    test eax, eax
    jz .fail
    cmp dword [wf_hdr], 'MSWC'
    jne .fail
    cmp byte [wf_hdr+4], 2
    jne .fail
    cmp byte [wf_hdr+5], 0
    jne .fail
    lea rsi, [wf_hdr+16]
    lea rdi, [wa_hn]
    mov ecx, 16
    rep movsb
    xor ecx, ecx
    call wa_make_tag
    test eax, eax
    jz .fail
    lea rdi, [wf_req]
    xor eax, eax
    mov ecx, 6
    rep stosq
    mov dword [wf_req], 'MSWP'
    mov byte [wf_req+4], 2
    lea rsi, [wa_tag]
    lea rdi, [wf_req+16]
    mov ecx, 32
    rep movsb
    lea rcx, [wf_req]
    mov edx, 48
    call wf_send_all
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

; Client: wf_hdr holds a complete 144-byte reply -> eax 1 if it is version 2 and its tag is right
FN wa_check_header
    cmp dword [wf_hdr], 'MSWR'
    jne .no
    cmp byte [wf_hdr+4], 2
    jne .no
    mov ecx, 1
    call wa_make_tag
    test eax, eax
    jz .no
    lea rcx, [wa_tag]
    lea rdx, [wf_hdr+112]
    mov r8d, 32
    call wa_ct_equal
    jmp .d
.no:
    xor eax, eax
.d:
END_FN
