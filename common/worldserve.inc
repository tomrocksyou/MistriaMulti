; Host half of the authenticated world transfer (the launchers only; the protocol is described in worldauth.inc and docs/PROTOCOL.md).
; The including program provides wf_key_for_slot (ecx slot -> eax 1 with that slot's session key in wa_key, 0 if it has none).

section .data
wa_msg_old db 'Update MistriaMulti: the world download now needs a login',0
wa_msg_old_len equ $ - wa_msg_old

section .text
; Server: signs the reply header in wf_hdr (version 2 set by the caller): the tag goes to bytes 112..143
FN wa_sign_header
    mov ecx, 1
    call wa_make_tag
    lea rsi, [wa_tag]
    lea rdi, [wf_hdr+112]
    mov ecx, 32
    cld
    rep movsb
END_FN

; Server: a refusal in the 144-byte format (status 3, no tag) or, for an old client, the 112-byte format. ecx 2 or 1 = version
FN wa_refuse
    mov r12d, ecx
    lea rdi, [wf_hdr]
    xor eax, eax
    mov ecx, 18
    cld
    rep stosq
    mov dword [wf_hdr], 'MSWR'
    mov [wf_hdr+4], r12b
    mov byte [wf_hdr+5], 3
    mov edx, 144
    cmp r12d, 2
    je .send
    lea rsi, [wa_msg_old]              ; an old client cannot read it, but it shows up in a packet capture or log
    lea rdi, [wf_hdr+48]
    mov ecx, wa_msg_old_len
    rep movsb
    mov edx, 112
.send:
    lea rcx, [wf_hdr]
    call wf_send_all
END_FN

; Server: a connection was accepted on [wf_sock] (its timeouts are set). Runs the whole challenge and response.
; eax 1: the client proved the session key (wa_key, wa_slot and both nonces are set: send a header and call wa_sign_header)
; eax 0: refused (the refusal was sent) or the connection broke; the caller just closes it
FN wa_serve_auth
    lea rcx, [wf_req]
    mov edx, 16
    mov r8d, 3000
    call wf_recv_exact
    test eax, eax
    jz .drop
    cmp dword [wf_req], 'MSWQ'
    jne .drop
    movzx eax, byte [wf_req+4]
    cmp eax, 1
    je .old
    cmp eax, 2
    jne .drop
    lea rcx, [wf_req+16]
    mov edx, 48
    mov r8d, 3000
    call wf_recv_exact
    test eax, eax
    jz .drop
    movzx eax, byte [wf_req+5]
    mov [wa_slot], eax
    lea rsi, [wf_req+16]
    lea rdi, [wa_cn]
    mov ecx, 16
    cld
    rep movsb
    lea rcx, [wa_hn]
    mov edx, 16
    call wf_random
    test eax, eax
    jz .drop
    lea rdi, [wf_hdr]                  ; CHALLENGE
    xor eax, eax
    mov ecx, 4
    rep stosq
    mov dword [wf_hdr], 'MSWC'
    mov byte [wf_hdr+4], 2
    lea rsi, [wa_hn]
    lea rdi, [wf_hdr+16]
    mov ecx, 16
    rep movsb
    lea rcx, [wf_hdr]
    mov edx, 32
    call wf_send_all
    test eax, eax
    jz .drop
    lea rcx, [wf_req]
    mov edx, 48
    mov r8d, 3000
    call wf_recv_exact
    test eax, eax
    jz .drop
    mov dword [wa_ok], 0
    cmp dword [wf_req], 'MSWP'
    jne .check
    cmp byte [wf_req+4], 2
    jne .check
    mov eax, [wa_slot]
    dec eax
    cmp eax, 6                         ; slot 1..7 only: slot 0 is the host itself
    ja .check
    mov ecx, [wa_slot]
    call wf_key_for_slot
    mov [wa_ok], eax
.check:
    cmp dword [wa_ok], 0
    jne .have_key
    lea rdi, [wa_key]                  ; no session for this slot: the tag is still computed (with a zero key) and then refused
    xor eax, eax
    mov ecx, 4
    rep stosq
.have_key:
    xor ecx, ecx
    call wa_make_tag
    lea rcx, [wa_tag]
    lea rdx, [wf_req+16]
    mov r8d, 32
    call wa_ct_equal
    and eax, [wa_ok]
    jz .refuse
    mov eax, 1
    jmp .d
.refuse:
    mov ecx, 2
    call wa_refuse
    xor eax, eax
    jmp .d
.old:
    mov ecx, 1                         ; an old client sent 16 bytes and waits for 112: answer at once
    call wa_refuse
.drop:
    xor eax, eax
.d:
END_FN

