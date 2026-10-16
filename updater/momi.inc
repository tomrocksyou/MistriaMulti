; MOMI step of the manager: after an update changed the mod files, MOMI has to rebuild the game's data. Two ways:
;  1. the player's chosen MOMI command-line program (a file name containing "-cli"), run for them, ONLY after they agree in a
;     question each time, with EXIT_ON_COMPLETE=true so it does not wait for a key. It is started in the game folder and gets no
;     arguments: per MOMI's public source (Program.cs, Standalone.cs) no arguments means "install every mod in the mods folder".
;  2. otherwise (no CLI chosen, declined, failed) the chosen MOMI window program is opened and the player is told to press Install.
; Nothing is searched for or guessed: both paths are chosen by the player once (or set by the tests through the environment).
; Facts and what is unverified: docs/MOMI-NOTES.md.
extern ShellExecuteW, GetOpenFileNameW, SetEnvironmentVariableW, MessageBoxW, EnableWindow, PeekMessageW
extern GetExitCodeProcess, WaitForSingleObject, GetTickCount64

section .data
WSTR mo_t_button, "Open MOMI"
WSTR mo_e_exe, "MISTRIMULTI_MOMI_EXE"
WSTR mo_e_cli, "MISTRIMULTI_MOMI_CLI_EXE"
WSTR mo_e_consent, "MISTRIMULTI_MOMI_CONSENT"
WSTR mo_e_exit, "EXIT_ON_COMPLETE"
WSTR mo_v_true, "true"
WSTR mo_v_yes, "yes"
WSTR mo_f_cfg, "%s\FieldsOfMistria\mod_data\mistrimulti\momi.cfg"
WSTR mo_f_cfgcli, "%s\FieldsOfMistria\mod_data\mistrimulti\momi-cli.cfg"
WSTR mo_f_q, `"%s"`
WSTR mo_verb, "open"
mo_filter: dw __utf16__("Programs (*.exe)"), 0, __utf16__("*.exe"), 0, 0
WSTR mo_title, "Choose the Mods of Mistria (MOMI) program, the one with a window (or its command-line program)"
WSTR mo_c_title, "MistriMulti: run MOMI's installer?"
mo_c_text: dw __utf16__(`MistriMulti is updated. MOMI must now rebuild the game's data.\r\n\r\nRun MOMI's command-line installer for you?\r\n\r\n%s\r\n\r\nClose Fields of Mistria first. It installs every mod in your mods folder, not only the ones ticked in the MOMI window. Choose No to do it yourself in MOMI.`), 0
mo_m_ok: dw __utf16__(`MOMI was opened.\r\n\r\n1. Close Fields of Mistria if it is running.\r\n2. In MOMI, select MistriaMulti and click Install.\r\n3. Start the game from Steam.`), 0
mo_m_none: dw __utf16__(`MOMI was not found. Press Open MOMI again and choose the MOMI program (the one with a window). The choice is remembered.`), 0
mo_m_cli: dw __utf16__(`That is MOMI's command-line program, which the Open MOMI button does not run. Choose the MOMI program that has a window.`), 0
mo_m_clisaved: dw __utf16__(`MOMI's command-line program was saved. After the next update, Update MistriMulti offers to run it for you (you are asked each time).\r\n\r\nPress Open MOMI again to also choose the MOMI program with a window.`), 0
mo_m_fail: dw __utf16__(`MOMI could not be started. Open it yourself, select MistriaMulti and click Install.`), 0
mo_r_ok: dw __utf16__(`Updated to %s and MOMI's installer finished (exit code 0).\r\n\r\nStart the game from Steam. If the mod is missing in the game, close the game, press Open MOMI and click Install.`), 0
mo_r_bad: dw __utf16__(`Updated to %s, but MOMI's installer reported a problem (exit code %d).\r\n\r\nClose the game, press Open MOMI, select MistriaMulti and click Install; the MOMI window shows what went wrong.`), 0
mo_r_nostart: dw __utf16__(`Updated to %s, but MOMI's installer could not be started.\r\n\r\nClose the game, press Open MOMI, select MistriaMulti and click Install.`), 0
mo_r_wait: dw __utf16__(`Updated to %s. MOMI's installer is still running. Wait for it to finish, then start the game.`), 0
mo_r_declined: dw __utf16__(`Updated to %s. MOMI's installer was not run.\r\n\r\nClose the game, press Open MOMI, select MistriaMulti and click Install.`), 0
mo_r_prefix: dw __utf16__(`Updated to %s.\r\n\r\n`), 0

section .bss
momi_quiet resd 1
momi_exit resd 1
momi_declined resd 1
momi_path resw 1040
momi_cli_path resw 1040
momi_cmd resw 1100
momi_text resw 1400
momi_ofn resb 152
mo_fenv resq 1
mo_ffmt resq 1
mo_fout resq 1

section .text

; rcx = format of the file name (mo_f_cfg / mo_f_cfgcli). wpath2 = that file under %LOCALAPPDATA%\FieldsOfMistria\mod_data\mistrimulti  eax 1 ok
FN momi_cfg_path
    mov r12, rcx
    lea rcx, [mp_e_local]
    lea rdx, [wpath1]
    mov r8d, 400
    call GetEnvironmentVariableW
    test eax, eax
    jz .bad
    cmp eax, 400
    ja .bad
    lea rcx, [wpath2]
    mov rdx, r12
    lea r8, [wpath1]
    call wsprintfW
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; Does the file name part of the wide path in rcx contain "-cli" (any case: ModsOfMistriaInstaller-cli.exe, ...-cli-linux)? eax 1 / 0
FN momi_is_cli
    mov rsi, rcx
    mov rdi, rcx
.sc:
    movzx eax, word [rsi]
    test eax, eax
    jz .scan
    cmp eax, '\'
    je .sep
    cmp eax, '/'
    jne .nx
.sep:
    lea rdi, [rsi+2]
.nx:
    add rsi, 2
    jmp .sc
.scan:
    movzx eax, word [rdi]
    test eax, eax
    jz .no
    cmp eax, '-'
    jne .n
    movzx eax, word [rdi+2]
    or eax, 0x20
    cmp eax, 'c'
    jne .n
    movzx eax, word [rdi+4]
    or eax, 0x20
    cmp eax, 'l'
    jne .n
    movzx eax, word [rdi+6]
    or eax, 0x20
    cmp eax, 'i'
    jne .n
    mov eax, 1
    jmp .d
.n:
    add rdi, 2
    jmp .scan
.no:
    xor eax, eax
.d:
END_FN

; Looks for a MOMI program: the environment variable rcx names, then the choice saved in the file whose format is rdx; r8 = buffer for
; the path (520 characters). Nothing else is searched. eax 1 found
FN momi_find_x
    mov [mo_fenv], rcx
    mov [mo_ffmt], rdx
    mov [mo_fout], r8
    mov rdx, r8
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jz .cfg
    cmp eax, 520
    jae .cfg
    mov rcx, [mo_fout]
    call file_exists
    test eax, eax
    jnz .found
.cfg:
    mov rcx, [mo_ffmt]
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
    mov rdx, [mo_fout]
    call wcopy
    mov rcx, [mo_fout]
    call file_exists
    test eax, eax
    jz .none
.found:
    mov eax, 1
    jmp .d
.none:
    mov rax, [mo_fout]
    mov word [rax], 0
    xor eax, eax
.d:
END_FN

FN momi_find
    lea rcx, [mo_e_exe]
    lea rdx, [mo_f_cfg]
    lea r8, [momi_path]
    call momi_find_x
END_FN

FN momi_find_cli
    lea rcx, [mo_e_cli]
    lea rdx, [mo_f_cfgcli]
    lea r8, [momi_cli_path]
    call momi_find_x
END_FN

; Remembers the program rcx in the file whose name format is rdx (see momi_cfg_path)
FN momi_remember
    mov r12, rcx
    mov rcx, rdx
    call momi_cfg_path
    test eax, eax
    jz .d
    lea rcx, [wpath2]
    call ensure_dirs
    mov rcx, r12
    call lstrlenW
    lea r8d, [rax*2]
    lea rcx, [wpath2]
    mov rdx, r12
    call write_file
.d:
END_FN

; Asks the player for a MOMI program once. eax 1 if one was chosen (momi_path)
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

; Opens the chosen MOMI window program (momi_path) in its own folder, with no arguments. eax 1 if it started
FN momi_exec_gui
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
    xor ecx, ecx
    cmp rax, 32
    seta cl
    mov eax, ecx
END_FN

; The button: find MOMI (ask once), open it, and tell the player what to click. Never passes arguments to MOMI's window program.
; A command-line program chosen here is only remembered (momi-cli.cfg); it is run by "Update MistriMulti", after a question.
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
    lea rcx, [momi_path]            ; remember the choice
    lea rdx, [mo_f_cfg]
    call momi_remember
.run:
    call momi_exec_gui
    test eax, eax
    jz .fail
    lea rcx, [mo_m_ok]
    jmp .say
.fail:
    lea rcx, [mo_m_fail]
    jmp .say
.cli:
    lea rcx, [mo_m_cli]
    test r13d, r13d
    jz .say
    lea rcx, [momi_path]            ; just chosen: keep it for the one-click update, do not run it now
    lea rdx, [mo_f_cfgcli]
    call momi_remember
    lea rcx, [mo_m_clisaved]
    jmp .say
.none:
    lea rcx, [mo_m_none]
.say:
    call set_state
END_FN

; rcx = message with one %s (the version) and optionally one %d (momi_exit). It becomes the status.
FN momi_say_version
    mov r12, rcx
    lea rcx, [done_msg]
    mov rdx, r12
    lea r8, [latest_ver]
    mov r9d, [momi_exit]
    call wsprintfW
    lea rcx, [done_msg]
    call set_state
END_FN

; May the command-line installer run? A question each time; hidden test mode: only with MISTRIMULTI_MOMI_CONSENT=yes. eax 1 yes
FN momi_consent
    cmp dword [momi_quiet], 0
    je .ask
    lea rcx, [mo_e_consent]
    lea rdx, [wpath1]
    mov r8d, 8
    call GetEnvironmentVariableW
    test eax, eax
    jz .no
    lea rcx, [wpath1]
    lea rdx, [mo_v_yes]
    call wequal
    jmp .d
.ask:
    lea rcx, [momi_text]
    lea rdx, [mo_c_text]
    lea r8, [momi_cli_path]
    call wsprintfW
    mov rcx, [h_wnd]
    lea rdx, [momi_text]
    lea r8, [mo_c_title]
    mov r9d, 0x24                   ; MB_YESNO | MB_ICONQUESTION
    call MessageBoxW
    xor ecx, ecx
    cmp eax, 6                      ; IDYES
    sete cl
    mov eax, ecx
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; Runs momi_cli_path with no arguments in the game folder, EXIT_ON_COMPLETE=true, no window. Waits up to 5 minutes (the manager's window
; keeps repainting). eax: 0 could not start, 1 exit code 0, 2 another exit code (momi_exit), 3 still running
FN momi_run_cli
    mov dword [momi_exit], 0
    lea rcx, [mo_e_exit]
    lea rdx, [mo_v_true]
    call SetEnvironmentVariableW
    lea rcx, [momi_cmd]
    lea rdx, [mo_f_q]
    lea r8, [momi_cli_path]
    call wsprintfW
    lea rdx, [game_dir]
    cmp dword [have_game], 0
    jne .gd
    xor edx, edx
.gd:
    lea rcx, [momi_cmd]
    xor r8d, r8d
    mov r9d, 0x08000000             ; CREATE_NO_WINDOW
    call spawn
    test rax, rax
    jz .nostart
    mov rbx, rax
    cmp dword [momi_quiet], 0
    jne .go
    mov rcx, [h_wnd]
    xor edx, edx
    call EnableWindow
.go:
    call GetTickCount64
    mov r14, rax
.w:
    mov rcx, rbx
    mov edx, 50
    call WaitForSingleObject
    test eax, eax
    jz .done
    cmp dword [momi_quiet], 0
    jne .tm
.pk:
    lea rcx, [msg]
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 1           ; PM_REMOVE
    call PeekMessageW
    test eax, eax
    jz .tm
    lea rcx, [msg]
    call TranslateMessage
    lea rcx, [msg]
    call DispatchMessageW
    jmp .pk
.tm:
    call GetTickCount64
    sub rax, r14
    cmp rax, 300000
    jb .w
    mov r15d, 3
    jmp .closed
.done:
    mov rcx, rbx
    lea rdx, [momi_exit]
    call GetExitCodeProcess
    mov r15d, 1
    cmp dword [momi_exit], 0
    je .closed
    mov r15d, 2
.closed:
    mov rcx, rbx
    call CloseHandle
    cmp dword [momi_quiet], 0
    jne .ret
    mov rcx, [h_wnd]
    mov edx, 1
    call EnableWindow
.ret:
    mov eax, r15d
    jmp .d
.nostart:
    xor eax, eax
.d:
END_FN

; After an update that changed mod files: run the chosen MOMI command-line installer (after a question), else open the chosen MOMI
; window program, else leave the "press Open MOMI" instructions in the status.
FN momi_after_update
    mov dword [momi_declined], 0
    call momi_find_cli
    test eax, eax
    jz .gui
    lea rcx, [momi_cli_path]
    call momi_is_cli                ; a program whose name has no "-cli" is never run here
    test eax, eax
    jz .gui
    call momi_consent
    test eax, eax
    jz .declined
    call momi_run_cli
    cmp eax, 1
    je .ok
    cmp eax, 2
    je .bad
    cmp eax, 3
    je .wait
    lea rcx, [mo_r_nostart]
    jmp .say
.ok:
    lea rcx, [mo_r_ok]
    jmp .say
.bad:
    lea rcx, [mo_r_bad]
    jmp .say
.wait:
    lea rcx, [mo_r_wait]
    jmp .say
.declined:
    mov dword [momi_declined], 1
.gui:
    call momi_find
    test eax, eax
    jz .nogui
    lea rcx, [momi_path]
    call momi_is_cli
    test eax, eax
    jnz .nogui
    call momi_exec_gui
    test eax, eax
    jz .nogui
    lea rcx, [done_msg]
    lea rdx, [mo_r_prefix]
    lea r8, [latest_ver]
    call wsprintfW
    lea rcx, [done_msg]
    lea rdx, [mo_m_ok]
    lea r8, [done_msg]
    call join_wide
    lea rcx, [done_msg]
    call set_state
    jmp .d
.nogui:
    cmp dword [momi_declined], 0
    je .d                           ; nothing chosen: the update message already says "press Open MOMI"
    lea rcx, [mo_r_declined]
.say:
    call momi_say_version
.d:
END_FN
