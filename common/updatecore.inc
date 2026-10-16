; Update support of the launchers (Linux: linux/menu.inc, Windows: launcher/menu.inc): the part that does not care about the
; operating system. docs/SYNC-UPDATE.md describes the whole feature.
;
;   1. the update RUN: the in-game Update button sends `cmd=update`; the launcher starts the update program (the manager's
;      `update --result <file>` on Linux, `MistriMulti.exe --update <file>` on Windows) as a child, reads its result file about once
;      a second and publishes state / version / message / error code in menu/status.json (fields us, uv, um, ue, ur).
;   2. the RELEASE CHECK: once a day at most (3 hours after a failed try), a short quiet check of the latest release; the answer
;      is published as `update` (a version, or "none") and remembered in update_check.txt.
;
; Both are driven from sv_poll (chk_step, up_step) which only runs once the game has been started, so neither can delay the game.
; The operating system supplies the plat_* routines (spawn, poll, kill, files, clocks); everything here is plain ASCII logic.
;
; The result file (written by the update program, atomically) is key=value lines:
;   state=checking|downloading|installing|done|failed|needs_momi   version=<x.y.z>   message=<plain words>   error=<number>
; Nothing in it is trusted: the state must be one of the six words, the version must parse as a version, the message is reduced to
; printable ASCII (90 characters, no quote or backslash), the error to 0..999.
;
; Expected from the including file: cfg_get, a_equal, a2i, file_buf, cfg_len, sv_session, sv_status_write, and these
;   plat_ms            -> rax milliseconds (monotonic)
;   plat_unix          -> rax seconds since 1970 (UTC)
;   plat_cfg_read      -> eax 1 if update.cfg was read into file_buf / cfg_len (NUL terminated)
;   plat_cache_read    -> eax 1 if update_check.txt was read into file_buf / cfg_len
;   plat_cache_write   rcx data, rdx length: writes update_check.txt (atomically)
;   plat_manifest_read -> eax 1 if <game>/mods/mistrimulti/manifest.toml was read into file_buf / cfg_len
;   plat_up_limit      -> eax milliseconds replacing the run time limit (tests), 0 for the built-in limits
;   plat_up_prepare / plat_up_start (eax 1 started) / plat_up_poll (rax -1 running, else exit code) / plat_up_kill / plat_up_read (eax 1)
;   plat_chk_start (eax 1 started) / plat_chk_poll (rax -1 running, else exit code) / plat_chk_kill / plat_chk_read (eax 1) / plat_chk_clean

UP_ST_NONE equ 0
UP_ST_CHECKING equ 1
UP_ST_DOWNLOADING equ 2
UP_ST_INSTALLING equ 3
UP_ST_DONE equ 4
UP_ST_FAILED equ 5
UP_ST_MOMI equ 6
UP_ER_BUSY equ 61                    ; hosting or joining: not now
UP_ER_MISSING equ 62                 ; the update program is not next to the launcher
UP_ER_NORESULT equ 63                ; it ended without saying how it went
UP_ER_FAILED equ 64                  ; it ended with a failure it did not describe
UP_ER_TIMEOUT equ 66                 ; killed after too long
UP_RUN_LIMIT_MS equ 300000           ; checking / downloading: 5 minutes
UP_INSTALL_LIMIT_MS equ 900000       ; installing is never cut off earlier
CK_TIMEOUT_MS equ 8000
CK_OK_SECONDS equ 86400
CK_RETRY_SECONDS equ 10800

section .data
uk_state db 6,'state='
uk_version db 8,'version='
uk_message db 8,'message='
uk_error db 6,'error='
uk_code db 5,'code='
uk_checked db 8,'checked='
uk_ok db 3,'ok='
uk_latest db 7,'latest='
uk_check db 6,'check='
us_n0 db 'none',0
us_n1 db 'checking',0
us_n2 db 'downloading',0
us_n3 db 'installing',0
us_n4 db 'done',0
us_n5 db 'failed',0
us_n6 db 'needs_momi',0
uv_off db 'off',0
uv_no db 'no',0
uv_zero db '0',0
uv_false db 'false',0
uj_a db ',"update":"',0
uj_b db '","us":"',0
uj_c db '","uv":"',0
uj_d db '","um":"',0
uj_e db '","ue":',0
uj_f db ',"ur":',0
uj_none db 'none',0
uc_a db 'checked=',0
uc_b db 10,'ok=',0
uc_c db 10,'latest=',0
uc_d db 10,0
align 8
us_names dq us_n0, us_n1, us_n2, us_n3, us_n4, us_n5, us_n6

section .bss
up_limit resd 1
up_state resd 1
up_err resd 1
up_run resd 1
up_active resd 1
up_started resq 1
up_next resq 1
up_ver resb 32
up_msg resb 96
up_latest resb 32
up_installed resb 32
up_raw resb 208
up_tmp resb 32
up_tmp2 resb 32
up_dig resb 16
up_pa resb 16
up_pb resb 16
up_json resb 400
ck_state resd 1
ck_started resq 1
ck_text resb 96
ck_checked resq 1
ck_ok resd 1

section .text
; rcx = ASCII "N", "N.N", "N.N.N" or "N.N.N.N" (1-5 digits each), rdx = dword[4] out (missing groups are 0). eax 1 if valid
FN up_ver_parse
    mov qword [rdx], 0
    mov qword [rdx+8], 0
    xor r8d, r8d
.group:
    xor eax, eax
    xor r9d, r9d
.dg:
    movzx r10d, byte [rcx]
    lea r11d, [r10-'0']
    cmp r11d, 9
    ja .sep
    imul eax, eax, 10
    add eax, r11d
    inc r9d
    cmp r9d, 5
    ja .bad
    inc rcx
    jmp .dg
.sep:
    test r9d, r9d
    jz .bad
    mov [rdx+r8*4], eax
    inc r8d
    test r10d, r10d
    jz .ok
    cmp r10d, '.'
    jne .bad
    cmp r8d, 4
    jae .bad
    inc rcx
    jmp .group
.ok:
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; rcx = version a, rdx = version b (ASCII). eax 1 if both are versions and a is higher than b
FN up_ver_newer
    mov r12, rdx
    lea rdx, [up_pa]
    call up_ver_parse
    test eax, eax
    jz .no
    mov rcx, r12
    lea rdx, [up_pb]
    call up_ver_parse
    test eax, eax
    jz .no
    lea r8, [up_pa]
    lea r9, [up_pb]
    xor ecx, ecx
.l: cmp ecx, 4
    jae .no
    mov eax, [r8+rcx*4]
    cmp eax, [r9+rcx*4]
    ja .yes
    jb .no
    inc ecx
    jmp .l
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; rcx = destination (32 bytes), rdx = source ASCII. Copies the source if it is a valid version, else stores "". eax 1 if copied
FN up_copy_ver
    mov r12, rcx
    mov r13, rdx
    mov rcx, rdx
    lea rdx, [up_pa]
    call up_ver_parse
    mov byte [r12], 0
    test eax, eax
    jz .d
    mov rsi, r13
    mov rdi, r12
.c: lodsb
    stosb
    test al, al
    jnz .c
    mov eax, 1
.d:
END_FN

; rcx = destination (96 bytes), rdx = source ASCII. Keeps printable ASCII only, at most 90 characters; " becomes ' and \ becomes /
FN up_clean_msg
    xor r8d, r8d
.l: movzx eax, byte [rdx]
    inc rdx
    test eax, eax
    jz .e
    cmp eax, 32
    jb .l
    cmp eax, 126
    ja .l
    cmp al, '"'
    jne .a
    mov al, 39
.a: cmp al, 92
    jne .b
    mov al, '/'
.b: mov [rcx+r8], al
    inc r8d
    cmp r8d, 90
    jb .l
.e: mov byte [rcx+r8], 0
END_FN

; rcx = decimal ASCII (1-12 digits) -> rax value, -1 if it is not a number
FN up_atoq
    xor eax, eax
    xor edx, edx
.l: movzx r8d, byte [rcx]
    test r8d, r8d
    jz .e
    sub r8d, '0'
    cmp r8d, 9
    ja .bad
    imul rax, rax, 10
    add rax, r8
    inc edx
    cmp edx, 12
    ja .bad
    inc rcx
    jmp .l
.e: test edx, edx
    jnz .d
.bad:
    mov rax, -1
.d:
END_FN

; rcx = dest, rdx = NUL terminated source -> rax = dest after the copy (no NUL written)
FN up_put
    mov rax, rcx
.l: mov r8b, [rdx]
    test r8b, r8b
    jz .d
    mov [rax], r8b
    inc rax
    inc rdx
    jmp .l
.d:
END_FN

; rcx = dest, edx = unsigned number -> rax = dest after the digits
FN up_put_int
    mov r8, rcx
    mov eax, edx
    lea r9, [up_dig+16]
    xor r10d, r10d
    mov ecx, 10
.l: xor edx, edx
    div ecx
    add dl, '0'
    dec r9
    mov [r9], dl
    inc r10d
    test eax, eax
    jnz .l
.c: mov al, [r9]
    mov [r8], al
    inc r8
    inc r9
    dec r10d
    jnz .c
    mov rax, r8
END_FN

; Applies the result file in file_buf / cfg_len. eax 1 if it named a known state (the other fields are taken with it)
FN up_apply_result
    lea rcx, [uk_state]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
    mov r12d, 1
.s: cmp r12d, 7
    jae .none
    mov eax, r12d
    lea rdx, [us_names]
    mov rdx, [rdx+rax*8]
    lea rcx, [up_tmp]
    call a_equal
    test eax, eax
    jnz .found
    inc r12d
    jmp .s
.none:
    xor eax, eax
    jmp .d
.found:
    mov [up_state], r12d
    lea rcx, [uk_version]
    lea rdx, [up_raw]
    mov r8d, 32
    call cfg_get
    lea rcx, [up_ver]
    lea rdx, [up_raw]
    call up_copy_ver
    lea rcx, [uk_message]
    lea rdx, [up_raw]
    mov r8d, 200
    call cfg_get
    lea rcx, [up_msg]
    lea rdx, [up_raw]
    call up_clean_msg
    lea rcx, [uk_error]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
    test eax, eax
    jnz .num
    lea rcx, [uk_code]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
.num:
    lea rcx, [up_tmp]
    call a2i
    cmp eax, 0
    jl .zero
    cmp eax, 999
    jle .store
.zero:
    xor eax, eax
.store:
    mov [up_err], eax
    mov eax, 1
.d:
END_FN

; -> rax = the version to publish as `update`: the latest release when it is newer than the installed mod, else "none"
FN up_update_text
    lea rax, [uj_none]
    cmp byte [up_latest], 0
    je .d
    cmp byte [up_installed], 0
    je .d
    lea rcx, [up_latest]
    lea rdx, [up_installed]
    call up_ver_newer
    lea rcx, [up_latest]
    lea rdx, [uj_none]
    test eax, eax
    mov rax, rcx
    cmovz rax, rdx
.d:
END_FN

; Builds the update fields of status.json in up_json (no closing brace) -> eax length
FN up_json_make
    lea rcx, [up_json]
    lea rdx, [uj_a]
    call up_put
    mov r12, rax
    call up_update_text
    mov rcx, r12
    mov rdx, rax
    call up_put
    mov rcx, rax
    lea rdx, [uj_b]
    call up_put
    mov r12d, [up_state]
    cmp r12d, 6
    jbe .st
    xor r12d, r12d
.st:
    lea rdx, [us_names]
    mov rdx, [rdx+r12*8]
    mov rcx, rax
    call up_put
    mov rcx, rax
    lea rdx, [uj_c]
    call up_put
    mov rcx, rax
    lea rdx, [up_ver]
    call up_put
    mov rcx, rax
    lea rdx, [uj_d]
    call up_put
    mov rcx, rax
    lea rdx, [up_msg]
    call up_put
    mov rcx, rax
    lea rdx, [uj_e]
    call up_put
    mov rcx, rax
    mov edx, [up_err]
    call up_put_int
    mov rcx, rax
    lea rdx, [uj_f]
    call up_put
    mov rcx, rax
    mov edx, [up_run]
    call up_put_int
    mov byte [rax], 0
    lea rcx, [up_json]
    sub rax, rcx
END_FN

; ---------------- text of latest.txt and manifest.toml ----------------
; file_buf / cfg_len hold a release list ("version 0.4.7" on its first line, blank lines and # comments allowed before it).
; eax 1 and the version in up_tmp2 if found and valid
FN up_parse_latest
    lea rsi, [file_buf]
    mov r12, rsi
    add r12, [cfg_len]
.line:
    cmp rsi, r12
    jae .no
    movzx eax, byte [rsi]
    cmp al, 10
    je .skip1
    cmp al, 13
    je .skip1
    cmp al, '#'
    je .skipline
    mov rax, [rsi]
    mov rcx, 'version '
    cmp rax, rcx
    jne .no
    add rsi, 8
    lea rdi, [up_raw]
    xor ecx, ecx
.c: cmp rsi, r12
    jae .end
    movzx eax, byte [rsi]
    cmp al, 33
    jb .end
    cmp ecx, 30
    jae .no
    mov [rdi+rcx], al
    inc ecx
    inc rsi
    jmp .c
.end:
    mov byte [rdi+rcx], 0
    lea rcx, [up_tmp2]
    lea rdx, [up_raw]
    call up_copy_ver
    jmp .d
.skip1:
    inc rsi
    jmp .line
.skipline:
    cmp rsi, r12
    jae .no
    cmp byte [rsi], 10
    je .skip1
    inc rsi
    jmp .skipline
.no:
    xor eax, eax
.d:
END_FN

; file_buf / cfg_len hold manifest.toml: the first line  version = "x.y.z"  . eax 1 and the version in up_tmp2 if found and valid
FN up_parse_manifest
    lea rsi, [file_buf]
    mov r12, rsi
    add r12, [cfg_len]
.line:
    cmp rsi, r12
    jae .no
    mov eax, [rsi]
    cmp eax, 'vers'
    jne .next
    mov eax, [rsi+4]
    and eax, 0xffffff
    cmp eax, 'ion'
    jne .next
    add rsi, 7
.sp1:
    cmp byte [rsi], ' '
    je .adv1
    cmp byte [rsi], 9
    jne .eq
.adv1:
    inc rsi
    jmp .sp1
.eq:
    cmp byte [rsi], '='
    jne .next
    inc rsi
.sp2:
    cmp byte [rsi], ' '
    jne .q
    inc rsi
    jmp .sp2
.q: cmp byte [rsi], '"'
    jne .next
    inc rsi
    lea rdi, [up_raw]
    xor ecx, ecx
.c: cmp rsi, r12
    jae .no
    movzx eax, byte [rsi]
    cmp al, '"'
    je .end
    cmp al, 32
    jb .no
    cmp ecx, 30
    jae .no
    mov [rdi+rcx], al
    inc ecx
    inc rsi
    jmp .c
.end:
    mov byte [rdi+rcx], 0
    lea rcx, [up_tmp2]
    lea rdx, [up_raw]
    call up_copy_ver
    jmp .d
.next:
    cmp rsi, r12
    jae .no
    cmp byte [rsi], 10
    je .nl
    inc rsi
    jmp .next
.nl:
    inc rsi
    jmp .line
.no:
    xor eax, eax
.d:
END_FN

; Reads the installed mod's version (manifest.toml in the game folder) into up_installed ("" if unknown)
FN up_load_installed
    mov byte [up_installed], 0
    call plat_manifest_read
    test eax, eax
    jz .d
    call up_parse_manifest
    test eax, eax
    jz .d
    lea rcx, [up_installed]
    lea rdx, [up_tmp2]
    call up_copy_ver
.d:
END_FN

; ---------------- the update run ----------------
; cmd=update. One run at a time; refused while hosting or joining; answered in status.json either way.
FN up_cmd_update
    cmp dword [up_active], 0
    jne .publish
    cmp dword [up_state], UP_ST_DONE
    je .publish
    cmp dword [up_state], UP_ST_MOMI
    je .publish
    inc dword [up_run]
    mov dword [up_err], 0
    mov byte [up_ver], 0
    mov byte [up_msg], 0
    cmp dword [sv_session], 0
    je .go
    mov dword [up_state], UP_ST_FAILED
    mov dword [up_err], UP_ER_BUSY
    jmp .publish
.go:
    call plat_up_prepare
    call plat_up_limit
    mov [up_limit], eax
    call plat_up_start
    test eax, eax
    jnz .started
    mov dword [up_state], UP_ST_FAILED
    mov dword [up_err], UP_ER_MISSING
    jmp .publish
.started:
    mov dword [up_active], 1
    mov dword [up_state], UP_ST_CHECKING
    call plat_ms
    mov [up_started], rax
    add rax, 1000
    mov [up_next], rax
.publish:
    call sv_status_write
END_FN

; cmd=update_cancel. Stops a run that is checking or downloading; an installation is never cut off half way.
FN up_cmd_cancel
    cmp dword [up_active], 0
    je .publish
    cmp dword [up_state], UP_ST_INSTALLING
    je .publish
    call plat_up_kill
    mov dword [up_active], 0
    mov dword [up_state], UP_ST_NONE
    mov dword [up_err], 0
    mov byte [up_ver], 0
    mov byte [up_msg], 0
.publish:
    call sv_status_write
END_FN

; Called from every sv_poll: follows a running update program.
FN up_step
    cmp dword [up_active], 0
    je .d
    call plat_ms
    mov r12, rax
    sub rax, [up_started]
    mov ecx, UP_RUN_LIMIT_MS
    mov edx, UP_INSTALL_LIMIT_MS
    cmp dword [up_state], UP_ST_INSTALLING
    cmove ecx, edx
    mov edx, [up_limit]
    test edx, edx
    cmovnz ecx, edx                          ; a test can shorten the limit (MISTRIMULTI_UPDATE_TIMEOUT_MS)
    cmp rax, rcx
    ja .timeout
    call plat_up_poll
    mov r13, rax
    cmp r13, -1
    jne .ended
    cmp r12, [up_next]
    jb .d
    lea rax, [r12+1000]
    mov [up_next], rax
    call plat_up_read
    test eax, eax
    jz .d
    call up_apply_result
    call sv_status_write
    jmp .d
.ended:
    call plat_up_read
    test eax, eax
    jz .judge
    call up_apply_result
.judge:
    mov dword [up_active], 0
    test r13, r13
    jnz .nonzero
    mov eax, [up_state]
    cmp eax, UP_ST_DONE
    je .fin
    cmp eax, UP_ST_MOMI
    je .fin
    cmp eax, UP_ST_FAILED
    je .failed_err
    mov dword [up_state], UP_ST_FAILED       ; exit 0 but no final state in the result file
    mov dword [up_err], UP_ER_NORESULT
    mov byte [up_msg], 0
    jmp .fin
.nonzero:
    cmp dword [up_state], UP_ST_FAILED
    je .failed_err
    mov dword [up_state], UP_ST_FAILED       ; a failure exit code outranks a hopeful state
    mov dword [up_err], UP_ER_FAILED
    mov byte [up_msg], 0
    jmp .fin
.failed_err:
    cmp dword [up_err], 0
    jne .fin
    mov dword [up_err], UP_ER_FAILED
.fin:
    cmp dword [up_state], UP_ST_DONE
    jne .publish
    call up_load_installed                   ; the new mod files are in place: `update` becomes "none" if it is the latest
.publish:
    call sv_status_write
    jmp .d
.timeout:
    call plat_up_kill
    mov dword [up_active], 0
    mov dword [up_state], UP_ST_FAILED
    mov dword [up_err], UP_ER_TIMEOUT
    mov byte [up_msg], 0
    call sv_status_write
.d:
END_FN

; ---------------- the release check ----------------
; Writes update_check.txt: checked=<now> ok=<0|1> latest=<known latest or nothing>. ecx = ok
FN ck_save
    mov r12d, ecx
    lea rcx, [ck_text]
    lea rdx, [uc_a]
    call up_put
    mov r13, rax
    call plat_unix
    mov rcx, r13
    mov edx, eax
    call up_put_int
    mov rcx, rax
    lea rdx, [uc_b]
    call up_put
    mov rcx, rax
    mov edx, r12d
    call up_put_int
    mov rcx, rax
    lea rdx, [uc_c]
    call up_put
    mov rcx, rax
    lea rdx, [up_latest]
    call up_put
    mov rcx, rax
    lea rdx, [uc_d]
    call up_put
    lea rcx, [ck_text]
    sub rax, rcx
    mov rdx, rax
    call plat_cache_write
END_FN

; First call after the game started (from sv_poll), then every call until the check ended.
FN chk_step
    mov eax, [ck_state]
    cmp eax, 2
    jae .d
    test eax, eax
    jnz .running
    mov dword [ck_state], 2                 ; ended unless a program is started below
    call up_load_installed
    call plat_cfg_read
    test eax, eax
    jz .cache
    lea rcx, [uk_check]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
    call ck_word
    test eax, eax
    jnz .publish                            ; the player turned the check off: update stays "none"
.cache:
    mov byte [up_latest], 0
    mov qword [ck_checked], 0
    mov dword [ck_ok], 0
    call plat_cache_read
    test eax, eax
    jz .ask
    lea rcx, [uk_checked]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
    lea rcx, [up_tmp]
    call up_atoq
    test rax, rax
    js .ask
    mov [ck_checked], rax
    lea rcx, [uk_ok]
    lea rdx, [up_tmp]
    mov r8d, 16
    call cfg_get
    cmp byte [up_tmp], '1'
    sete al
    movzx eax, al
    mov [ck_ok], eax
    lea rcx, [uk_latest]
    lea rdx, [up_raw]
    mov r8d, 32
    call cfg_get
    lea rcx, [up_latest]
    lea rdx, [up_raw]
    call up_copy_ver
    call plat_unix
    mov rcx, [ck_checked]
    cmp rax, rcx
    jb .ask                                 ; the clock went back: do not trust the stamp
    sub rax, rcx
    mov edx, CK_RETRY_SECONDS
    mov ecx, CK_OK_SECONDS
    cmp dword [ck_ok], 0
    cmovne rdx, rcx
    cmp rax, rdx
    jb .publish                             ; checked recently: the remembered answer stands
.ask:
    call plat_chk_start
    test eax, eax
    jz .publish
    mov dword [ck_state], 1
    call plat_ms
    mov [ck_started], rax
.publish:
    call sv_status_write
    jmp .d
.running:
    call plat_ms
    sub rax, [ck_started]
    cmp rax, CK_TIMEOUT_MS
    ja .timeout
    call plat_chk_poll
    cmp rax, -1
    je .d
    test rax, rax
    jnz .fail
    call plat_chk_read
    test eax, eax
    jz .fail
    call up_parse_latest
    test eax, eax
    jz .fail
    lea rcx, [up_latest]
    lea rdx, [up_tmp2]
    call up_copy_ver
    mov ecx, 1
    jmp .end
.timeout:
    call plat_chk_kill
.fail:
    xor ecx, ecx                            ; a failed try is silent: the old answer stays, the next try is in three hours
.end:
    call ck_save
    call plat_chk_clean
    mov dword [ck_state], 2
    call sv_status_write
.d:
END_FN

; up_tmp holds the value of a config line. eax 1 if it says off / no / 0 / false (any case)
FN ck_word
    lea rsi, [up_tmp]
.lc:movzx eax, byte [rsi]
    test eax, eax
    jz .cmp
    mov ecx, eax
    sub ecx, 'A'
    cmp ecx, 25
    ja .nx
    or byte [rsi], 32
.nx:inc rsi
    jmp .lc
.cmp:
    lea rcx, [up_tmp]
    lea rdx, [uv_off]
    call a_equal
    test eax, eax
    jnz .d
    lea rcx, [up_tmp]
    lea rdx, [uv_no]
    call a_equal
    test eax, eax
    jnz .d
    lea rcx, [up_tmp]
    lea rdx, [uv_zero]
    call a_equal
    test eax, eax
    jnz .d
    lea rcx, [up_tmp]
    lea rdx, [uv_false]
    call a_equal
.d:
END_FN
