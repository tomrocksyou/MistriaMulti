; Linux Steam ID probe

bits 64
default rel
%include "abi.inc"
extern dlopen, dlsym, dlclose, setenv
section .data
steam_app_env db 'SteamAppId',0
steam_game_env db 'SteamGameId',0
steam_app_value db '2142790',0
section .bss
steam_initial_stack resq 1
section .text
global steam_identity_start
steam_identity_start:
    mov [steam_initial_stack], rsp
    and rsp, -16
    sub rsp, 8
    jmp steam_identity_main
FN si_load
    mov rax, [steam_initial_stack]
    cmp qword [rax], 2
    jne .bad
    lea rdi, [steam_app_env]
    lea rsi, [steam_app_value]
    mov edx, 1
    call setenv wrt ..plt
    lea rdi, [steam_game_env]
    lea rsi, [steam_app_value]
    mov edx, 1
    call setenv wrt ..plt
    mov rax, [steam_initial_stack]
    mov rdi, [rax+16]
    mov esi, 2
    call dlopen wrt ..plt
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN
FN si_lookup
    mov rsi, rcx
    mov rdi, [steam_library]
    call dlsym wrt ..plt
END_FN
FN si_call_zero
    call rcx
END_FN
FN si_call_one
    mov rax, rcx
    mov rdi, rdx
    call rax
END_FN
FN si_close
    mov rdi, [steam_library]
    test rdi, rdi
    jz .done
    call dlclose wrt ..plt
.done:
END_FN
FN si_print
    mov rsi, rcx
    mov edi, 1
    mov eax, 1
    syscall
END_FN
FN si_exit
    mov edi, ecx
    mov eax, 60
    syscall
END_FN
%include "steam_identity.inc"
