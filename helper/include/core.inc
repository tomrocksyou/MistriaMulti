; MistriMulti UDP transport.
; UDP snapshots with bounded fragmentation, per-source reassembly, and replay rejection.
; Game-level acknowledged event queues ride inside these snapshots.
%define MAX_PLAYERS 8
%define MAX_STATE 16384
%define FRAGMENT 1152
%define HEADER 40
%define REC_SIZE 32832
%define P_ADDR 0
%define P_SEEN 16
%define P_SEQ 24
%define P_ASM_SEQ 28
%define P_HASH 32
%define P_LENGTH 36
%define P_BITS 40
%define P_WANT 44
%define P_PRESENT 48
%define P_COMPLETE 52
%define P_EPOCH 56
%define P_BUILD 64
%define P_CACHE (64+MAX_STATE)

section .data
udp_socket dq -1
mode_host dd 0
local_id dd 0
session_code dd 0
local_epoch dd 0
local_port dd 0
tx_reliable dd 0
tx_hash dd 0
tx_length dd 2
tx_sequence dd 1
last_send dq 0
last_status dq 0
now_ms dq 0
tx_packets dq 0
rx_packets dq 0
bad_packets dq 0
local_address dw 2,0
    dd 0
    dq 0
host_address dw 2,0
    dd 0
    dq 0
initial_json db '{"active":false}',0
inactive_json db '{"active":false}',0
tx_suffix db '/tx.frame',0
rx_suffix db '/rx_0.json',0
status_suffix db '/status.json',0
stop_suffix db '/stop.flag',0
usage db 'MistriMulti 0.1.0 - native NASM multiplayer helper',10
    db 'host: mistrimulti-helper host LOCAL_PORT 0 SESSION_HEX BRIDGE_DIRECTORY',10
    db 'join: mistrimulti-helper join LOCAL_PORT PLAYER_ID SESSION_HEX BRIDGE_DIRECTORY HOST_IPV4 HOST_PORT',10
    db 'PLAYER_ID: host=0; each joining player uses a different number 1..7.',10
    db 'SESSION_HEX: shared eight-digit hex room code. IPv4 only.',10
    db 'The bridge directory must already exist. Create stop.flag there to exit.',10,0
started db 'MistriMulti helper running. Ctrl+C or stop.flag exits.',10,0
bad_arguments db 'Invalid arguments. Run the helper without arguments for usage.',10,0
socket_error db 'Could not create or bind UDP socket. Check port and network permissions.',10,0
status_prefix db '{"running":true,"id":',0
status_middle db ',"mask":',0
status_tx db ',"tx":',0
status_rx db ',"rx":',0
status_bad db ',"dropped":',0
status_heartbeat db ',"heartbeat":',0
status_end db '}',0
stopped_json db '{"running":false,"mask":0}',0

section .bss
base_dir resb 2048
tx_path resb 2112
rx_path resb 2112
status_path resb 2112
stop_path resb 2112
file_bytes resb MAX_STATE+3
packet_in resb HEADER+FRAGMENT+1
packet_out resb HEADER+FRAGMENT
source_address resb 16
peers resb REC_SIZE*MAX_PLAYERS
status_buffer resb 256
number_buffer resb 32

section .text
FN mistria_main
    call parse_arguments
    test eax, eax
    jz .usage
    cmp eax, -1
    je .arguments
    call pl_socket
    test rax, rax
    js .network
    mov [udp_socket], rax
    mov rcx, rax
    lea rdx, [local_address]
    call pl_bind
    test rax, rax
    js .network
    call pl_ticks
    mov [local_epoch], eax
    mov [now_ms], rax
    mov [last_status], rax
    mov ecx, [local_id]
    call peer_pointer
    mov r12, rax
    mov eax, [local_epoch]
    mov [r12+P_EPOCH], eax
    mov dword [r12+P_PRESENT], 1
    mov dword [r12+P_COMPLETE], 1
    mov dword [r12+P_SEQ], 1
    lea rcx, [r12+P_CACHE]
    lea rdx, [initial_json]
    call text_copy
    mov dword [r12+P_LENGTH], 16
    lea rcx, [r12+P_CACHE]
    mov edx, 16
    call hash_bytes
    mov [r12+P_HASH], eax
    lea rcx, [started]
    call pl_print
    call publish_status
.loop:
    mov rcx, [udp_socket]
    mov edx, 50
    call pl_poll
    call pl_ticks
    mov [now_ms], rax
    call read_local_frame
    mov ebx, 32
.drain:
    mov rcx, [udp_socket]
    lea rdx, [packet_in]
    mov r8d, HEADER+FRAGMENT+1
    lea r9, [source_address]
    call pl_recv
    test rax, rax
    js .send
    mov ecx, eax
    call receive_fragment
    dec ebx
    jnz .drain
.send:
    mov rax, [now_ms]
    sub rax, [last_send]
    mov edx, 1000
    cmp dword [tx_reliable], 0
    je .interval
    mov edx, 100
.interval:
    cmp rax, rdx
    jb .status
    call send_local
    mov rax, [now_ms]
    mov [last_send], rax
.status:
    mov rax, [now_ms]
    sub rax, [last_status]
    cmp rax, 1000
    jb .loop
    call expire_peers
    call publish_status
    mov rax, [now_ms]
    mov [last_status], rax
    lea rcx, [stop_path]
    call pl_exists
    test eax, eax
    jz .loop
    lea rcx, [status_path]
    lea rdx, [stopped_json]
    mov r8d, 26
    call pl_atomic
    xor ecx, ecx
    call pl_exit
.usage:
    lea rcx, [usage]
    call pl_print
    xor ecx, ecx
    call pl_exit
.arguments:
    lea rcx, [bad_arguments]
    call pl_print
    mov ecx, 2
    call pl_exit
.network:
    lea rcx, [socket_error]
    call pl_print
    mov ecx, 3
    call pl_exit
END_FN

FN text_length
    xor eax, eax
.loop:
    cmp byte [rcx+rax], 0
    je .done
    inc eax
    jmp .loop
.done:
END_FN

; Copy NUL-terminated string, returning the address of its destination terminator.
FN text_copy
.loop:
    mov al, [rdx]
    mov [rcx], al
    test al, al
    jz .done
    inc rcx
    inc rdx
    jmp .loop
.done:
    mov rax, rcx
END_FN

FN bytes_copy
    mov rax, rcx
    mov rdi, rcx
    mov rsi, rdx
    mov rcx, r8
    cld
    rep movsb
END_FN

; FNV-1a is an integrity checksum, not cryptographic authentication.
FN hash_bytes
    mov eax, 2166136261
    xor r8d, r8d
.loop:
    cmp r8, rdx
    jae .done
    movzx r9d, byte [rcx+r8]
    xor eax, r9d
    imul eax, 16777619
    inc r8d
    jmp .loop
.done:
END_FN

; Decimal parse, rejects empty/non-digit/overflow; carry flag on failure.
FN parse_decimal
    xor eax, eax
    cmp byte [rcx], 0
    je .bad
.loop:
    movzx edx, byte [rcx]
    test edx, edx
    jz .good
    sub edx, '0'
    cmp edx, 9
    ja .bad
    cmp eax, 429496729
    ja .bad
    imul eax, 10
    add eax, edx
    jc .bad
    inc rcx
    jmp .loop
.good:
    clc
    jmp .done
.bad:
    stc
.done:
END_FN

FN parse_hex
    xor eax, eax
    xor r8d, r8d
.loop:
    movzx edx, byte [rcx+r8]
    test edx, edx
    jz .finish
    cmp r8d, 8
    jae .bad
    cmp edx, '0'
    jb .bad
    cmp edx, '9'
    jbe .digit
    or edx, 32
    sub edx, 'a'
    cmp edx, 5
    ja .bad
    add edx, 10
    jmp .append
.digit:
    sub edx, '0'
.append:
    shl eax, 4
    or eax, edx
    inc r8d
    jmp .loop
.finish:
    cmp r8d, 8
    jne .bad
    clc
    jmp .done
.bad:
    stc
.done:
END_FN

FN parse_ip
    lea rdi, [host_address+4]
    xor r8d, r8d
.octet:
    xor eax, eax
    xor r9d, r9d
.digit:
    movzx edx, byte [rcx]
    cmp edx, '0'
    jb .end_octet
    cmp edx, '9'
    ja .end_octet
    sub edx, '0'
    imul eax, 10
    add eax, edx
    cmp eax, 255
    ja .bad
    inc r9d
    cmp r9d, 3
    ja .bad
    inc rcx
    jmp .digit
.end_octet:
    test r9d, r9d
    jz .bad
    mov [rdi+r8], al
    inc r8d
    cmp r8d, 4
    je .finish
    cmp byte [rcx], '.'
    jne .bad
    inc rcx
    jmp .octet
.finish:
    cmp byte [rcx], 0
    jne .bad
    clc
    jmp .done
.bad:
    stc
.done:
END_FN

FN parse_arguments
    call pl_args_init
    cmp eax, 2
    jb .usage
    mov r12d, eax
    mov ecx, 1
    call pl_arg
    cmp dword [rax], 'host'
    je .host
    cmp dword [rax], 'join'
    jne .bad
    cmp byte [rax+4], 0
    jne .bad
    cmp r12d, 8
    jne .bad
    jmp .port
.host:
    cmp byte [rax+4], 0
    jne .bad
    cmp r12d, 6
    jne .bad
    mov dword [mode_host], 1
.port:
    mov ecx, 2
    call pl_arg
    mov rcx, rax
    call parse_decimal
    jc .bad
    test eax, eax
    jz .bad
    cmp eax, 65535
    ja .bad
    mov [local_port], eax
    xchg al, ah
    mov [local_address+2], ax
    mov ecx, 3
    call pl_arg
    mov rcx, rax
    call parse_decimal
    jc .bad
    cmp eax, MAX_PLAYERS
    jae .bad
    cmp dword [mode_host], 1
    je .host_id
    test eax, eax
    jz .bad
    jmp .id
.host_id:
    test eax, eax
    jnz .bad
.id:
    mov [local_id], eax
    mov ecx, 4
    call pl_arg
    mov rcx, rax
    call parse_hex
    jc .bad
    mov [session_code], eax
    mov ecx, 5
    call pl_arg
    mov r13, rax
    mov rcx, rax
    call text_length
    test eax, eax
    jz .bad
    cmp eax, 2000
    ja .bad
    lea rcx, [base_dir]
    mov rdx, r13
    call text_copy
    lea rcx, [tx_path]
    lea rdx, [tx_suffix]
    call make_path
    lea rcx, [rx_path]
    lea rdx, [rx_suffix]
    call make_path
    lea rcx, [status_path]
    lea rdx, [status_suffix]
    call make_path
    lea rcx, [stop_path]
    lea rdx, [stop_suffix]
    call make_path
    cmp dword [mode_host], 1
    je .good
    mov ecx, 6
    call pl_arg
    mov rcx, rax
    call parse_ip
    jc .bad
    mov ecx, 7
    call pl_arg
    mov rcx, rax
    call parse_decimal
    jc .bad
    test eax, eax
    jz .bad
    cmp eax, 65535
    ja .bad
    xchg al, ah
    mov [host_address+2], ax
.good:
    mov eax, 1
    jmp .done
.usage:
    xor eax, eax
    jmp .done
.bad:
    mov eax, -1
.done:
END_FN

; destination RCX and suffix RDX -> full path destination.
FN make_path
    mov r12, rdx
    lea rdx, [base_dir]
    call text_copy
    mov rcx, rax
    mov rdx, r12
    call text_copy
END_FN

FN peer_pointer
    imul rax, rcx, REC_SIZE
    lea rdx, [peers]
    add rax, rdx
END_FN

FN read_local_frame
    lea rcx, [tx_path]
    lea rdx, [file_bytes]
    mov r8d, MAX_STATE+3
    call pl_read
    cmp rax, 4
    jl .done
    cmp rax, MAX_STATE+2
    ja .done
    cmp byte [file_bytes+1], 10
    jne .done
    movzx edx, byte [file_bytes]
    sub edx, '0'
    cmp edx, 1
    ja .done
    mov [tx_reliable], edx
    sub eax, 2
    mov r12d, eax
    mov ecx, [local_id]
    call peer_pointer
    mov r13, rax
    cmp r12d, [r13+P_LENGTH]
    jne .changed
    lea rsi, [file_bytes+2]
    lea rdi, [r13+P_CACHE]
    mov ecx, r12d
    cld
    repe cmpsb
    je .done
.changed:
    inc dword [tx_sequence]
    mov eax, [tx_sequence]
    mov [r13+P_SEQ], eax
    mov [r13+P_LENGTH], r12d
    lea rcx, [r13+P_CACHE]
    lea rdx, [file_bytes+2]
    mov r8d, r12d
    call bytes_copy
    lea rcx, [r13+P_CACHE]
    mov edx, r12d
    call hash_bytes
    mov [r13+P_HASH], eax
    call send_local
    mov rax, [now_ms]
    mov [last_send], rax
.done:
END_FN

FN send_local
    mov ecx, [local_id]
    call peer_pointer
    mov r12, rax
    cmp dword [mode_host], 0
    jne .host
    mov rcx, r12
    lea rdx, [host_address]
    mov r8d, [local_id]
    call send_record
    jmp .done
.host:
    mov ebx, 1
.peer:
    cmp ebx, MAX_PLAYERS
    jae .done
    mov ecx, ebx
    call peer_pointer
    cmp dword [rax+P_PRESENT], 0
    je .next
    mov rdx, rax
    mov rcx, r12
    xor r8d, r8d
    call send_record
.next:
    inc ebx
    jmp .peer
.done:
END_FN

; RCX source record, RDX destination sockaddr, R8D original source player ID.
FN send_record
    mov r12, rcx
    mov r13, rdx
    mov r14d, r8d
    mov dword [packet_out], 'MSMP'
    mov word [packet_out+4], 1
    mov word [packet_out+6], 0
    mov [packet_out+8], r14d
    mov eax, [r12+P_SEQ]
    mov [packet_out+12], eax
    mov eax, [session_code]
    mov [packet_out+16], eax
    mov eax, [r12+P_HASH]
    mov [packet_out+20], eax
    mov eax, [r12+P_LENGTH]
    mov [packet_out+24], eax
    add eax, FRAGMENT-1
    xor edx, edx
    mov ecx, FRAGMENT
    div ecx
    mov [packet_out+30], ax
    mov eax, [r12+P_EPOCH]
    mov [packet_out+32], eax
    mov dword [packet_out+36], 0
    xor ebx, ebx
    xor r15d, r15d
.chunk:
    mov [packet_out+28], bx
    mov r8d, [r12+P_LENGTH]
    sub r8d, r15d
    cmp r8d, FRAGMENT
    jbe .size
    mov r8d, FRAGMENT
.size:
    mov [rsp+64], r8d
    lea rcx, [packet_out+HEADER]
    lea rdx, [r12+P_CACHE+r15]
    call bytes_copy
    mov rcx, [udp_socket]
    lea rdx, [packet_out]
    mov r8d, [rsp+64]
    add r8d, HEADER
    mov r9, r13
    call pl_send
    test rax, rax
    js .next
    inc qword [tx_packets]
.next:
    inc ebx
    add r15d, FRAGMENT
    cmp r15d, [r12+P_LENGTH]
    jb .chunk
END_FN

; Datagram length in ECX; buffer/address are platform-filled globals.
FN receive_fragment
    cmp ecx, HEADER+1
    jb .bad
    cmp ecx, HEADER+FRAGMENT
    ja .bad
    mov r15d, ecx
    cmp dword [packet_in], 'MSMP'
    jne .bad
    cmp dword [packet_in+4], 1
    jne .bad
    mov eax, [session_code]
    cmp eax, [packet_in+16]
    jne .bad
    mov r12d, [packet_in+8]
    cmp r12d, MAX_PLAYERS
    jae .bad
    cmp r12d, [local_id]
    je .done
    mov ebx, [packet_in+24]
    cmp ebx, 2
    jb .bad
    cmp ebx, MAX_STATE
    ja .bad
    lea eax, [rbx+FRAGMENT-1]
    xor edx, edx
    mov ecx, FRAGMENT
    div ecx
    cmp ax, [packet_in+30]
    jne .bad
    movzx edx, word [packet_in+28]
    cmp edx, eax
    jae .bad
    imul r14d, edx, FRAGMENT
    mov ecx, ebx
    sub ecx, r14d
    cmp ecx, FRAGMENT
    jbe .length
    mov ecx, FRAGMENT
.length:
    add ecx, HEADER
    cmp ecx, r15d
    jne .bad
    cmp dword [mode_host], 0
    je .client
    test r12d, r12d
    jz .bad
    jmp .record
.client:
    mov rax, [source_address]
    cmp rax, [host_address]
    jne .bad
.record:
    mov ecx, r12d
    call peer_pointer
    mov r13, rax
    cmp dword [mode_host], 0
    je .source_ok
    cmp dword [r13+P_PRESENT], 0
    je .new_peer
    mov rax, [source_address]
    cmp rax, [r13+P_ADDR]
    jne .bad
    jmp .source_ok
.new_peer:
    mov rax, [source_address]
    mov [r13+P_ADDR], rax
    mov rax, [source_address+8]
    mov [r13+P_ADDR+8], rax
.source_ok:
    mov rax, [now_ms]
    mov [r13+P_SEEN], rax
    mov dword [r13+P_PRESENT], 1
    mov eax, [packet_in+32]
    cmp eax, [r13+P_EPOCH]
    je .same_epoch
    mov [r13+P_EPOCH], eax
    mov dword [r13+P_COMPLETE], 0
    mov dword [r13+P_BITS], 0
    mov eax, [packet_in+12]
    mov [r13+P_ASM_SEQ], eax
    jmp .begin_frame
.same_epoch:
    mov eax, [packet_in+12]
    sub eax, [r13+P_ASM_SEQ]
    js .done
    jnz .new_frame
    cmp dword [r13+P_COMPLETE], 0
    jne .heartbeat
    cmp dword [r13+P_BITS], 0
    jne .same_frame
    jmp .begin_frame
.new_frame:
    mov eax, [packet_in+12]
    mov [r13+P_ASM_SEQ], eax
    mov dword [r13+P_COMPLETE], 0
.begin_frame:
    mov dword [r13+P_BITS], 0
    mov eax, [packet_in+20]
    mov [r13+P_HASH], eax
    mov eax, [packet_in+24]
    mov [r13+P_LENGTH], eax
    movzx ecx, word [packet_in+30]
    mov eax, 1
    shl eax, cl
    dec eax
    mov [r13+P_WANT], eax
.same_frame:
    mov eax, [packet_in+20]
    cmp eax, [r13+P_HASH]
    jne .bad
    mov eax, [packet_in+24]
    cmp eax, [r13+P_LENGTH]
    jne .bad
    lea rcx, [r13+P_BUILD+r14]
    lea rdx, [packet_in+HEADER]
    mov r8d, r15d
    sub r8d, HEADER
    call bytes_copy
    movzx ecx, word [packet_in+28]
    bts [r13+P_BITS], ecx
    mov eax, [r13+P_BITS]
    cmp eax, [r13+P_WANT]
    jne .done
    lea rcx, [r13+P_BUILD]
    mov edx, [r13+P_LENGTH]
    call hash_bytes
    cmp eax, [r13+P_HASH]
    jne .corrupt
    mov eax, [r13+P_ASM_SEQ]
    mov [r13+P_SEQ], eax
    lea rcx, [r13+P_CACHE]
    lea rdx, [r13+P_BUILD]
    mov r8d, [r13+P_LENGTH]
    call bytes_copy
    mov ecx, r12d
    mov rdx, r13
    call publish_record
    test eax, eax
    jz .done
    mov dword [r13+P_COMPLETE], 1
    inc qword [rx_packets]
    cmp dword [mode_host], 0
    je .done
    ; Broadcast accepted, fully reassembled state to every other live client.
    mov ebx, 1
.forward:
    cmp ebx, MAX_PLAYERS
    jae .done
    cmp ebx, r12d
    je .next_peer
    mov ecx, ebx
    call peer_pointer
    cmp dword [rax+P_PRESENT], 0
    je .next_peer
    mov rdx, rax
    mov rcx, r13
    mov r8d, r12d
    call send_record
.next_peer:
    inc ebx
    jmp .forward
.heartbeat:
    inc qword [rx_packets]
    cmp dword [mode_host], 0
    je .done
    ; Forward one cached snapshot on the last heartbeat fragment. This also
    ; introduces idle players to late joiners without rewriting game IPC files.
    movzx eax, word [packet_in+28]
    inc eax
    cmp ax, [packet_in+30]
    jne .done
    mov ebx, 1
    jmp .forward
.corrupt:
    mov dword [r13+P_BITS], 0
.bad:
    inc qword [bad_packets]
.done:
END_FN

FN publish_record
    mov r12, rdx
    mov ebx, ecx
    lea rcx, [rx_path]
    lea rdx, [rx_suffix]
    call make_path
    lea rcx, [base_dir]
    call text_length
    add bl, '0'
    lea rdx, [rx_path]
    mov [rdx+rax+4], bl
    lea rcx, [rx_path]
    lea rdx, [r12+P_CACHE]
    mov r8d, [r12+P_LENGTH]
    call pl_atomic
END_FN

FN expire_peers
    xor ebx, ebx
.peer:
    cmp ebx, MAX_PLAYERS
    jae .done
    cmp ebx, [local_id]
    je .next
    mov ecx, ebx
    call peer_pointer
    mov r12, rax
    cmp dword [r12+P_PRESENT], 0
    je .next
    mov rax, [now_ms]
    sub rax, [r12+P_SEEN]
    cmp rax, 10000
    jb .next
    mov dword [r12+P_PRESENT], 0
    mov dword [r12+P_COMPLETE], 0
    mov dword [r12+P_BITS], 0
    mov dword [r12+P_EPOCH], 0
    lea rcx, [r12+P_CACHE]
    lea rdx, [inactive_json]
    call text_copy
    mov dword [r12+P_LENGTH], 16
    mov ecx, ebx
    mov rdx, r12
    call publish_record
.next:
    inc ebx
    jmp .peer
.done:
END_FN

; Append decimal unsigned 64-bit RCX to destination RDX, returning terminator.
FN append_number
    mov r12, rdx
    mov rax, rcx
    lea rdi, [number_buffer+31]
    mov byte [rdi], 0
    mov ebx, 10
.digit:
    xor edx, edx
    div rbx
    add dl, '0'
    dec rdi
    mov [rdi], dl
    test rax, rax
    jnz .digit
    mov rcx, r12
    mov rdx, rdi
    call text_copy
END_FN

FN publish_status
    xor r12d, r12d
    xor ebx, ebx
.mask:
    cmp ebx, MAX_PLAYERS
    jae .write
    cmp ebx, [local_id]
    je .next
    mov ecx, ebx
    call peer_pointer
    cmp dword [rax+P_PRESENT], 0
    je .next
    bts r12d, ebx
.next:
    inc ebx
    jmp .mask
.write:
    lea rcx, [status_buffer]
    lea rdx, [status_prefix]
    call text_copy
    mov rdx, rax
    mov ecx, [local_id]
    call append_number
    mov rcx, rax
    lea rdx, [status_middle]
    call text_copy
    mov rdx, rax
    mov ecx, r12d
    call append_number
    mov rcx, rax
    lea rdx, [status_tx]
    call text_copy
    mov rdx, rax
    mov rcx, [tx_packets]
    call append_number
    mov rcx, rax
    lea rdx, [status_rx]
    call text_copy
    mov rdx, rax
    mov rcx, [rx_packets]
    call append_number
    mov rcx, rax
    lea rdx, [status_bad]
    call text_copy
    mov rdx, rax
    mov rcx, [bad_packets]
    call append_number
    mov rcx, rax
    lea rdx, [status_heartbeat]
    call text_copy
    mov rdx, rax
    mov rcx, [now_ms]
    call append_number
    mov rcx, rax
    lea rdx, [status_end]
    call text_copy
    lea rdx, [status_buffer]
    sub rax, rdx
    mov r8, rax
    lea rcx, [status_path]
    call pl_atomic
END_FN
