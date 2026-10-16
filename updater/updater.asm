; MistriaMulti updater: a plain Win32 window written in NASM. No C runtime.
; Shows the installed and latest version, updates the mod files, and backs up solo saves.
bits 64
default rel
%define WINDOWS 1
%include "abi.inc"

%macro WSTR 2
%1: dw __utf16__(%2), 0
%endmacro

extern GetModuleHandleW, ExitProcess, GetCommandLineW, LocalFree, GetFileAttributesW, CreateFileW, ReadFile, CloseHandle
extern CommandLineToArgvW
extern RegisterClassExW, CreateWindowExW, DefWindowProcW, ShowWindow, UpdateWindow, GetMessageW, TranslateMessage
extern DispatchMessageW, PostQuitMessage, SendMessageW, SetWindowTextW, LoadCursorW, wsprintfW
extern UpdateWindow, GetModuleFileNameW, GetStockObject, GetEnvironmentVariableW, CreateDirectoryW, CopyFileW, DeleteFileW, MoveFileExW, WriteFile
extern FindFirstFileW, FindNextFileW, FindClose, GetLocalTime, lstrlenW
extern SHGetKnownFolderPath, CoTaskMemFree
extern WinHttpOpen, WinHttpConnect, WinHttpOpenRequest, WinHttpSendRequest, WinHttpReceiveResponse
extern WinHttpQueryHeaders, WinHttpReadData, WinHttpCloseHandle, WinHttpSetTimeouts, GetSystemTimeAsFileTime
extern BCryptOpenAlgorithmProvider, BCryptHash, BCryptCloseAlgorithmProvider

section .data
WSTR clip_static, "STATIC"
WSTR cls_name, "MistriMultiUpdater"
WSTR cls_static, "STATIC"
WSTR cls_button, "BUTTON"
WSTR title, "MistriaMulti"
WSTR txt_check, "Check for updates"
WSTR txt_update, "Update MistriMulti"
WSTR txt_save, "Save Solo"
WSTR txt_close, "Close"
WSTR txt_start, "Looking for the game..."
fmt_game_missing: dw __utf16__(`Fields of Mistria was not found.\r\n\r\nPass the game folder as the first argument, or install the game through Steam.`), 0
fmt_status: dw __utf16__(`Game folder:\r\n%s\r\n\r\nMod installed:   %s\r\nLatest version:  %s\r\nTools:           %s\r\n\r\n`), 0
WSTR msg_unknown, "Press Update MistriMulti."
WSTR msg_uptodate, "You are up to date."
WSTR msg_available, "An update is available. Press Update MistriMulti."
WSTR msg_tools, "The mod is current, but a program (launcher, helper or this manager) has a newer version. Press Update MistriMulti."
WSTR msg_newer, "The version installed here is newer than the published one. There is nothing to update."
WSTR msg_notinstalled, "Not installed yet. Press Update MistriMulti to install."
WSTR msg_offline, "Could not reach the update server (is the repository public yet?)."
WSTR msg_badlist, "The update list is not valid, or was cut off. Nothing was changed."
WSTR msg_hash, "A downloaded file failed its checksum. Nothing was changed."
WSTR msg_dlfail, "A download failed (or the file was too large). Nothing was changed."
WSTR msg_needcheck, "Check for updates first."
WSTR msg_writefail, "Could not write a file next to the game or this program. Nothing was changed."
WSTR msg_swapfail, "Could not replace a file (is the game or the launcher running?). Everything was put back as it was."
WSTR msg_nogame, "Fields of Mistria was not found, so the mod cannot be updated. Pass the game folder as the first argument."
WSTR msg_current, "Everything is already up to date."
fmt_done: dw __utf16__(`Updated to %s.\r\n\r\nFiles installed: %d (mod %d, programs %d).`), 0
fmt_done_self: dw __utf16__(`\r\n\r\nMistriMulti.exe itself was updated. Close this window and open MistriMulti.exe again to use the new version.`), 0
fmt_done_momi: dw __utf16__(`\r\n\r\nNext: close the game, press Open MOMI (it asks once where MOMI is), select MistriaMulti and click Install, then start the game.`), 0
fmt_saved: dw __utf16__(`Saved %d file(s) to:\r\n%s`), 0
WSTR msg_nosaves, "No solo saves were found to back up."
WSTR msg_nodocs, "Could not find your Documents folder."
WSTR env_local, "LOCALAPPDATA"
WSTR env_saves, "MISTRIMULTI_SAVES_DIR"
WSTR env_docs, "MISTRIMULTI_DOCS_DIR"
WSTR suffix_saves, "\FieldsOfMistria\saves"
WSTR suffix_backups, "\MistriMulti Backups"
WSTR fmt_stamp, "\%04d%02d%02d-%02d%02d%02d"
WSTR fmt_star, "%s\*"
WSTR fmt_slash, "%s\%s"
WSTR fmt_url, "%s/%s"
WSTR fmt_mods, "%s\mods\%s"
WSTR fmt_new, "%s.new"
WSTR fmt_ver_line, "%S"
WSTR ua, "MistriMultiUpdater"
WSTR verb_get, "GET"
WSTR alg_sha256, "SHA256"
WSTR def_host, "raw.githubusercontent.com"
WSTR def_prefix, "/tomrocksyou/MistriaMulti/main"
WSTR latest_path, "release/latest.txt"
WSTR txt_none, "not installed"
WSTR txt_unknown, "(press Update MistriMulti)"
WSTR suffix_maybe, "\Maybe.toml"
WSTR suffix_manifest, "\mods\mistrimulti\manifest.toml"
WSTR cand_1, ":\SteamLibrary\steamapps\common\Fields of Mistria"
WSTR cand_2, ":\Steam\steamapps\common\Fields of Mistria"
WSTR cand_3, ":\Program Files (x86)\Steam\steamapps\common\Fields of Mistria"
WSTR cand_4, ":\Program Files\Steam\steamapps\common\Fields of Mistria"
WSTR fmt_cand, "%c%s"
WSTR fmt_cat, "%s%s"
needle_version db 'version = "'
needle_version_len equ $ - needle_version
WSTR txt_unavail, "unavailable"
WSTR s_daily, "--daily"
WSTR dl_cfg, "%s\update.cfg"
WSTR dl_json, "%s\update.json"
WSTR dl_tmp, "%s\update.json.tmp"
WSTR dl_fmt, `{"v":1,"latest":"%s","checked":%u}`
dl_off db 'check=off'
dl_off_len equ $ - dl_off
dl_checked db '"checked":'
dl_checked_len equ $ - dl_checked
hexdigits db '0123456789abcdef'
align 4
guid_docs dd 0xFDD39AD0
    dw 0x238F, 0x46AF
    db 0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7
align 8
cand_table dq cand_1, cand_2, cand_3, cand_4

section .bss
sinfo resb 104
pinfo resb 24
h_inst resq 1
h_wnd resq 1
h_status resq 1
h_btn_update resq 1
h_font resq 1
argc resd 1
argv resq 1
msg resb 64
wc resb 80
game_dir resw 520
path_tmp resw 1040
status_text resw 2048
installed_ver resw 40
latest_ver resw 40
file_buf resb 8192
http_buf resb 1056768              ; HTTP_MAX + room for one more read (see http_get)
manifest_buf resb 32768
http_len resq 1
manifest_len resq 1
status_code resd 1
q_len resd 1
srv_host resq 1
srv_prefix resq 1
srv_port resd 1
srv_secure resd 1
state_msg resq 1
digest resb 32
hexout resb 72
wpath1 resw 1040
wpath2 resw 1040
wpath3 resw 1040
wurl resw 1040
fd resb 600
st resb 16
hAlg resq 1
m_hex resq 1
m_path resq 1
m_pathlen resq 1
tmp_ptr resq 1
done_msg resw 1024
copied resd 1
ft_now resq 1
http_tmo resd 1                    ; milliseconds for every WinHTTP step, 0 = the system defaults
upd_ok resd 1                      ; 1 when do_update finished installing

section .text
global start
%include "winutil.inc"
%include "world.inc"
%include "release.inc"
%include "mp.inc"
%include "momi.inc"




; Looks for Fields of Mistria; fills game_dir. rax=1 found / 0 not found
; Tries argv[1], then drive letters C..Z against the usual Steam library locations.
FN find_game
    cmp dword [argc], 2
    jb .search
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [game_dir]
    call wcopy
    lea rcx, [game_dir]
    lea rdx, [suffix_maybe]
    lea r8, [path_tmp]
    call join_wide
    lea rcx, [path_tmp]
    call file_exists
    jmp .finish
.search:
    mov r12d, 'C'
.drive:
    xor r13d, r13d
.cand:
    ; game_dir = X + candidate
    lea rcx, [game_dir]
    lea rdx, [fmt_cand]
    mov r8d, r12d
    lea rax, [cand_table]
    mov r9, [rax+r13*8]
    call wsprintfW
    lea rcx, [game_dir]
    lea rdx, [suffix_maybe]
    lea r8, [path_tmp]
    call join_wide
    lea rcx, [path_tmp]
    call file_exists
    test eax, eax
    jnz .finish
    inc r13d
    cmp r13d, 4
    jb .cand
    inc r12d
    cmp r12d, 'Z'
    jbe .drive
    xor eax, eax
.finish:
END_FN


; Reads the installed mod version into installed_ver ("not installed" when missing).
FN read_installed
    lea rcx, [txt_none]
    lea rdx, [installed_ver]
    call wcopy
    lea rcx, [game_dir]
    lea rdx, [suffix_manifest]
    lea r8, [path_tmp]
    call join_wide
    lea rcx, [path_tmp]
    mov edx, 0x80000000        ; GENERIC_READ
    mov r8d, 1                 ; FILE_SHARE_READ
    xor r9d, r9d
    mov qword [rsp+32], 3      ; OPEN_EXISTING
    mov qword [rsp+40], 0x80
    mov qword [rsp+48], 0
    call CreateFileW
    cmp rax, -1
    je .done
    mov rbx, rax
    mov rcx, rbx
    lea rdx, [file_buf]
    mov r8d, 8000
    lea r9, [rsp+64]
    mov qword [rsp+32], 0
    call ReadFile
    mov rcx, rbx
    call CloseHandle
    mov edx, [rsp+64]          ; bytes read
    lea rcx, [file_buf]
    lea r8, [needle_version]
    mov r9d, needle_version_len
    call find_bytes
    test rax, rax
    jz .done
    lea rsi, [rax+needle_version_len]
    lea rdi, [installed_ver]
    xor ecx, ecx
.v: movzx eax, byte [rsi]
    cmp al, '"'
    je .vend
    test al, al
    jz .vend
    mov [rdi+rcx*2], ax
    inc rsi
    inc ecx
    cmp ecx, 30
    jb .v
.vend:
    mov word [rdi+rcx*2], 0
.done:
END_FN

FN show_status
    lea rcx, [status_text]
    lea rdx, [fmt_status]
    lea r8, [game_dir]
    lea r9, [installed_ver]
    lea rax, [latest_ver]
    mov [rsp+32], rax
    mov rax, [tools_text]
    mov [rsp+40], rax
    call wsprintfW
    lea rcx, [status_text]
    mov rdx, [state_msg]
    lea r8, [status_text]
    call join_wide
    mov rcx, [h_status]
    lea rdx, [status_text]
    call SetWindowTextW
END_FN

; rcx = wide message to show under the versions
FN set_state
    mov [state_msg], rcx
    call show_status
END_FN

; Creates a child control. rcx=class rdx=text r8d=style r9d=x ; stack: y,w,h,id (our own convention: r12..r15 preset)
FN make_child
    ; in: rcx class, rdx text, r8 style, r9 x, r12 y, r13 w, r14 h, r15 id
    ; CreateWindowExW(ex, class, text, style, x, y, w, h, parent, menu, inst, param)
    mov r10, r8                ; style
    mov r8, rdx                ; text -> 3rd arg
    mov rdx, rcx               ; class -> 2nd arg
    xor ecx, ecx               ; ex style -> 1st arg
    mov r11, r9                ; x
    mov r9, r10                ; style -> 4th arg
    mov [rsp+32], r11          ; x
    mov [rsp+40], r12          ; y
    mov [rsp+48], r13          ; w
    mov [rsp+56], r14          ; h
    mov rax, [cur_parent]
    mov [rsp+64], rax          ; parent
    mov [rsp+72], r15          ; control id as menu
    mov rax, [h_inst]
    mov [rsp+80], rax
    mov qword [rsp+88], 0
    call CreateWindowExW
    mov rbx, rax
    mov rcx, rbx
    mov edx, 0x30              ; WM_SETFONT
    mov r8, [h_font]
    mov r9d, 1
    call SendMessageW
    mov rax, rbx
END_FN






; ---------- network ----------
; rcx host (wide), rdx path (wide). Uses srv_port / srv_secure. eax=1 ok, body in http_buf, length in http_len
FN http_get
    mov r12, rcx
    mov r13, rdx
    mov qword [http_len], 0
    xor ebx, ebx
    xor esi, esi
    xor edi, edi
    lea rcx, [ua]
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 0
    call WinHttpOpen
    test rax, rax
    jz .fail
    mov rbx, rax
    mov edx, [http_tmo]
    test edx, edx
    jz .notmo
    mov rcx, rbx
    mov r8d, edx
    mov r9d, edx
    mov [rsp+32], rdx
    call WinHttpSetTimeouts
.notmo:
    mov rcx, rbx
    mov rdx, r12
    mov r8d, [srv_port]
    xor r9d, r9d
    call WinHttpConnect
    test rax, rax
    jz .fail
    mov rsi, rax
    mov rcx, rsi
    lea rdx, [verb_get]
    mov r8, r13
    xor r9d, r9d
    mov qword [rsp+32], 0
    mov qword [rsp+40], 0
    xor eax, eax
    cmp dword [srv_secure], 0
    je .ns
    mov eax, 0x800000       ; WINHTTP_FLAG_SECURE
.ns:
    mov [rsp+48], rax
    call WinHttpOpenRequest
    test rax, rax
    jz .fail
    mov rdi, rax
    mov rcx, rdi
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    mov qword [rsp+32], 0
    mov qword [rsp+40], 0
    mov qword [rsp+48], 0
    call WinHttpSendRequest
    test eax, eax
    jz .fail
    mov rcx, rdi
    xor edx, edx
    call WinHttpReceiveResponse
    test eax, eax
    jz .fail
    mov dword [q_len], 4
    mov dword [status_code], 0
    mov rcx, rdi
    mov edx, 0x20000013     ; STATUS_CODE | FLAG_NUMBER
    xor r8d, r8d
    lea r9, [status_code]
    lea rax, [q_len]
    mov [rsp+32], rax
    mov qword [rsp+40], 0
    call WinHttpQueryHeaders
    cmp dword [status_code], 200
    jne .fail
    xor r14d, r14d
.read:
    mov eax, HTTP_MAX + 8191
    sub eax, r14d
    jbe .fail
    cmp eax, 8192
    jbe .sz
    mov eax, 8192
.sz:
    mov rcx, rdi
    lea rdx, [http_buf]
    add rdx, r14
    mov r8d, eax
    lea r9, [q_len]
    call WinHttpReadData
    test eax, eax
    jz .fail
    mov eax, [q_len]
    test eax, eax
    jz .ok
    add r14d, eax
    cmp r14d, HTTP_MAX
    ja .fail                        ; larger than anything we publish: refuse
    jmp .read
.ok:
    mov [http_len], r14
    lea rax, [http_buf]
    mov byte [rax+r14], 0
    mov r15d, 1
    jmp .close
.fail:
    xor r15d, r15d
.close:
    test rdi, rdi
    jz .c1
    mov rcx, rdi
    call WinHttpCloseHandle
.c1:
    test rsi, rsi
    jz .c2
    mov rcx, rsi
    call WinHttpCloseHandle
.c2:
    test rbx, rbx
    jz .c3
    mov rcx, rbx
    call WinHttpCloseHandle
.c3:
    mov eax, r15d
END_FN

; rcx data, rdx length -> lowercase hex of SHA-256 in hexout (64 chars + 0). eax=1 ok
FN sha256_hex
    mov r12, rcx
    mov r13, rdx
    lea rcx, [hAlg]
    lea rdx, [alg_sha256]
    xor r8d, r8d
    xor r9d, r9d
    call BCryptOpenAlgorithmProvider
    test eax, eax
    jnz .fail
    mov rcx, [hAlg]
    xor edx, edx
    xor r8d, r8d
    mov r9, r12
    mov [rsp+32], r13
    lea rax, [digest]
    mov [rsp+40], rax
    mov qword [rsp+48], 32
    call BCryptHash
    mov ebx, eax
    mov rcx, [hAlg]
    xor edx, edx
    call BCryptCloseAlgorithmProvider
    test ebx, ebx
    jnz .fail
    lea rsi, [digest]
    lea rdi, [hexout]
    lea r8, [hexdigits]
    xor ecx, ecx
.h: movzx eax, byte [rsi+rcx]
    mov edx, eax
    shr edx, 4
    and eax, 15
    mov dl, [r8+rdx]
    mov [rdi], dl
    mov al, [r8+rax]
    mov [rdi+1], al
    add rdi, 2
    inc ecx
    cmp ecx, 32
    jb .h
    mov byte [rdi], 0
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

; ---------- update list ----------
FN cleanup_staged
    xor r12d, r12d
.l: cmp r12d, [ent_n]
    jae .d
    mov ecx, r12d
    call entry_load
    call entry_paths
    lea rcx, [wpath2]
    call DeleteFileW
    inc r12d
    jmp .l
.d:
END_FN

; Puts every file back that this update moved: the old file returns over the new one, files that were new are removed.
FN rollback_all
    xor r12d, r12d
.l: cmp r12d, [ent_n]
    jae .d
    mov ecx, r12d
    call entry_load
    call entry_paths
    lea rax, [ent_flag]
    movzx r13d, byte [rax+r12]
    test r13d, 6
    jz .n
    test r13d, 2
    jz .remove
    lea rcx, [wold]
    lea rdx, [wpath1]
    mov r8d, 1                      ; MOVEFILE_REPLACE_EXISTING
    call MoveFileExW
    jmp .n
.remove:
    lea rcx, [wpath1]
    call DeleteFileW
.n: inc r12d
    jmp .l
.d:
END_FN

; The loaded entry: move the old file aside (a running program can be renamed, not overwritten), move the staged
; file into place. Records what happened in ent_flag so rollback_all can undo it. eax 1 ok / 0 failed
FN swap_in
    lea rcx, [wold]
    call DeleteFileW                ; a stale .old (fails, harmlessly, when its program still runs)
    lea rcx, [wpath1]
    call file_exists
    test eax, eax
    jz .place
    lea rcx, [wpath1]
    lea rdx, [wold]
    xor r8d, r8d
    call MoveFileExW
    test eax, eax
    jz .fail
    mov ecx, [cur_i]
    lea rax, [ent_flag]
    or byte [rax+rcx], 2
.place:
    lea rcx, [wpath2]
    lea rdx, [wpath1]
    xor r8d, r8d
    call MoveFileExW
    test eax, eax
    jz .fail
    mov ecx, [cur_i]
    lea rax, [ent_flag]
    or byte [rax+rcx], 4
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN do_check
    mov qword [manifest_len], 0
    mov dword [ent_n], 0
    call list_url
    mov rcx, [ent_host]
    lea rdx, [wurl]
    call http_get
    test eax, eax
    jz .offline
    mov rcx, [http_len]
    cmp rcx, 30000
    ja .bad
    mov rdx, rcx
    lea rsi, [http_buf]
    lea rdi, [manifest_buf]
    rep movsb
    mov byte [rdi], 0
    mov [manifest_len], rdx
    call manifest_validate
    test eax, eax
    jz .bad
    call count_tools
    call version_state
    cmp eax, 0
    je .notinst
    cmp eax, 1
    je .available
    cmp eax, 3
    je .newer
    lea rcx, [msg_uptodate]
    cmp dword [tools_stale], 0
    je .show
    lea rcx, [msg_tools]
    jmp .show
.available:
    lea rcx, [msg_available]
    jmp .show
.newer:
    lea rcx, [msg_newer]
    jmp .show
.notinst:
    lea rcx, [msg_notinstalled]
    jmp .show
.bad:
    mov qword [manifest_len], 0
    mov dword [ent_n], 0
    lea rcx, [txt_unavail]
    lea rdx, [latest_ver]
    call wcopy
    lea rax, [txt_tools_unknown]
    mov [tools_text], rax
    lea rcx, [msg_badlist]
    jmp .show
.offline:
    lea rcx, [txt_unavail]
    lea rdx, [latest_ver]
    call wcopy
    lea rax, [txt_tools_unknown]
    mov [tools_text], rax
    lea rcx, [msg_offline]
.show:
    call set_state
END_FN

; Verifies the whole list, downloads every file that differs from what is installed, verifies each hash, stages
; it as <name>.new, and only then replaces the files (all or nothing; the old files are kept as <name>.old until
; everything is in place). The running MistriMulti.exe is renamed to .old like any other program.
FN do_update
    cmp qword [manifest_len], 0
    jne .go
    lea rcx, [msg_needcheck]
    call set_state
    jmp .d
.go:
    call manifest_validate
    test eax, eax
    jz .badlist
    call version_state
    cmp eax, 3
    je .newer
    lea rdi, [ent_flag]
    xor eax, eax
    mov ecx, MAX_ENTRIES
    rep stosb
    mov dword [n_mod], 0
    mov dword [n_bin], 0
    mov dword [self_upd], 0
    xor r12d, r12d                  ; entry number
    xor r15d, r15d                  ; files staged
.p1:
    cmp r12d, [ent_n]
    jae .staged
    mov ecx, r12d
    call entry_load
    call entry_paths
    cmp dword [cur_kind], 2
    je .dest_ok
    cmp dword [have_game], 0
    je .nogame
.dest_ok:
    call installed_matches
    test eax, eax
    jnz .p1n
    mov rcx, [ent_host]
    lea rdx, [wurl]
    call http_get
    test eax, eax
    jz .dlfail
    lea rcx, [http_buf]
    mov rdx, [http_len]
    call sha256_hex
    test eax, eax
    jz .dlfail
    lea rsi, [hexout]
    mov rdi, [m_hex]
    mov ecx, 64
    repe cmpsb
    jne .hashfail
    lea rcx, [wpath1]
    call ensure_dirs
    lea rcx, [wpath2]
    lea rdx, [http_buf]
    mov r8, [http_len]
    call write_file
    test eax, eax
    jz .writefail
    lea rax, [ent_flag]
    mov byte [rax+r12], 1
    inc r15d
.p1n:
    inc r12d
    jmp .p1
.staged:
    test r15d, r15d
    jnz .swap
    lea rcx, [msg_current]
    call set_state
    jmp .d
.swap:
    xor r13d, r13d                  ; sweep 0: everything except manifest.toml; sweep 1: manifest.toml last
.sweep:
    xor r12d, r12d
.s1:
    cmp r12d, [ent_n]
    jae .sweepdone
    lea rax, [ent_flag]
    test byte [rax+r12], 1
    jz .s1n
    mov ecx, r12d
    call entry_load
    xor eax, eax
    cmp dword [cur_kind], 3
    sete al
    cmp eax, r13d
    jne .s1n
    call entry_paths
    call swap_in
    test eax, eax
    jz .swapfail
.s1n:
    inc r12d
    jmp .s1
.sweepdone:
    inc r13d
    cmp r13d, 2
    jb .sweep
    ; all in place: count, forget the backups
    xor r12d, r12d
.fin:
    cmp r12d, [ent_n]
    jae .finished
    lea rax, [ent_flag]
    movzx r13d, byte [rax+r12]
    test r13d, 4
    jz .finn
    mov ecx, r12d
    call entry_load
    call entry_paths
    cmp dword [cur_kind], 2
    je .isbin
    inc dword [n_mod]
    jmp .bk
.isbin:
    inc dword [n_bin]
    lea rcx, [wpath1]
    lea rdx, [self_path]
    call lstrcmpiW
    test eax, eax
    jnz .bk
    mov dword [self_upd], 1
.bk:
    test r13d, 2
    jz .finn
    lea rcx, [wold]
    call DeleteFileW                ; refused for the program that is running: removed at the next start
.finn:
    inc r12d
    jmp .fin
.finished:
    mov dword [upd_ok], 1
    call read_installed
    mov eax, [n_mod]
    add eax, [n_bin]
    lea rcx, [done_msg]
    lea rdx, [fmt_done]
    lea r8, [latest_ver]
    mov r9d, eax
    mov eax, [n_mod]
    mov [rsp+32], rax
    mov eax, [n_bin]
    mov [rsp+40], rax
    call wsprintfW
    cmp dword [self_upd], 0
    je .noself
    lea rcx, [done_msg]
    lea rdx, [fmt_done_self]
    lea r8, [done_msg]
    call join_wide
.noself:
    cmp dword [n_mod], 0
    je .nomomi
    lea rcx, [done_msg]
    lea rdx, [fmt_done_momi]
    lea r8, [done_msg]
    call join_wide
.nomomi:
    call count_tools
    lea rcx, [done_msg]
    call set_state
    jmp .d
.newer:
    lea rcx, [msg_newer]
    call set_state
    jmp .d
.badlist:
    lea rcx, [msg_badlist]
    call set_state
    jmp .d
.nogame:
    call cleanup_staged
    lea rcx, [msg_nogame]
    call set_state
    jmp .d
.dlfail:
    call cleanup_staged
    lea rcx, [msg_dlfail]
    call set_state
    jmp .d
.hashfail:
    call cleanup_staged
    lea rcx, [msg_hash]
    call set_state
    jmp .d
.writefail:
    call cleanup_staged
    lea rcx, [msg_writefail]
    call set_state
    jmp .d
.swapfail:
    call rollback_all
    call cleanup_staged
    lea rcx, [msg_swapfail]
    call set_state
.d:
END_FN

; The one button: check, update when there is something to update, then the MOMI step. Every outcome is a plain sentence.
FN do_oneclick
    mov dword [upd_ok], 0
    call do_check
    cmp qword [manifest_len], 0
    je .d                           ; offline or invalid list: do_check said so
    call version_state
    cmp eax, 3
    je .d                           ; the installed version is newer: nothing to do
    cmp eax, 2
    jne .go
    cmp dword [tools_stale], 0
    je .d                           ; up to date
.go:
    call do_update
    cmp dword [upd_ok], 0
    je .d
    cmp dword [n_mod], 0
    je .d                           ; only programs changed: MOMI has nothing new to install
    call momi_after_update
.d:
END_FN

; --daily <mod data folder> [<host> <port> <https 0/1> <path prefix>]   (started hidden by the launcher at every game start)
; At most one check a day, silent, short timeouts: reads the latest release list, writes <mod data folder>\update.json
; {"v":1,"latest":"x.y.z","checked":<unix seconds>} for the mod's badge. A line "check=off" in <mod data folder>\update.cfg turns it
; off. Any failure ends quietly without touching anything. Nothing is installed.
FN daily_check
    mov rax, [argv]
    mov r12, [rax+16]
    lea rcx, [wpath1]
    lea rdx, [dl_cfg]
    mov r8, r12
    call wsprintfW
    lea rcx, [wpath1]
    lea rdx, [file_buf]
    mov r8d, 2000
    call read_file
    cmp rax, 9
    jl .nocfg
    mov rdx, rax
    lea rcx, [file_buf]
    lea r8, [dl_off]
    mov r9d, dl_off_len
    call find_bytes
    test rax, rax
    jnz .done
.nocfg:
    lea rcx, [ft_now]
    call GetSystemTimeAsFileTime
    mov rax, [ft_now]
    xor edx, edx
    mov rcx, 10000000
    div rcx
    mov rcx, 11644473600
    sub rax, rcx
    mov r13, rax                    ; now, unix seconds
    lea rcx, [wpath1]
    lea rdx, [dl_json]
    mov r8, r12
    call wsprintfW
    lea rcx, [wpath1]
    lea rdx, [file_buf]
    mov r8d, 2000
    call read_file
    cmp rax, 12
    jl .go
    mov rdx, rax
    lea rcx, [file_buf]
    lea r8, [dl_checked]
    mov r9d, dl_checked_len
    call find_bytes
    test rax, rax
    jz .go
    lea rcx, [rax+dl_checked_len]
    xor eax, eax
    xor r8d, r8d
.dg:
    movzx edx, byte [rcx]
    sub edx, '0'
    cmp edx, 9
    ja .dge
    imul rax, rax, 10
    add rax, rdx
    inc rcx
    inc r8d
    cmp r8d, 11
    jb .dg
    jmp .go                         ; absurd number: check again
.dge:
    cmp r13, rax
    jb .go                          ; "checked" lies in the future: check again
    mov rdx, r13
    sub rdx, rax
    cmp rdx, 86400
    jb .done                        ; checked within the last day
.go:
    mov dword [http_tmo], 5000
    mov qword [manifest_len], 0
    mov dword [ent_n], 0
    call list_url
    mov rcx, [ent_host]
    lea rdx, [wurl]
    call http_get
    test eax, eax
    jz .done
    mov rcx, [http_len]
    cmp rcx, 30000
    ja .done
    mov rdx, rcx
    lea rsi, [http_buf]
    lea rdi, [manifest_buf]
    rep movsb
    mov byte [rdi], 0
    mov [manifest_len], rdx
    call manifest_validate
    test eax, eax
    jz .done
    lea rcx, [done_msg]
    lea rdx, [dl_fmt]
    lea r8, [latest_ver]
    mov r9d, r13d
    call wsprintfW
    mov r14d, eax
    lea rcx, [http_buf]
    lea rdx, [done_msg]
    mov r8d, 400
    call wide_to_ascii
    lea rcx, [wpath2]
    lea rdx, [dl_tmp]
    mov r8, r12
    call wsprintfW
    lea rcx, [wpath2]
    call ensure_dirs
    lea rcx, [wpath2]
    lea rdx, [http_buf]
    mov r8d, r14d
    call write_file
    test eax, eax
    jz .done
    lea rcx, [wpath1]
    lea rdx, [dl_json]
    mov r8, r12
    call wsprintfW
    lea rcx, [wpath2]
    lea rdx, [wpath1]
    mov r8d, 1                      ; MOVEFILE_REPLACE_EXISTING
    call MoveFileExW
.done:
END_FN

FN do_save
    lea rcx, [env_saves]
    lea rdx, [wpath1]
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jnz .have_src
    lea rcx, [env_local]
    lea rdx, [wpath3]
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jz .nosaves
    lea rcx, [wpath1]
    lea rdx, [fmt_cat]
    lea r8, [wpath3]
    lea r9, [suffix_saves]
    call wsprintfW
.have_src:
    lea rcx, [env_docs]
    lea rdx, [wpath2]
    mov r8d, 520
    call GetEnvironmentVariableW
    test eax, eax
    jnz .have_docs
    lea rcx, [guid_docs]
    xor edx, edx
    xor r8d, r8d
    lea r9, [tmp_ptr]
    call SHGetKnownFolderPath
    test eax, eax
    jnz .nodocs
    mov rcx, [tmp_ptr]
    lea rdx, [wpath2]
    call wcopy
    mov rcx, [tmp_ptr]
    call CoTaskMemFree
.have_docs:
    lea rcx, [wpath3]
    lea rdx, [fmt_cat]
    lea r8, [wpath2]
    lea r9, [suffix_backups]
    call wsprintfW
    lea rcx, [wpath3]
    xor edx, edx
    call CreateDirectoryW
    lea rcx, [st]
    call GetLocalTime
    lea rcx, [wpath2]
    lea rdx, [fmt_stamp]
    movzx r8d, word [st]
    movzx r9d, word [st+2]
    movzx eax, word [st+6]
    mov [rsp+32], rax
    movzx eax, word [st+8]
    mov [rsp+40], rax
    movzx eax, word [st+10]
    mov [rsp+48], rax
    movzx eax, word [st+12]
    mov [rsp+56], rax
    call wsprintfW
    lea rcx, [wurl]
    lea rdx, [fmt_cat]
    lea r8, [wpath3]
    lea r9, [wpath2]
    call wsprintfW
    lea rcx, [wurl]
    xor edx, edx
    call CreateDirectoryW
    mov dword [copied], 0
    lea rcx, [wpath2]
    lea rdx, [fmt_star]
    lea r8, [wpath1]
    call wsprintfW
    lea rcx, [wpath2]
    lea rdx, [fd]
    call FindFirstFileW
    cmp rax, -1
    je .report
    mov rbx, rax
.each:
    test dword [fd], 0x10          ; skip folders
    jnz .next
    lea rcx, [wpath3]
    lea rdx, [fmt_slash]
    lea r8, [wpath1]
    lea r9, [fd+44]
    call wsprintfW
    lea rcx, [wpath2]
    lea rdx, [fmt_slash]
    lea r8, [wurl]
    lea r9, [fd+44]
    call wsprintfW
    lea rcx, [wpath3]
    lea rdx, [wpath2]
    xor r8d, r8d
    call CopyFileW
    test eax, eax
    jz .next
    inc dword [copied]
.next:
    mov rcx, rbx
    lea rdx, [fd]
    call FindNextFileW
    test eax, eax
    jnz .each
    mov rcx, rbx
    call FindClose
.report:
    cmp dword [copied], 0
    je .nosaves
    lea rcx, [done_msg]
    lea rdx, [fmt_saved]
    mov r8d, [copied]
    lea r9, [wurl]
    call wsprintfW
    lea rcx, [done_msg]
    call set_state
    jmp .d
.nosaves:
    lea rcx, [msg_nosaves]
    call set_state
    jmp .d
.nodocs:
    lea rcx, [msg_nodocs]
    call set_state
.d:
END_FN


FN wndproc
    ; rcx=hwnd rdx=msg r8=wParam r9=lParam
    cmp edx, 2                 ; WM_DESTROY
    je .destroy
    cmp edx, 0x111             ; WM_COMMAND
    je .command
    call DefWindowProcW
    jmp .done
.command:
    movzx eax, r8w
    cmp eax, 1
    je .do_check
    cmp eax, 2
    je .do_oneclick
    cmp eax, 3
    je .do_save
    cmp eax, 4
    je .close
    cmp eax, 5
    je .do_host
    cmp eax, 6
    je .do_join
    cmp eax, 7
    je .do_steam
    cmp eax, 8
    je .do_momi
    xor eax, eax
    jmp .done
.do_momi:
    call momi_open
    xor eax, eax
    jmp .done
.do_host:
    call mp_do_host
    xor eax, eax
    jmp .done
.do_join:
    call mp_open_join
    xor eax, eax
    jmp .done
.do_steam:
    call mp_do_steam
    xor eax, eax
    jmp .done
.do_check:
    call do_check
    xor eax, eax
    jmp .done
.do_oneclick:
    call do_oneclick
    xor eax, eax
    jmp .done
.do_save:
    call do_save
    xor eax, eax
    jmp .done
.close:
    mov rcx, [h_wnd]
    mov edx, 0x10              ; WM_CLOSE
    xor r8d, r8d
    xor r9d, r9d
    call DefWindowProcW
    xor eax, eax
    jmp .done
.destroy:
    xor ecx, ecx
    call PostQuitMessage
    xor eax, eax
.done:
END_FN

start:
    sub rsp, 8
    and rsp, -16
    sub rsp, 128
    ; command line
    call GetCommandLineW
    mov rcx, rax
    lea rdx, [argc]
    call CommandLineToArgvW
    mov [argv], rax
    xor ecx, ecx
    call GetModuleHandleW
    mov [h_inst], rax
    mov ecx, 17                ; DEFAULT_GUI_FONT
    call GetStockObject
    mov [h_font], rax
    ; defaults (arguments 2-5 override the server: host port secure(0/1) path-prefix, used for testing)
    lea rcx, [txt_unknown]
    lea rdx, [latest_ver]
    call wcopy
    lea rax, [def_host]
    mov [srv_host], rax
    lea rax, [def_prefix]
    mov [srv_prefix], rax
    mov dword [srv_port], 443
    mov dword [srv_secure], 1
    lea rax, [msg_unknown]
    mov [state_msg], rax
    cmp dword [argc], 6
    jb .args_done
    mov rax, [argv]
    mov rcx, [rax+16]
    mov [srv_host], rcx
    mov rcx, [rax+24]
    call w2i
    mov [srv_port], eax
    mov rax, [argv]
    mov rcx, [rax+32]
    call w2i
    mov [srv_secure], eax
    mov rax, [argv]
    mov rcx, [rax+40]
    mov [srv_prefix], rcx
    mov dword [srv_override], 1
.args_done:
    ; --daily <mod data folder> [<host> <port> <https 0/1> <path prefix>]: the once-a-day update check (no window), see daily_check
    cmp dword [argc], 3
    jb .nodaily
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_daily]
    call wequal
    test eax, eax
    jz .nodaily
    mov dword [srv_override], 0
    lea rax, [def_host]
    mov [srv_host], rax
    lea rax, [def_prefix]
    mov [srv_prefix], rax
    mov dword [srv_port], 443
    mov dword [srv_secure], 1
    cmp dword [argc], 7
    jb .dl_run
    mov rax, [argv]
    mov rcx, [rax+24]
    mov [srv_host], rcx
    mov rcx, [rax+32]
    call w2i
    mov [srv_port], eax
    mov rax, [argv]
    mov rcx, [rax+40]
    call w2i
    mov [srv_secure], eax
    mov rax, [argv]
    mov rcx, [rax+48]
    mov [srv_prefix], rcx
    mov dword [srv_override], 1
.dl_run:
    call daily_check
    xor ecx, ecx
    call ExitProcess
.nodaily:
    ; where this program lives: tools are installed next to it; leftovers of an earlier update are removed
    xor ecx, ecx
    lea rdx, [self_path]
    mov r8d, 520
    call GetModuleFileNameW
    lea rcx, [self_path]
    lea rdx, [app_dir]
    call wcopy
    lea rcx, [app_dir]
    call cut_last_component
    call startup_cleanup
    lea rax, [txt_tools_unknown]
    mov [tools_text], rax
    ; window class
    lea rdi, [wc]
    xor eax, eax
    mov ecx, 80
    rep stosb
    mov dword [wc], 80
    mov dword [wc+4], 3
    lea rax, [wndproc]
    mov [wc+8], rax
    mov rax, [h_inst]
    mov [wc+24], rax
    xor ecx, ecx
    mov edx, 32512             ; IDC_ARROW
    call LoadCursorW
    mov [wc+40], rax
    mov qword [wc+48], 6       ; COLOR_WINDOW + 1
    lea rax, [cls_name]
    mov [wc+64], rax
    lea rcx, [wc]
    call RegisterClassExW
    lea rax, [join_proc]               ; second window class: the Join window
    mov [wc+8], rax
    lea rax, [mp_join_class]
    mov [wc+64], rax
    lea rcx, [wc]
    call RegisterClassExW
    lea rax, [wndproc]
    mov [wc+8], rax
    lea rax, [cls_name]
    mov [wc+64], rax
    ; main window
    xor ecx, ecx
    lea rdx, [cls_name]
    lea r8, [title]
    mov r9d, 0x10CA0000        ; WS_VISIBLE | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
    mov dword [rsp+32], 0x80000000
    mov dword [rsp+40], 0x80000000
    mov qword [rsp+48], 520
    mov qword [rsp+56], 395
    mov qword [rsp+64], 0
    mov qword [rsp+72], 0
    mov rax, [h_inst]
    mov [rsp+80], rax
    mov qword [rsp+88], 0
    call CreateWindowExW
    mov [h_wnd], rax
    mov [cur_parent], rax
    ; status text
    lea rcx, [cls_static]
    lea rdx, [txt_start]
    mov r8d, 0x50000000        ; WS_CHILD | WS_VISIBLE
    mov r9d, 16
    mov r12d, 12
    mov r13d, 480
    mov r14d, 180
    mov r15d, 10
    call make_child
    mov [h_status], rax
    ; buttons
    lea rcx, [cls_button]
    lea rdx, [txt_update]
    mov r8d, 0x50010000        ; WS_CHILD | WS_VISIBLE | WS_TABSTOP
    mov r9d, 16
    mov r12d, 204
    mov r13d, 236
    mov r14d, 28
    mov r15d, 2
    call make_child
    mov [h_btn_update], rax
    lea rcx, [cls_button]
    lea rdx, [txt_save]
    mov r8d, 0x50010000
    mov r9d, 260
    mov r12d, 204
    mov r13d, 100
    mov r14d, 28
    mov r15d, 3
    call make_child
    lea rcx, [cls_button]
    lea rdx, [txt_close]
    mov r8d, 0x50010000
    mov r9d, 368
    mov r12d, 204
    mov r13d, 112
    mov r14d, 28
    mov r15d, 4
    call make_child
    lea rcx, [cls_button]
    lea rdx, [mp_t_hostbtn]
    mov r8d, 0x50010000
    mov r9d, 16
    mov r12d, 244
    mov r13d, 150
    mov r14d, 30
    mov r15d, 5
    call make_child
    lea rcx, [cls_button]
    lea rdx, [mp_t_joinbtn]
    mov r8d, 0x50010000
    mov r9d, 176
    mov r12d, 244
    mov r13d, 150
    mov r14d, 30
    mov r15d, 6
    call make_child
    lea rcx, [cls_button]
    lea rdx, [mp_t_steambtn]
    mov r8d, 0x50010000
    mov r9d, 336
    mov r12d, 244
    mov r13d, 144
    mov r14d, 30
    mov r15d, 7
    call make_child
    lea rcx, [cls_button]
    lea rdx, [mo_t_button]
    mov r8d, 0x50010000
    mov r9d, 16
    mov r12d, 284
    mov r13d, 150
    mov r14d, 30
    mov r15d, 8
    call make_child
    ; test hook:  --fetch <ip> <destination folder> <result file> [<bridge folder> <slot>]   (downloads the host's world, writes the result code)
    cmp dword [argc], 5
    jb .nofetch
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_fetch]
    call wequal
    test eax, eax
    jz .nofetch
    mov rax, [argv]
    mov rdx, [rax+16]
    lea rcx, [mp_ascii]
    mov r8d, 20
    call wide_to_ascii
    lea rcx, [mp_ascii]
    call v_ipv4
    test eax, eax
    jz .fetch_bad
    lea rcx, [mp_ascii]
    call inet_addr
    mov ecx, eax
    mov rax, [argv]
    mov rdx, [rax+24]
    mov dword [wf_connect_ms], 1500
    mov r12d, ecx
    mov r13, rdx
    mov qword [wf_keypath], 0
    cmp dword [argc], 7
    jb .fetch_nosession
    mov rax, [argv]                    ; optional: <bridge folder> <slot 1-7>, the join session to prove
    mov rcx, [rax+40]
    mov rax, [rax+48]
    movzx edx, word [rax]
    sub edx, '0'
    call world_use_session
.fetch_nosession:
    mov ecx, r12d
    mov rdx, r13
    call world_fetch
    add al, '0'
    mov [mp_ascii+32], al
    jmp .fetch_write
.fetch_bad:
    mov byte [mp_ascii+32], '9'
.fetch_write:
    mov rax, [argv]
    mov rcx, [rax+32]
    lea rdx, [mp_ascii+32]
    mov r8d, 1
    call write_file
    xor ecx, ecx
    call ExitProcess
.nofetch:
    ; test hook:  --urls <version> <file>   writes the host and URL path used for the list, a mod file and a tool
    cmp dword [argc], 4
    jb .nourls
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_urls]
    call wequal
    test eax, eax
    jz .nourls
    call urls_dump
    xor ecx, ecx
    call ExitProcess
.nourls:
    ; test hook:  --scan <file>
    cmp dword [argc], 3
    jb .noscan
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_scan]
    call wequal
    test eax, eax
    jz .noscan
    call mp_scan
    mov rax, [argv]
    mov rcx, [rax+16]
    call mp_dump_scan
    xor ecx, ecx
    call ExitProcess
.noscan:
    ; hook for the launcher's in-game menu:  --addrs <file>
    cmp dword [argc], 3
    jb .noaddrs
    mov rax, [argv]
    mov rcx, [rax+8]
    lea rdx, [s_addrs]
    call wequal
    test eax, eax
    jz .noaddrs
    mov rax, [argv]
    mov rcx, [rax+16]
    call mp_dump_addrs
    xor ecx, ecx
    call ExitProcess
.noaddrs:
    ; game + installed version
    call find_game
    mov [have_game], eax
    test eax, eax
    jz .no_game
    call read_installed
    call show_status
    jmp .loop_init
.no_game:
    mov word [game_dir], 0
    lea rcx, [txt_none]
    lea rdx, [installed_ver]
    call wcopy
    mov rcx, [h_status]
    lea rdx, [fmt_game_missing]
    call SetWindowTextW
.loop_init:
    ; Hidden test mode: argument 6 = steps (c=check u=update s=save), argument 7 = file to write the final status to.
    cmp dword [argc], 8
    jb .interactive
    mov rax, [argv]
    mov rsi, [rax+48]
.step:
    movzx eax, word [rsi]
    test ax, ax
    jz .steps_done
    cmp ax, 'c'
    je .st_c
    cmp ax, 'u'
    je .st_u
    cmp ax, 's'
    je .st_s
    cmp ax, 'm'
    je .st_m
    cmp ax, 'a'
    je .st_a
    jmp .st_next
.st_c:
    call do_check
    jmp .st_next
.st_u:
    call do_update
    jmp .st_next
.st_a:
    mov dword [momi_quiet], 1
    call do_oneclick
    jmp .st_next
.st_s:
    call do_save
    jmp .st_next
.st_m:
    mov dword [momi_quiet], 1
    call momi_open
.st_next:
    add rsi, 2
    jmp .step
.steps_done:
    lea rcx, [status_text]
    call lstrlenW
    lea rdx, [status_text]
    lea r8d, [rax*2]
    mov rax, [argv]
    mov rcx, [rax+56]
    call write_file
    xor ecx, ecx
    call ExitProcess
.interactive:
    mov rcx, [h_wnd]
    mov edx, 5
    call ShowWindow
    ; MISTRIMULTI_OPEN_JOIN=1 opens the Join window straight away (used for screenshots)
    lea rcx, [mp_e_openjoin]
    lea rdx, [wpath1]
    mov r8d, 4
    call GetEnvironmentVariableW
    test eax, eax
    jz .pump
    call mp_open_join
.pump:
    lea rcx, [msg]
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call GetMessageW
    test eax, eax
    jle .quit
    lea rcx, [msg]
    call TranslateMessage
    lea rcx, [msg]
    call DispatchMessageW
    jmp .pump
.quit:
    mov ecx, [msg+16]
    call ExitProcess
