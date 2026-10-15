; Release list handling of the manager: parsing, strict validation, version comparison, where each file goes.
; Included by updater.asm after winutil.inc.  The list format and the publishing scheme: docs/RELEASES.md.
;
;   version 0.2.0
;   <64 lowercase hex> mod/mistrimulti/<file>      installed under <game>\mods\mistrimulti\
;   <64 lowercase hex> bin/<tool>.exe              installed next to MistriMulti.exe (whitelisted names only)
;   end <number of file lines>                     a list that lost its tail is rejected
;
; Nothing is trusted: a list is used only when every line is valid.  Rejected: any path outside the two roots,
; ".." or a leading dot, drive letters, backslashes, absolute paths, characters outside [A-Za-z0-9._-], empty or
; reserved (CON, NUL, COM1...) names, duplicates, a missing footer, more than MAX_ENTRIES files.
extern lstrcmpiW

MAX_ENTRIES equ 200
HTTP_MAX equ 1048576                ; largest file or list that will be downloaded
BIN_COUNT equ 4

section .data
WSTR host_raw, "raw.githubusercontent.com"
WSTR host_gh, "github.com"
WSTR path_list_prod, "/tomrocksyou/MistriaMulti/releases/latest/download/latest.txt"
WSTR fmt_prod_mod, "/tomrocksyou/MistriaMulti/v%s/%s"
WSTR fmt_prod_bin, "/tomrocksyou/MistriaMulti/releases/download/v%s/%s"
WSTR fmt_bin_dest, "%s\%s"
WSTR fmt_old, "%s.old"
WSTR fmt_urls_line, `%s %s\r\n`
WSTR sfx_old, ".old"
WSTR sfx_new, ".new"
WSTR txt_tools_unknown, "not checked yet"
WSTR txt_tools_ok, "up to date"
WSTR txt_tools_new, "update available"
WSTR s_urls, "--urls"
mod_prefix db 'mod/mistrimulti/'
mod_manifest db 'mod/mistrimulti/manifest.toml'
mod_manifest_len equ $ - mod_manifest
bin_n0 db 'bin/MistriMulti.exe'
bin_n0_len equ $ - bin_n0
bin_n1 db 'bin/MistriMultiLauncher.exe'
bin_n1_len equ $ - bin_n1
bin_n2 db 'bin/mistrimulti-helper.exe'
bin_n2_len equ $ - bin_n2
bin_n3 db 'bin/mistrimulti-steam-id.exe'
bin_n3_len equ $ - bin_n3
urls_mod db 'mod/mistrimulti/gml/A.gml'
urls_mod_len equ $ - urls_mod
urls_bin db 'bin/MistriMulti.exe'
urls_bin_len equ $ - urls_bin
align 8
; (pointer, length) pairs: the only tool names the manager will ever install
bin_table dq bin_n0, bin_n0_len, bin_n1, bin_n1_len, bin_n2, bin_n2_len, bin_n3, bin_n3_len

section .bss
ent_n resd 1
cur_i resd 1
cur_kind resd 1
ver_inst resd 4
ver_lat resd 4
v_seen_ver resb 1
v_seen_end resb 1
v_manifest resb 1
alignb 8
ent_hex resq MAX_ENTRIES
ent_path resq MAX_ENTRIES
ent_plen resq MAX_ENTRIES
ent_kind resb MAX_ENTRIES           ; 1 mod file, 2 tool binary, 3 the mod's manifest.toml
ent_flag resb MAX_ENTRIES           ; 1 staged (.new written), 2 old file moved to .old, 4 new file in place
ent_host resq 1
srv_override resd 1
have_game resd 1
tools_stale resd 1
tools_text resq 1
n_mod resd 1
n_bin resd 1
self_upd resd 1
app_dir resw 520
self_path resw 520
wold resw 1040

section .text

; rcx = wide version "N", "N.N", "N.N.N" or "N.N.N.N" (1-5 digits each), rdx = dword[4] out (missing groups are 0). eax 1 if valid
FN ver_parse
    mov qword [rdx], 0
    mov qword [rdx+8], 0
    xor r8d, r8d
.group:
    xor eax, eax
    xor r9d, r9d
.dg:
    movzx r10d, word [rcx]
    lea r11d, [r10-'0']
    cmp r11d, 9
    ja .sep
    imul eax, eax, 10
    add eax, r11d
    inc r9d
    cmp r9d, 5
    ja .bad
    add rcx, 2
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
    add rcx, 2
    jmp .group
.ok:
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; rcx, rdx = dword[4] versions -> eax -1 (first is older), 0 (same), 1 (first is newer)
FN ver_cmp
    xor r8d, r8d
.l: mov eax, [rcx+r8*4]
    cmp eax, [rdx+r8*4]
    jb .less
    ja .more
    inc r8d
    cmp r8d, 4
    jb .l
    xor eax, eax
    jmp .d
.less:
    mov eax, -1
    jmp .d
.more:
    mov eax, 1
.d:
END_FN

; Compares the installed mod version with the published one. eax: 0 not installed, 1 older or unreadable (update),
; 2 same, 3 installed is NEWER than the published one (never offered as an update)
FN version_state
    lea rcx, [installed_ver]
    lea rdx, [txt_none]
    call wequal
    test eax, eax
    jnz .none
    lea rcx, [installed_ver]
    lea rdx, [ver_inst]
    call ver_parse
    test eax, eax
    jz .older
    lea rcx, [ver_inst]
    lea rdx, [ver_lat]
    call ver_cmp
    cmp eax, 0
    jl .older
    je .same
    mov eax, 3
    jmp .d
.same:
    mov eax, 2
    jmp .d
.older:
    mov eax, 1
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

; rcx = pointer to the name, edx = length of its part before the first '.'  -> eax 1 if it is a Windows device name
FN reserved_name
    cmp edx, 3
    je .three
    cmp edx, 4
    je .four
    jmp .no
.three:
    mov eax, [rcx]
    and eax, 0x00DFDFDF
    cmp eax, 'CON'
    je .yes
    cmp eax, 'PRN'
    je .yes
    cmp eax, 'AUX'
    je .yes
    cmp eax, 'NUL'
    je .yes
    jmp .no
.four:
    mov eax, [rcx]
    mov edx, eax
    shr edx, 24
    sub edx, '1'
    cmp edx, 8
    ja .no
    and eax, 0x00DFDFDF
    cmp eax, 'COM'
    je .yes
    cmp eax, 'LPT'
    je .yes
.no:
    xor eax, eax
    jmp .d
.yes:
    mov eax, 1
.d:
END_FN

; Classifies the path in m_path / m_pathlen (ASCII, not terminated). eax: 0 invalid, 1 mod file, 2 tool, 3 mod manifest.toml
FN path_kind
    mov r14, [m_path]
    mov rbx, [m_pathlen]
    cmp rbx, 5
    jb .bad
    cmp rbx, 160
    ja .bad
    ; tool binaries: exact whitelist
    lea r12, [bin_table]
    xor r13d, r13d
.bt:
    cmp r13d, BIN_COUNT
    jae .mod
    mov eax, r13d
    shl eax, 4
    mov rdi, [r12+rax]
    mov rcx, [r12+rax+8]
    cmp rcx, rbx
    jne .btn
    mov rsi, r14
    repe cmpsb
    je .isbin
.btn:
    inc r13d
    jmp .bt
.isbin:
    mov eax, 2
    jmp .d
.mod:
    cmp rbx, 17
    jb .bad
    mov rsi, r14
    lea rdi, [mod_prefix]
    mov ecx, 16
    repe cmpsb
    jne .bad
    mov r13d, 16                    ; position
    xor r12d, r12d                  ; length of the current component
    xor r15d, r15d                  ; length of its part before the first dot (-1 once a dot was seen)
    xor edi, edi
    mov r8d, 16                     ; start of the component
.ch:
    cmp r13, rbx
    jae .end
    movzx eax, byte [r14+r13]
    cmp eax, '/'
    je .slash
    cmp eax, '.'
    je .dot
    cmp eax, '-'
    je .norm
    cmp eax, '_'
    je .norm
    lea edx, [rax-'0']
    cmp edx, 9
    jbe .norm
    mov edx, eax
    or edx, 0x20
    sub edx, 'a'
    cmp edx, 25
    ja .bad
.norm:
    test edi, edi
    jnz .adv
    inc r15d
    jmp .adv
.dot:
    test r12d, r12d
    jz .bad                         ; a component may not start with a dot (also rules out "..")
    mov edi, 1
    jmp .adv
.slash:
    test r12d, r12d
    jz .bad                         ; empty component ("//")
    movzx eax, byte [r14+r13-1]
    cmp eax, '.'
    je .bad                         ; component ends with a dot
    lea rcx, [r14+r8]
    mov edx, r15d
    call reserved_name
    test eax, eax
    jnz .bad
    xor r12d, r12d
    xor r15d, r15d
    xor edi, edi
    lea r8, [r13+1]
    inc r13
    jmp .ch
.adv:
    inc r12d
    inc r13
    jmp .ch
.end:
    test r12d, r12d
    jz .bad                         ; ends with a slash
    movzx eax, byte [r14+rbx-1]
    cmp eax, '.'
    je .bad
    lea rcx, [r14+r8]
    mov edx, r15d
    call reserved_name
    test eax, eax
    jnz .bad
    mov eax, 1
    cmp rbx, mod_manifest_len
    jne .d
    mov rsi, r14
    lea rdi, [mod_manifest]
    mov ecx, mod_manifest_len
    repe cmpsb
    jne .mod_ok
    mov eax, 3
    jmp .d
.mod_ok:
    mov eax, 1
    jmp .d
.bad:
    xor eax, eax
.d:
END_FN

; rcx = ASCII digits, rdx = count (1-4) -> eax value, or -1
FN parse_uint
    test rdx, rdx
    jz .bad
    cmp rdx, 4
    ja .bad
    xor eax, eax
    xor r8d, r8d
.l: movzx r9d, byte [rcx+r8]
    sub r9d, '0'
    cmp r9d, 9
    ja .bad
    imul eax, eax, 10
    add eax, r9d
    inc r8
    cmp r8, rdx
    jb .l
    jmp .d
.bad:
    mov eax, -1
.d:
END_FN

; Validates manifest_buf as a whole and fills the ent_* tables. eax 1 = every line is acceptable
FN manifest_validate
    mov dword [ent_n], 0
    mov byte [v_seen_ver], 0
    mov byte [v_seen_end], 0
    mov byte [v_manifest], 0
    mov rax, [manifest_len]
    test rax, rax
    jz .bad
    lea rbx, [manifest_buf]
    lea r15, [rbx+rax]
    cmp byte [r15-1], 10
    jne .bad                        ; the last line is incomplete: the download was cut
.line:
    cmp rbx, r15
    jae .fin
    mov rdi, rbx
.eol:
    cmp byte [rdi], 10
    je .got
    inc rdi
    jmp .eol
.got:
    mov r13, rdi
    sub r13, rbx
    lea r14, [rdi+1]
    test r13, r13
    jz .next
    cmp byte [rbx+r13-1], 13
    jne .nocr
    dec r13
.nocr:
    test r13, r13
    jz .next
    cmp byte [rbx], '#'
    je .next
    cmp byte [v_seen_end], 0
    jne .bad                        ; nothing may follow the footer
    cmp byte [v_seen_ver], 0
    je .version
    cmp r13, 12
    ja .entry
    cmp dword [rbx], 'end '
    jne .entry
    lea rcx, [rbx+4]
    lea rdx, [r13-4]
    call parse_uint
    cmp eax, [ent_n]
    jne .bad
    mov byte [v_seen_end], 1
    jmp .next
.version:
    cmp r13, 9
    jb .bad
    cmp r13, 36
    ja .bad
    mov rax, 'version '
    cmp [rbx], rax
    jne .bad
    lea rcx, [latest_ver]
    lea rdx, [rbx+8]
    lea r8, [r13-8]
    call ascii_to_wide
    lea rcx, [latest_ver]
    lea rdx, [ver_lat]
    call ver_parse
    test eax, eax
    jz .bad
    mov byte [v_seen_ver], 1
    jmp .next
.entry:
    cmp r13, 66
    jb .bad
    cmp byte [rbx+64], ' '
    jne .bad
    xor ecx, ecx
.hx:
    movzx eax, byte [rbx+rcx]
    lea edx, [rax-'0']
    cmp edx, 9
    jbe .hok
    lea edx, [rax-97]
    cmp edx, 5
    ja .bad
.hok:
    inc ecx
    cmp ecx, 64
    jb .hx
    mov r8d, [ent_n]
    cmp r8d, MAX_ENTRIES
    jae .bad
    mov [m_hex], rbx
    lea rax, [rbx+65]
    mov [m_path], rax
    lea rax, [r13-65]
    mov [m_pathlen], rax
    call path_kind
    test eax, eax
    jz .bad
    mov r12d, eax
    mov r8d, [ent_n]
    xor r9d, r9d
.dup:
    cmp r9d, r8d
    jae .add
    lea rax, [ent_plen]
    mov rdx, [rax+r9*8]
    cmp rdx, [m_pathlen]
    jne .dupn
    lea rax, [ent_path]
    mov rsi, [rax+r9*8]
    mov rdi, [m_path]
    mov rcx, rdx
    repe cmpsb
    je .bad                         ; the same file twice
.dupn:
    inc r9d
    jmp .dup
.add:
    lea rax, [ent_hex]
    mov rdx, [m_hex]
    mov [rax+r8*8], rdx
    lea rax, [ent_path]
    mov rdx, [m_path]
    mov [rax+r8*8], rdx
    lea rax, [ent_plen]
    mov rdx, [m_pathlen]
    mov [rax+r8*8], rdx
    lea rax, [ent_kind]
    mov [rax+r8], r12b
    cmp r12d, 3
    jne .cnt
    mov byte [v_manifest], 1
.cnt:
    inc dword [ent_n]
.next:
    mov rbx, r14
    jmp .line
.fin:
    cmp byte [v_seen_ver], 0
    je .bad
    cmp byte [v_seen_end], 0
    je .bad
    cmp byte [v_manifest], 0
    je .bad
    cmp dword [ent_n], 1
    jb .bad
    mov eax, 1
    jmp .d
.bad:
    mov dword [ent_n], 0
    xor eax, eax
.d:
END_FN

; ecx = entry number -> m_hex, m_path, m_pathlen, cur_kind, cur_i
FN entry_load
    mov [cur_i], ecx
    lea rax, [ent_hex]
    mov rdx, [rax+rcx*8]
    mov [m_hex], rdx
    lea rax, [ent_path]
    mov rdx, [rax+rcx*8]
    mov [m_path], rdx
    lea rax, [ent_plen]
    mov rdx, [rax+rcx*8]
    mov [m_pathlen], rdx
    lea rax, [ent_kind]
    movzx eax, byte [rax+rcx]
    mov [cur_kind], eax
END_FN

; Builds for the loaded entry: wurl (URL path), ent_host (server), wpath1 (final file), wpath2 (staged .new), wold (.old).
; The entry was validated by manifest_validate.
FN entry_paths
    lea rcx, [wpath3]
    mov rdx, [m_path]
    mov r8, [m_pathlen]
    call ascii_to_wide
    cmp dword [srv_override], 0
    jne .test_server
    cmp dword [cur_kind], 2
    je .prod_bin
    lea rcx, [wurl]
    lea rdx, [fmt_prod_mod]
    lea r8, [latest_ver]
    lea r9, [wpath3]
    call wsprintfW
    lea rax, [host_raw]
    mov [ent_host], rax
    jmp .url_done
.prod_bin:
    lea rcx, [wurl]
    lea rdx, [fmt_prod_bin]
    lea r8, [latest_ver]
    lea r9, [wpath3+8]
    call wsprintfW
    lea rax, [host_gh]
    mov [ent_host], rax
    jmp .url_done
.test_server:
    lea rcx, [wurl]
    lea rdx, [fmt_url]
    mov r8, [srv_prefix]
    lea r9, [wpath3]
    call wsprintfW
    mov rax, [srv_host]
    mov [ent_host], rax
.url_done:
    cmp dword [cur_kind], 2
    je .bin_dest
    lea rsi, [wpath3+8]             ; skip "mod/"
.sl:
    movzx eax, word [rsi]
    test ax, ax
    jz .sd
    cmp ax, '/'
    jne .sn
    mov word [rsi], '\'
.sn:
    add rsi, 2
    jmp .sl
.sd:
    lea rcx, [wpath1]
    lea rdx, [fmt_mods]
    lea r8, [game_dir]
    lea r9, [wpath3+8]
    call wsprintfW
    jmp .stage
.bin_dest:
    lea rcx, [wpath1]
    lea rdx, [fmt_bin_dest]
    lea r8, [app_dir]
    lea r9, [wpath3+8]              ; skip "bin/"
    call wsprintfW
.stage:
    lea rcx, [wpath2]
    lea rdx, [fmt_new]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wold]
    lea rdx, [fmt_old]
    lea r8, [wpath1]
    call wsprintfW
END_FN

; List URL: wurl and ent_host
FN list_url
    cmp dword [srv_override], 0
    jne .test_server
    lea rcx, [path_list_prod]
    lea rdx, [wurl]
    call wcopy
    lea rax, [host_gh]
    mov [ent_host], rax
    jmp .d
.test_server:
    lea rcx, [wurl]
    lea rdx, [fmt_url]
    mov r8, [srv_prefix]
    lea r9, [latest_path]
    call wsprintfW
    mov rax, [srv_host]
    mov [ent_host], rax
.d:
END_FN

; Is the file at wpath1 identical to the entry in m_hex (SHA-256)? eax 1 / 0 (also 0 when the file is missing)
FN installed_matches
    lea rcx, [wpath1]
    lea rdx, [http_buf]
    mov r8d, HTTP_MAX + 1
    call read_file
    cmp rax, 0
    jl .no
    cmp rax, HTTP_MAX
    ja .no
    lea rcx, [http_buf]
    mov rdx, rax
    call sha256_hex
    test eax, eax
    jz .no
    lea rsi, [hexout]
    mov rdi, [m_hex]
    mov ecx, 64
    repe cmpsb
    jne .no
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

; Counts the tool binaries that are missing or different from the list -> tools_stale, tools_text
FN count_tools
    mov dword [tools_stale], 0
    xor r12d, r12d
.l: cmp r12d, [ent_n]
    jae .done
    mov ecx, r12d
    call entry_load
    cmp dword [cur_kind], 2
    jne .n
    call entry_paths
    call installed_matches
    test eax, eax
    jnz .n
    inc dword [tools_stale]
.n: inc r12d
    jmp .l
.done:
    lea rax, [txt_tools_ok]
    cmp dword [tools_stale], 0
    je .set
    lea rax, [txt_tools_new]
.set:
    mov [tools_text], rax
END_FN

; Deletes the .new and .old files left by an interrupted or earlier update next to MistriMulti.exe. A .old file of a
; program that is still running cannot be deleted; it is tried again at the next start.
FN startup_cleanup
    xor r12d, r12d
.l: cmp r12d, BIN_COUNT
    jae .d
    mov eax, r12d
    shl eax, 4
    lea rdx, [bin_table]
    mov rsi, [rdx+rax]
    mov r13, [rdx+rax+8]
    sub r13, 4                      ; the name without "bin/"
    add rsi, 4
    lea rcx, [wpath3]
    mov rdx, rsi
    mov r8, r13
    call ascii_to_wide
    lea rcx, [wpath1]
    lea rdx, [fmt_bin_dest]
    lea r8, [app_dir]
    lea r9, [wpath3]
    call wsprintfW
    lea rcx, [wpath2]
    lea rdx, [fmt_old]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    call DeleteFileW
    lea rcx, [wpath2]
    lea rdx, [fmt_new]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    call DeleteFileW
    inc r12d
    jmp .l
.d:
END_FN

; rcx = destination -> eax = characters written: "<host> <url path>" of the loaded list/entry, as a CRLF line
FN urls_emit
    mov r8, [ent_host]
    lea rdx, [fmt_urls_line]
    lea r9, [wurl]
    call wsprintfW
END_FN

; test hook   MistriMulti.exe --urls <version> <file>   writes the server and URL path used in production for the
; list, a mod file and a tool binary of that version (no network involved)
FN urls_dump
    mov rax, [argv]
    mov rcx, [rax+16]
    lea rdx, [latest_ver]
    call wcopy
    call list_url
    lea rcx, [http_buf]
    call urls_emit
    lea r12, [rax*2]
    lea rax, [urls_mod]
    mov [m_path], rax
    mov qword [m_pathlen], urls_mod_len
    mov dword [cur_kind], 1
    call entry_paths
    lea rcx, [http_buf]
    add rcx, r12
    call urls_emit
    lea r12, [r12+rax*2]
    lea rax, [urls_bin]
    mov [m_path], rax
    mov qword [m_pathlen], urls_bin_len
    mov dword [cur_kind], 2
    call entry_paths
    lea rcx, [http_buf]
    add rcx, r12
    call urls_emit
    lea r12, [r12+rax*2]
    mov rax, [argv]
    mov rcx, [rax+24]
    lea rdx, [http_buf]
    mov r8, r12
    call write_file
END_FN
