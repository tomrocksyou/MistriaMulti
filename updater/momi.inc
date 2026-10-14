; "Open MOMI": finds the Mods of Mistria installer window program and opens it, with the steps to follow.
; Included by updater.asm after mp.inc.
;
; Why it only OPENS MOMI: the MMAPI documents describe MOMI's command line (project ModsOfMistriaCommandLine) only for
; checks that write nothing (--lint, --seam-check, --reseed-check, --seam-diff, with --strict-lints, --compile-check,
; --fail-on-skip). They say that mods are installed by "running the installer (GUI or command line)" but never give
; the command or its arguments, and nothing documents the install's exit codes. Nothing is invented here: no
; argument is passed to MOMI, and the command-line program is refused. See docs/RELEASES.md.
extern ShellExecuteW, GetOpenFileNameW

section .data
WSTR mo_t_button, "Open MOMI"
WSTR mo_e_exe, "MISTRIMULTI_MOMI_EXE"
WSTR mo_f_cfg, "%s\FieldsOfMistria\mod_data\mistrimulti\momi.cfg"
WSTR mo_verb, "open"
WSTR mo_cli, "-cli.exe"
mo_filter: dw __utf16__("Programs (*.exe)"), 0, __utf16__("*.exe"), 0, 0
WSTR mo_title, "Choose the Mods of Mistria (MOMI) program, the one with a window"
mo_m_ok: dw __utf16__(`MOMI was opened.\r\n\r\n1. Close Fields of Mistria if it is running.\r\n2. In MOMI, select MistriaMulti and click Install.\r\n3. Start the game from Steam.`), 0
mo_m_none: dw __utf16__(`MOMI was not found. Press Open MOMI again and choose the MOMI program (the one with a window). The choice is remembered.`), 0
mo_m_cli: dw __utf16__(`That is MOMI's command-line program, which this manager does not run. Choose the MOMI program that has a window.`), 0
mo_m_fail: dw __utf16__(`MOMI could not be started. Open it yourself, select MistriaMulti and click Install.`), 0

section .bss
momi_quiet resd 1
momi_path resw 1040
momi_ofn resb 152

section .text

; wpath2 = %LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti\momi.cfg   eax 1 ok
FN momi_cfg_path
    lea rcx, [mp_e_local]
    lea rdx, [wpath1]
    mov r8d, 400
    call GetEnvironmentVariableW
    test eax, eax
    jz .bad
    cmp eax, 400
    ja .bad
    lea rcx, [wpath2]
    lea rdx, [mo_f_cfg]
    lea r8, [wpath1]
    call wsprintfW
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; Is the wide path in rcx the command-line program ("...-cli.exe")? eax 1 / 0
FN momi_is_cli
    mov r12, rcx
    call lstrlenW
    mov ecx, eax
    cmp ecx, 8
    jb .no
    lea rcx, [r12+rcx*2-16]
    lea rdx, [mo_cli]
    call lstrcmpiW
    test eax, eax
    jnz .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; Looks for MOMI: MISTRIMULTI_MOMI_EXE, then the choice saved in momi.cfg. momi_path = program. eax 1 found
FN momi_find
    lea rcx, [mo_e_exe]
    lea rdx, [momi_path]
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jz .cfg
    cmp eax, 520
    jae .cfg
    lea rcx, [momi_path]
    call file_exists
    test eax, eax
    jnz .found
.cfg:
    call momi_cfg_path
    test eax, eax
    jz .none
    lea rcx, [wpath2]
    lea rdx, [file_buf]
    mov r8d, 2000
    call read_file
    cmp rax, 6
    jl .none
    and eax, -2
    lea rdx, [file_buf]
    mov word [rdx+rax], 0
    shr eax, 1
    ; trim trailing CR, LF and spaces
.trim:
    test eax, eax
    jz .none
    movzx ecx, word [rdx+rax*2-2]
    cmp ecx, 32
    ja .trimmed
    mov word [rdx+rax*2-2], 0
    dec eax
    jmp .trim
.trimmed:
    lea rcx, [file_buf]
    lea rdx, [momi_path]
    call wcopy
    lea rcx, [momi_path]
    call file_exists
    test eax, eax
    jz .none
.found:
    mov eax, 1
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

; Asks the player for the MOMI program once. eax 1 if one was chosen (momi_path)
FN momi_pick
    lea rdi, [momi_ofn]
    xor eax, eax
    mov ecx, 152
    rep stosb
    mov word [momi_path], 0
    mov dword [momi_ofn], 152
    mov rax, [h_wnd]
    mov [momi_ofn+8], rax
    lea rax, [mo_filter]
    mov [momi_ofn+24], rax
    mov dword [momi_ofn+44], 1
    lea rax, [momi_path]
    mov [momi_ofn+48], rax
    mov dword [momi_ofn+56], 520
    lea rax, [mo_title]
    mov [momi_ofn+88], rax
    mov dword [momi_ofn+96], 0x1808      ; file must exist, path must exist, keep the working folder
    lea rcx, [momi_ofn]
    call GetOpenFileNameW
END_FN

; The button: find MOMI (ask once), open it, and tell the player what to click. Never passes arguments to MOMI.
FN momi_open
    xor r13d, r13d                  ; 1 when the player just chose the program
    call momi_find
    test eax, eax
    jnz .have
    cmp dword [momi_quiet], 0
    jne .none
    call momi_pick
    test eax, eax
    jz .none
    mov r13d, 1
.have:
    lea rcx, [momi_path]
    call momi_is_cli
    test eax, eax
    jnz .cli
    test r13d, r13d
    jz .run
    call momi_cfg_path              ; remember the choice
    test eax, eax
    jz .run
    lea rcx, [wpath2]
    call ensure_dirs
    lea rcx, [momi_path]
    call lstrlenW
    lea r8d, [rax*2]
    lea rcx, [wpath2]
    lea rdx, [momi_path]
    call write_file
.run:
    lea rcx, [momi_path]
    lea rdx, [wpath3]
    call wcopy
    lea rcx, [wpath3]
    call cut_last_component
    xor ecx, ecx
    cmp dword [momi_quiet], 0
    jne .exec
    mov rcx, [h_wnd]
.exec:
    lea rdx, [mo_verb]
    lea r8, [momi_path]
    xor r9d, r9d
    lea rax, [wpath3]
    mov [rsp+32], rax
    mov qword [rsp+40], 1           ; SW_SHOWNORMAL
    call ShellExecuteW
    cmp rax, 32
    jbe .fail
    lea rcx, [mo_m_ok]
    jmp .say
.fail:
    lea rcx, [mo_m_fail]
    jmp .say
.cli:
    lea rcx, [mo_m_cli]
    jmp .say
.none:
    lea rcx, [mo_m_none]
.say:
    call set_state
END_FN
