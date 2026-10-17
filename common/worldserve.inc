; Host half of the authenticated world transfer

section .data
wa_msg_old db 'Update MistriaMulti: the world download now needs a login',0
wa_msg_old_len equ $ - wa_msg_old

section .text
FN wa_sign_header
    mov ecx, 1
    call wa_make_tag
    lea rsi, [wa_tag]
    lea rdi, [wf_hdr+112]
    mov ecx, 32
    cld
    rep movsb
END_FN

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
    lea rsi, [wa_msg_old]
    lea rdi, [wf_hdr+48]
    mov ecx, wa_msg_old_len
    rep movsb
    mov edx, 112
.send:
    lea rcx, [wf_hdr]
    call wf_send_all
END_FN

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
    lea rdi, [wf_hdr]
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
    cmp eax, 6
    ja .check
    mov ecx, [wa_slot]
    call wf_key_for_slot
    mov [wa_ok], eax
.check:
    cmp dword [wa_ok], 0
    jne .have_key
    lea rdi, [wa_key]
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
    mov ecx, 1
    call wa_refuse
.drop:
    xor eax, eax
.d:
END_FN
