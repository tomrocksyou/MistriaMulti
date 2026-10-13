; Steam identity reader using the flat Steamworks API.
; Platform adapters accept an absolute path to the game's own Steam library.
section .data
steam_init_name db 'SteamAPI_InitFlat',0
steam_shutdown_name db 'SteamAPI_Shutdown',0
steam_user_name db 'SteamAPI_SteamUser_v023',0
steam_id_name db 'SteamAPI_ISteamUser_GetSteamID',0
steam_prefix db 'steam:'
section .bss
steam_library resq 1
steam_initialized resd 1
steam_decimal resb 32
steam_result resb 32
section .text
FN steam_identity_main
    call si_load
    test rax, rax
    jz .failed
    mov [steam_library], rax
    lea rcx, [steam_init_name]
    call si_lookup
    test rax, rax
    jz .failed
    mov r12, rax
    lea rcx, [steam_shutdown_name]
    call si_lookup
    test rax, rax
    jz .failed
    mov r13, rax
    lea rcx, [steam_user_name]
    call si_lookup
    test rax, rax
    jz .failed
    mov r14, rax
    lea rcx, [steam_id_name]
    call si_lookup
    test rax, rax
    jz .failed
    mov r15, rax
    mov rcx, r12
    xor edx, edx ; optional error-message buffer is null
    call si_call_one
    test eax, eax ; ESteamAPIInitResult_OK = 0
    jnz .failed
    mov dword [steam_initialized], 1
    mov rcx, r14
    call si_call_zero
    test rax, rax
    jz .failed
    mov rdx, rax
    mov rcx, r15
    call si_call_one
    mov r12, rax
    ; Public-universe individual account, default desktop instance, nonzero ID.
    mov rdx, rax
    shr rdx, 32
    cmp edx, 0x01100001
    jne .failed
    test eax, eax
    jz .failed
    mov rcx, r13
    call si_call_zero
    mov dword [steam_initialized], 0
    call si_close
    mov rax, r12
    lea rdi, [steam_decimal+31]
    mov ebx, 10
.digits:
    xor edx, edx
    div rbx
    add dl, '0'
    dec rdi
    mov [rdi], dl
    test rax, rax
    jnz .digits
    lea rsi, [steam_prefix]
    lea rdx, [steam_result]
    mov ecx, 6
.prefix:
    mov al, [rsi]
    mov [rdx], al
    inc rsi
    inc rdx
    dec ecx
    jnz .prefix
    lea r8, [steam_decimal+31]
.copy:
    cmp rdi, r8
    jae .print
    mov al, [rdi]
    mov [rdx], al
    inc rdi
    inc rdx
    jmp .copy
.print:
    mov byte [rdx], 10
    inc rdx
    lea rcx, [steam_result]
    sub rdx, rcx
    call si_print
    xor ecx, ecx
    call si_exit
.failed:
    cmp dword [steam_initialized], 0
    je .unload
    mov rcx, r13
    call si_call_zero
.unload:
    call si_close
    mov ecx, 2 ; no identity: caller may use an explicitly local fallback
    call si_exit
END_FN
