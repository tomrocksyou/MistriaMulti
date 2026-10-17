; Windows Steam ID probe

bits 64
default rel
%define WINDOWS 1
%include "abi.inc"
extern GetCommandLineW, CommandLineToArgvW, LocalFree, LoadLibraryExW, GetProcAddress
extern FreeLibrary, GetStdHandle, WriteFile, ExitProcess, SetEnvironmentVariableW
section .data
steam_app_env dw 'S','t','e','a','m','A','p','p','I','d',0
steam_game_env dw 'S','t','e','a','m','G','a','m','e','I','d',0
steam_app_value dw '2','1','4','2','7','9','0',0
section .bss
steam_argc resd 1
steam_argv resq 1
steam_written resd 1
section .text
FN si_load
    call GetCommandLineW
    mov rcx, rax
    lea rdx, [steam_argc]
    call CommandLineToArgvW
    mov [steam_argv], rax
    test rax, rax
    jz .bad
    cmp dword [steam_argc], 2
    jne .bad
    lea rcx, [steam_app_env]
    lea rdx, [steam_app_value]
    call SetEnvironmentVariableW
    lea rcx, [steam_game_env]
    lea rdx, [steam_app_value]
    call SetEnvironmentVariableW
    mov rax, [steam_argv]
    mov rcx, [rax+8]
    xor edx, edx
    mov r8d, 0x1100
    call LoadLibraryExW
    jmp .done
.bad:
    xor eax, eax
.done:
END_FN
FN si_lookup
    mov rdx, rcx
    mov rcx, [steam_library]
    call GetProcAddress
END_FN
FN si_call_zero
    call rcx
END_FN
FN si_call_one
    mov rax, rcx
    mov rcx, rdx
    call rax
END_FN
FN si_close
    mov rcx, [steam_library]
    test rcx, rcx
    jz .done
    call FreeLibrary
.done:
END_FN
FN si_print
    mov r12, rcx
    mov r13, rdx
    mov ecx, -11
    call GetStdHandle
    mov rcx, rax
    mov rdx, r12
    mov r8d, r13d
    lea r9, [steam_written]
    mov qword [rsp+32], 0
    call WriteFile
END_FN
FN si_exit
    mov r12d, ecx
    mov rcx, [steam_argv]
    test rcx, rcx
    jz .exit
    call LocalFree
.exit:
    mov ecx, r12d
    call ExitProcess
END_FN
%include "steam_identity.inc"
