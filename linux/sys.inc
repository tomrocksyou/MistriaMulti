; Linux x86-64 runtime shared by mistrimulti-launcher and mistrimulti-manager (NASM, raw syscalls, no libc).
; Inside the program the Windows x64 register convention of abi.inc is kept (arguments rcx, rdx, r8, r9, then the stack;
; result in rax), so the logic reads like the Windows launcher. The sys_* wrappers return the raw kernel result:
; a negative number (-errno) on failure. Every FN routine preserves rbx, rsi, rdi, rbp and r12-r15.
; Rule from scripts/lint-asm.py: never mix a data label with a register in one address; load it with LEA first.

%macro SYSCALL4 2
%1:
    push rdi
    push rsi
    mov rdi, rcx
    mov rsi, rdx
    mov rdx, r8
    mov r10, r9
    mov eax, %2
    syscall
    pop rsi
    pop rdi
    ret
%endmacro
; Five and six argument system calls take arguments 5 and 6 where the Windows convention puts them: [rsp+32], [rsp+40] at the call site.
%macro SYSCALL6 2
%1:
    push rdi
    push rsi
    mov rdi, rcx
    mov rsi, rdx
    mov rdx, r8
    mov r10, r9
    mov r8, [rsp+56]
    mov r9, [rsp+64]
    mov eax, %2
    syscall
    pop rsi
    pop rdi
    ret
%endmacro

section .text
SYSCALL4 sys_read, 0
SYSCALL4 sys_write, 1
SYSCALL4 sys_open, 2
SYSCALL4 sys_close, 3
SYSCALL4 sys_stat, 4
SYSCALL4 sys_poll, 7
SYSCALL6 sys_mmap, 9
SYSCALL4 sys_munmap, 11
SYSCALL4 sys_rt_sigaction, 13
SYSCALL4 sys_ioctl, 16
SYSCALL4 sys_access, 21
SYSCALL4 sys_dup2, 33
SYSCALL4 sys_nanosleep, 35
SYSCALL4 sys_getpid, 39
SYSCALL4 sys_socket, 41
SYSCALL4 sys_connect, 42
SYSCALL6 sys_sendto, 44
SYSCALL6 sys_recvfrom, 45
SYSCALL4 sys_shutdown, 48
SYSCALL4 sys_bind, 49
SYSCALL4 sys_listen, 50
SYSCALL6 sys_setsockopt, 54
SYSCALL6 sys_getsockopt, 55
SYSCALL4 sys_fork, 57
SYSCALL4 sys_execve, 59
SYSCALL4 sys_exit, 231
SYSCALL4 sys_wait4, 61
SYSCALL4 sys_kill, 62
SYSCALL4 sys_uname, 63
SYSCALL4 sys_getcwd, 79
SYSCALL4 sys_rename, 82
SYSCALL4 sys_mkdir, 83
SYSCALL4 sys_rmdir, 84
SYSCALL4 sys_unlink, 87
SYSCALL4 sys_readlink, 89
SYSCALL4 sys_getppid, 110
SYSCALL4 sys_prctl, 157
SYSCALL4 sys_getdents64, 217
SYSCALL4 sys_clock_gettime, 228
SYSCALL4 sys_accept4, 288
SYSCALL4 sys_pipe2, 293
SYSCALL4 sys_getrandom, 318

%define O_RDONLY 0
%define O_WRONLY 1
%define O_CLOEXEC 0x80000
%define O_NONBLOCK 0x800
%define O_DIRECTORY 0x10000
%define O_WRITE_NEW 0x80241            ; O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC
%define POLLIN 1
%define POLLOUT 4
%define POLLERR 8
%define POLLHUP 0x10
%define POLLNVAL 0x20
%define MSG_NOSIGNAL 0x4000
%define EINTR -4
%define EINPROGRESS -115

section .bss
argc_v resq 1
argv_v resq 1
envp_v resq 1
pb_base resq 1
pb_cur resq 1
pb_limit resq 1
pb_over resd 1
st_buf resb 144
ts_buf resb 16
pipe_fds resd 2
status_v resd 2
dir_fd resq 1
dir_pos resq 1
dir_end resq 1
dir_type resd 1
dir_buf resb 8192
copy_buf resb 65536
tmp_path resb 1100
guid resb 16
in_pos resd 1
in_len resd 1
inbuf resb 256

section .text
; Program entry: saves argc/argv/envp and calls program_main, which never returns (it ends with sys_exit).
global _start
_start:
    mov rax, [rsp]
    mov [argc_v], rax
    lea rcx, [rsp+8]
    mov [argv_v], rcx
    lea rcx, [rcx+rax*8+8]
    mov [envp_v], rcx
    and rsp, -16
    sub rsp, 8
    jmp program_main

; ---------------- strings and the string builder ----------------
FN str_len                      ; rcx -> rax
    xor eax, eax
.l: cmp byte [rcx+rax], 0
    je .d
    inc rax
    jmp .l
.d:
END_FN

FN str_copy                     ; rcx dst, rdx src -> rax = address of dst's terminator (caller guarantees room)
    mov rdi, rcx
    mov rsi, rdx
.l: lodsb
    stosb
    test al, al
    jnz .l
    lea rax, [rdi-1]
END_FN

; Bounded builder:  pb_start(dst, size), then pb_str / pb_bytes / pb_chr / pb_int, then pb_end -> length, or -1 if anything was cut off.
FN pb_start
    mov [pb_base], rcx
    mov [pb_cur], rcx
    lea rax, [rcx+rdx-1]
    mov [pb_limit], rax
    mov dword [pb_over], 0
END_FN

FN pb_bytes                     ; rcx src, rdx count
    mov rsi, rcx
    mov rdi, [pb_cur]
    mov r8, [pb_limit]
.l: test rdx, rdx
    jz .d
    cmp rdi, r8
    jae .over
    mov al, [rsi]
    mov [rdi], al
    inc rdi
    inc rsi
    dec rdx
    jmp .l
.over:
    mov dword [pb_over], 1
.d: mov [pb_cur], rdi
END_FN

FN pb_str                       ; rcx NUL-terminated
    mov r12, rcx
    call str_len
    mov rcx, r12
    mov rdx, rax
    call pb_bytes
END_FN

FN pb_chr                       ; cl
    mov [rsp+48], cl
    lea rcx, [rsp+48]
    mov edx, 1
    call pb_bytes
END_FN

FN pb_int                       ; rcx unsigned decimal
    mov rax, rcx
    lea rdi, [rsp+80]
    xor r8d, r8d
    mov ecx, 10
.l: xor edx, edx
    div rcx
    add dl, '0'
    dec rdi
    mov [rdi], dl
    inc r8d
    test rax, rax
    jnz .l
    mov rcx, rdi
    mov edx, r8d
    call pb_bytes
END_FN

FN pb_end                       ; NUL-terminates -> eax length, -1 on overflow
    mov rdi, [pb_cur]
    mov byte [rdi], 0
    mov rax, rdi
    sub rax, [pb_base]
    cmp dword [pb_over], 0
    je .d
    mov eax, -1
.d:
END_FN

; Zero-padded decimal: rcx = value, edx = width, r8 = destination (width bytes written)
FN put_dec_pad
    mov rax, rcx
    mov r9, r8
    mov ecx, edx
    mov r10d, 10
.l: test ecx, ecx
    jz .d
    dec ecx
    xor edx, edx
    div r10
    add dl, '0'
    mov [r9+rcx], dl
    jmp .l
.d:
END_FN

FN hex_bytes                    ; rcx out, rdx src, r8 count -> writes 2*count lowercase hex digits and a NUL
    lea r10, [hex_digits]
    xor r9d, r9d
.l: cmp r9, r8
    jae .e
    movzx eax, byte [rdx+r9]
    mov r11d, eax
    shr r11d, 4
    and eax, 15
    mov r11b, [r10+r11]
    mov al, [r10+rax]
    mov [rcx+r9*2], r11b
    mov [rcx+r9*2+1], al
    inc r9
    jmp .l
.e: mov byte [rcx+r9*2], 0
END_FN

FN a_starts_ci                  ; rcx text, rdx lowercase prefix -> eax 1 if text begins with prefix (ASCII, case-insensitive)
.l: movzx eax, byte [rdx]
    test al, al
    jz .yes
    movzx r8d, byte [rcx]
    cmp r8b, 'A'
    jb .c
    cmp r8b, 'Z'
    ja .c
    or r8b, 32
.c: cmp al, r8b
    jne .no
    inc rcx
    inc rdx
    jmp .l
.yes:
    mov eax, 1
    jmp .d
.no:
    xor eax, eax
.d:
END_FN

%include "textutil.inc"

; ---------------- environment and arguments ----------------
FN env_get                      ; rcx NAME -> rax pointer to the value, or 0
    mov r12, rcx
    mov rsi, [envp_v]
.next:
    mov rdi, [rsi]
    test rdi, rdi
    jz .none
    xor ecx, ecx
.cmp:
    mov al, [r12+rcx]
    test al, al
    jz .name_end
    cmp al, [rdi+rcx]
    jne .skip
    inc ecx
    jmp .cmp
.name_end:
    cmp byte [rdi+rcx], '='
    jne .skip
    lea rax, [rdi+rcx+1]
    jmp .d
.skip:
    add rsi, 8
    jmp .next
.none:
    xor eax, eax
.d:
END_FN

FN arg_n                        ; ecx index -> rax pointer to argv[index], 0 if absent
    cmp rcx, [argc_v]
    jae .none
    mov rax, [argv_v]
    mov rax, [rax+rcx*8]
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

FN cut_last_component           ; rcx path: truncates at the last '/' (the root "/" stays)
    mov rsi, rcx
    xor r8, r8
    xor r9d, r9d
.l: movzx eax, byte [rsi+r9]
    test al, al
    jz .e
    cmp al, '/'
    jne .n
    mov r8, r9
.n: inc r9
    jmp .l
.e: test r8, r8
    jnz .cut
    cmp byte [rsi], '/'
    jne .d
    mov byte [rsi+1], 0
    jmp .d
.cut:
    mov byte [rsi+r8], 0
.d:
END_FN

FN base_name                    ; rcx path -> rax pointer to the part after the last '/'
    mov rax, rcx
.l: movzx edx, byte [rcx]
    test dl, dl
    jz .d
    inc rcx
    cmp dl, '/'
    jne .l
    mov rax, rcx
    jmp .l
.d:
END_FN

; ---------------- files ----------------
FN file_exists                  ; rcx path -> eax 1/0
    xor edx, edx
    call sys_access
    test rax, rax
    sete al
    movzx eax, al
END_FN

FN path_kind                    ; rcx path -> eax: 0 missing, 1 regular file, 2 directory, 3 other
    lea rdx, [st_buf]
    call sys_stat
    test rax, rax
    jnz .none
    mov eax, [st_buf+24]
    and eax, 0xF000
    cmp eax, 0x8000
    je .file
    cmp eax, 0x4000
    je .dir
    mov eax, 3
    jmp .d
.file:
    mov eax, 1
    jmp .d
.dir:
    mov eax, 2
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

FN read_file                    ; rcx path, rdx buffer, r8 max bytes -> rax bytes read, -1 on failure. Never reads more than r8.
    mov r12, rdx
    mov r13, r8
    mov edx, O_RDONLY | O_CLOEXEC | O_NONBLOCK   ; a FIFO named launcher.cfg must not be able to hang the launcher
    xor r8d, r8d
    call sys_open
    test rax, rax
    js .fail
    mov rbx, rax
    xor r14d, r14d
.rd:
    mov r8, r13
    sub r8, r14
    jz .ok
    mov rcx, rbx
    lea rdx, [r12+r14]
    call sys_read
    cmp rax, EINTR
    je .rd
    test rax, rax
    js .bad
    jz .ok
    add r14, rax
    jmp .rd
.ok:
    mov rcx, rbx
    call sys_close
    mov rax, r14
    jmp .d
.bad:
    mov rcx, rbx
    call sys_close
.fail:
    mov rax, -1
.d:
END_FN

FN write_all                    ; rcx fd, rdx data, r8 length -> eax 1 if everything was written
    mov rbx, rcx
    mov r12, rdx
    mov r13, r8
.l: test r13, r13
    jz .ok
    mov rcx, rbx
    mov rdx, r12
    mov r8, r13
    call sys_write
    cmp rax, EINTR
    je .l
    test rax, rax
    jle .fail
    add r12, rax
    sub r13, rax
    jmp .l
.ok:
    mov eax, 1
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN write_plain                  ; rcx path, rdx data, r8 length -> eax 1 ok (creates or truncates the file in place)
    mov r12, rdx
    mov r13, r8
    mov edx, O_WRITE_NEW
    mov r8d, 0644o
    call sys_open
    test rax, rax
    js .fail
    mov rbx, rax
    mov rcx, rbx
    mov rdx, r12
    mov r8, r13
    call write_all
    mov r14d, eax
    mov rcx, rbx
    call sys_close
    mov eax, r14d
    jmp .d
.fail:
    xor eax, eax
.d:
END_FN

FN write_file                   ; rcx path, rdx data, r8 length -> eax 1 ok. Writes <path>.tmp and renames it, so readers never see half a file.
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    lea rcx, [tmp_path]
    mov edx, 1100
    call pb_start
    mov rcx, r12
    call pb_str
    lea rcx, [s_tmp_suffix]
    call pb_str
    call pb_end
    cmp eax, -1
    je .fail
    lea rcx, [tmp_path]
    mov rdx, r13
    mov r8, r14
    call write_plain
    test eax, eax
    jz .cleanup
    lea rcx, [tmp_path]
    mov rdx, r12
    call sys_rename
    test rax, rax
    jnz .cleanup
    mov eax, 1
    jmp .d
.cleanup:
    lea rcx, [tmp_path]
    call sys_unlink
.fail:
    xor eax, eax
.d:
END_FN

FN copy_file                    ; rcx source, rdx destination -> eax 1 ok
    mov r12, rdx
    mov edx, O_RDONLY | O_CLOEXEC
    xor r8d, r8d
    call sys_open
    test rax, rax
    js .fail
    mov r13, rax
    mov rcx, r12
    mov edx, O_WRITE_NEW
    mov r8d, 0644o
    call sys_open
    test rax, rax
    js .closein
    mov r14, rax
.l: mov rcx, r13
    lea rdx, [copy_buf]
    mov r8d, 65536
    call sys_read
    cmp rax, EINTR
    je .l
    test rax, rax
    js .bad
    jz .ok
    mov r8, rax
    mov rcx, r14
    lea rdx, [copy_buf]
    call write_all
    test eax, eax
    jnz .l
.bad:
    xor r15d, r15d
    jmp .close
.ok:
    mov r15d, 1
.close:
    mov rcx, r14
    call sys_close
    mov rcx, r13
    call sys_close
    test r15d, r15d
    jnz .done
    mov rcx, r12
    call sys_unlink
    jmp .fail
.closein:
    mov rcx, r13
    call sys_close
.fail:
    xor r15d, r15d
.done:
    mov eax, r15d
END_FN

; Creates every missing folder in front of the last '/' of the path (the final name itself is not created).
FN ensure_dirs                  ; rcx path
    mov rsi, rcx
    mov r12d, 1
.l: movzx eax, byte [rsi+r12]
    test al, al
    jz .d
    cmp al, '/'
    jne .n
    mov byte [rsi+r12], 0
    mov rcx, rsi
    mov edx, 0755o
    call sys_mkdir
    mov byte [rsi+r12], '/'
.n: inc r12d
    jmp .l
.d:
END_FN

FN dir_open                     ; rcx path -> rax fd (negative on failure)
    mov edx, O_RDONLY | O_DIRECTORY | O_CLOEXEC
    xor r8d, r8d
    call sys_open
    mov [dir_fd], rax
    mov qword [dir_pos], 0
    mov qword [dir_end], 0
END_FN

FN dir_next                     ; -> rax pointer to the next entry name (skips . and ..), 0 at the end. dir_type = DT_ value.
.again:
    mov rax, [dir_pos]
    cmp rax, [dir_end]
    jb .have
    mov rcx, [dir_fd]
    lea rdx, [dir_buf]
    mov r8d, 8192
    call sys_getdents64
    cmp rax, EINTR
    je .again
    test rax, rax
    jle .none
    mov [dir_end], rax
    mov qword [dir_pos], 0
    xor eax, eax
.have:
    lea rsi, [dir_buf]
    add rsi, rax
    movzx ecx, word [rsi+16]
    add rcx, rax
    mov [dir_pos], rcx
    movzx ecx, byte [rsi+18]
    mov [dir_type], ecx
    lea rax, [rsi+19]
    cmp byte [rax], '.'
    jne .d
    cmp byte [rax+1], 0
    je .again
    cmp byte [rax+1], '.'
    jne .d
    cmp byte [rax+2], 0
    je .again
    jmp .d
.none:
    xor eax, eax
.d:
END_FN

FN dir_close
    mov rcx, [dir_fd]
    test rcx, rcx
    js .d
    call sys_close
    mov qword [dir_fd], -1
.d:
END_FN

; ---------------- time ----------------
FN ticks_ms                     ; -> rax milliseconds on the monotonic clock
    mov ecx, 1
    lea rdx, [ts_buf]
    call sys_clock_gettime
    mov rax, [ts_buf]
    imul rax, rax, 1000
    mov rcx, rax
    mov rax, [ts_buf+8]
    xor edx, edx
    mov r8d, 1000000
    div r8
    add rax, rcx
END_FN

FN sleep_ms                     ; ecx milliseconds
    mov eax, ecx
    xor edx, edx
    mov r8d, 1000
    div r8d
    mov [ts_buf], rax
    imul edx, edx, 1000000
    mov [ts_buf+8], rdx
    lea rcx, [ts_buf]
    xor edx, edx
    call sys_nanosleep
END_FN

; Writes "YYYYMMDD-HHMMSS" (UTC, 15 characters and a NUL) at rcx. UTC keeps the names sortable across daylight saving changes.
FN time_stamp
    mov r12, rcx
    xor ecx, ecx
    lea rdx, [ts_buf]
    call sys_clock_gettime
    mov rcx, r12
    mov rdx, [ts_buf]
    call time_stamp_at
END_FN

FN time_stamp_at                ; rcx out buffer, rdx = seconds since 1970-01-01 00:00:00 UTC
    mov r12, rcx
    mov rax, rdx
    xor edx, edx
    mov ecx, 86400
    div rcx
    mov r13, rax                    ; days since 1970-01-01
    mov rax, rdx
    xor edx, edx
    mov ecx, 3600
    div rcx
    mov r14, rax                    ; hours
    mov rax, rdx
    xor edx, edx
    mov ecx, 60
    div rcx
    mov r15, rax                    ; minutes
    mov [rsp+48], rdx               ; seconds
    ; civil date from the day number (proleptic Gregorian, March based years)
    lea rax, [r13+719468]
    xor edx, edx
    mov ecx, 146097
    div rcx
    mov rbx, rax                    ; era
    mov rsi, rdx                    ; day of era
    mov rax, rsi
    xor edx, edx
    mov ecx, 1460
    div rcx
    mov rdi, rsi
    sub rdi, rax
    mov rax, rsi
    xor edx, edx
    mov ecx, 36524
    div rcx
    add rdi, rax
    mov rax, rsi
    xor edx, edx
    mov ecx, 146096
    div rcx
    sub rdi, rax
    mov rax, rdi
    xor edx, edx
    mov ecx, 365
    div rcx
    mov rdi, rax                    ; year of era
    imul rax, rbx, 400
    add rax, rdi
    mov [rsp+56], rax               ; year, before the January/February adjustment
    imul r8, rdi, 365
    mov rax, rdi
    shr rax, 2
    add r8, rax
    mov rax, rdi
    xor edx, edx
    mov ecx, 100
    div rcx
    sub r8, rax
    sub rsi, r8                     ; day of year
    lea rax, [rsi+rsi*4+2]
    xor edx, edx
    mov ecx, 153
    div rcx
    mov rbx, rax                    ; month index, March = 0
    imul rax, rbx, 153
    add rax, 2
    xor edx, edx
    mov ecx, 5
    div rcx
    sub rsi, rax
    inc rsi
    mov [rsp+64], rsi               ; day of month
    lea rax, [rbx+3]
    cmp rbx, 10
    jb .m
    sub rax, 12
.m: mov [rsp+72], rax               ; month 1..12
    cmp rax, 2
    ja .y
    inc qword [rsp+56]
.y: mov rcx, [rsp+56]
    mov edx, 4
    mov r8, r12
    call put_dec_pad
    mov rcx, [rsp+72]
    mov edx, 2
    lea r8, [r12+4]
    call put_dec_pad
    mov rcx, [rsp+64]
    mov edx, 2
    lea r8, [r12+6]
    call put_dec_pad
    mov byte [r12+8], '-'
    mov rcx, r14
    mov edx, 2
    lea r8, [r12+9]
    call put_dec_pad
    mov rcx, r15
    mov edx, 2
    lea r8, [r12+11]
    call put_dec_pad
    mov rcx, [rsp+48]
    mov edx, 2
    lea r8, [r12+13]
    call put_dec_pad
    mov byte [r12+15], 0
END_FN

; ---------------- random ----------------
FN random_bytes                 ; rcx buffer, edx count (<= 256)
    mov r12, rcx
    mov r13d, edx
    xor r8d, r8d
    call sys_getrandom
    cmp rax, r13
    je .d
    lea rcx, [s_urandom]
    mov rdx, r12
    mov r8, r13
    call read_file
    cmp rax, r13
    je .d
    call ticks_ms                   ; last resort: not secret, but the game still starts
    mov r8, 6364136223846793005
    mov r9, 1442695040888963407
    xor ecx, ecx
.f: cmp ecx, r13d
    jae .d
    imul rax, r8
    add rax, r9
    mov rdx, rax
    shr rdx, 33
    mov [r12+rcx], dl
    inc ecx
    jmp .f
.d:
END_FN

FN guid_hex                     ; rcx -> 32 lowercase hex digits and a NUL (also leaves the 16 random bytes in guid)
    mov r12, rcx
    lea rcx, [guid]
    mov edx, 16
    call random_bytes
    mov rcx, r12
    lea rdx, [guid]
    mov r8d, 16
    call hex_bytes
END_FN

; ---------------- processes ----------------
FN sigpipe_set                  ; ecx = 1 ignore SIGPIPE, 0 default action
    mov [ts_buf], rcx
    mov qword [ts_buf+8], 0
    mov qword [ts_buf+16], 0
    mov qword [ts_buf+24], 0
    mov ecx, 13
    lea rdx, [ts_buf]
    xor r8d, r8d
    mov r9d, 8
    call sys_rt_sigaction
END_FN

; spawn(path, argv, stdin_fd, stdout_fd, [stderr_fd], [flags]) -> rax pid, or -1.  A descriptor of -1 keeps the inherited one.
; flags: 1 = the child dies with this process (PR_SET_PDEATHSIG SIGKILL), 2 = search PATH when the name has no '/'
FN spawn
    mov r12, rcx
    mov r13, rdx
    mov r14, r8
    mov r15, r9
    call sys_getpid
    mov rbx, rax
    call sys_fork
    test rax, rax
    js .fail
    jnz .parent
    ; ---- child ----
    test dword [rbp+56], 1
    jz .nopdeath
    mov ecx, 1                      ; PR_SET_PDEATHSIG
    mov edx, 9                      ; SIGKILL
    xor r8d, r8d
    xor r9d, r9d
    call sys_prctl
    call sys_getppid
    cmp rax, rbx
    jne .die                        ; the launcher is already gone
.nopdeath:
    cmp r14, -1
    je .o
    mov rcx, r14
    xor edx, edx
    call sys_dup2
.o: cmp r15, -1
    je .e
    mov rcx, r15
    mov edx, 1
    call sys_dup2
.e: mov rcx, [rbp+48]
    cmp rcx, -1
    je .go
    mov edx, 2
    call sys_dup2
.go:
    xor ecx, ecx
    call sigpipe_set                    ; an ignored SIGPIPE would be inherited by the program started below
    mov rcx, r12
    mov rdx, r13
    test dword [rbp+56], 2
    jz .direct
    call exec_search
    jmp .die
.direct:
    mov r8, [envp_v]
    call sys_execve
.die:
    mov ecx, 127
    call sys_exit
.parent:
    jmp .d
.fail:
    mov rax, -1
.d:
END_FN

; execvp: rcx = program name (argv[0] of rdx), rdx = argv. Returns only when nothing could be executed.
FN exec_search
    mov r12, rcx
    mov r13, rdx
    mov rcx, r12
.sl:cmp byte [rcx], 0
    je .search
    cmp byte [rcx], '/'
    je .plain
    inc rcx
    jmp .sl
.plain:
    mov rcx, r12
    mov rdx, r13
    mov r8, [envp_v]
    call sys_execve
    jmp .d
.search:
    lea rcx, [s_env_path]
    call env_get
    test rax, rax
    jnz .have
    lea rax, [s_default_path]
.have:
    mov r14, rax
.seg:
    lea rcx, [tmp_path]
    mov edx, 1100
    call pb_start
    mov rsi, r14
.cp:movzx eax, byte [rsi]
    test al, al
    jz .segend
    cmp al, ':'
    je .segend
    inc rsi
    jmp .cp
.segend:
    mov r15, rsi
    mov rcx, r14
    mov rdx, rsi
    sub rdx, rcx
    jz .skipdir
    call pb_bytes
    mov cl, '/'
    call pb_chr
.skipdir:
    mov rcx, r12
    call pb_str
    call pb_end
    cmp eax, -1
    je .nextseg
    lea rcx, [tmp_path]
    mov rdx, r13
    mov r8, [envp_v]
    call sys_execve
.nextseg:
    cmp byte [r15], 0
    je .d
    lea r14, [r15+1]
    jmp .seg
.d:
END_FN

; Decodes a wait status into a shell style exit code.
FN proc_poll                    ; rcx pid -> rax exit code (signals count as 128+n), -1 while the process is still running
    mov r12, rcx
    lea rdx, [status_v]
    mov r8d, 1                      ; WNOHANG
    xor r9d, r9d
    call sys_wait4
    test rax, rax
    jz .running
    js .gone
    mov eax, [status_v]
    mov ecx, eax
    and ecx, 0x7f
    jz .exited
    lea eax, [rcx+128]
    jmp .d
.exited:
    shr eax, 8
    and eax, 0xff
    jmp .d
.gone:
    mov eax, 1
    jmp .d
.running:
    mov rax, -1
.d:
END_FN

FN proc_wait                    ; rcx pid, edx timeout in milliseconds -> exit code, or -1 if it is still running afterwards
    mov r12, rcx
    mov r13d, edx
    call ticks_ms
    add r13, rax
.l: mov rcx, r12
    call proc_poll
    cmp rax, -1
    jne .d
    call ticks_ms
    cmp rax, r13
    jae .late
    mov ecx, 20
    call sleep_ms
    jmp .l
.late:
    mov rax, -1
.d:
END_FN

FN proc_kill                    ; rcx pid: SIGKILL, then reap it
    mov r12, rcx
    mov edx, 9
    call sys_kill
    mov rcx, r12
    lea rdx, [status_v]
    xor r8d, r8d
    xor r9d, r9d
    call sys_wait4
END_FN

; ---------------- console ----------------
FN say                          ; rcx NUL-terminated text -> stdout
    mov r12, rcx
    call str_len
    mov r8, rax
    mov ecx, 1
    mov rdx, r12
    call write_all
END_FN

FN say_err
    mov r12, rcx
    call str_len
    mov r8, rax
    mov ecx, 2
    mov rdx, r12
    call write_all
END_FN

; next input byte -> eax, or -1 at the end of the input (refills from stdin; works for terminals and pipes)
FN getc
    mov eax, [in_pos]
    cmp eax, [in_len]
    jb .have
.rd:xor ecx, ecx
    lea rdx, [inbuf]
    mov r8d, 250
    call sys_read
    cmp rax, EINTR
    je .rd
    test rax, rax
    jle .eof
    mov [in_len], eax
    mov dword [in_pos], 0
.have:
    mov eax, [in_pos]
    lea rcx, [inbuf]
    movzx eax, byte [rcx+rax]
    inc dword [in_pos]
    jmp .d
.eof:
    mov dword [in_pos], 0
    mov dword [in_len], 0
    mov eax, -1
.d:
END_FN

; rcx prompt, rdx out buffer, r8 size -> eax length, -1 at the end of the input. Spaces and the line ending are dropped.
FN ask
    mov r12, rdx
    mov r13, r8
    dec r13
    call say
    xor r14d, r14d                  ; characters stored
    xor r15d, r15d                  ; bytes seen
.ch:
    call getc
    cmp eax, -1
    je .end
    inc r15d
    cmp al, 10
    je .e
    cmp al, 13
    je .ch
    cmp al, ' '
    je .ch
    cmp r14, r13
    jae .ch
    mov [r12+r14], al
    inc r14
    jmp .ch
.end:
    test r15d, r15d
    jz .eof
.e: mov byte [r12+r14], 0
    mov eax, r14d
    jmp .d
.eof:
    mov byte [r12], 0
    mov eax, -1
.d:
END_FN

section .data
s_tmp_suffix db '.tmp',0
s_urandom db '/dev/urandom',0
hex_digits db '0123456789abcdef'
s_env_path db 'PATH',0
s_default_path db '/usr/local/bin:/usr/bin:/bin',0
align 8
section .text
