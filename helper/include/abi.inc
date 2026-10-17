; Internal ABI

%macro FN 1
%xdefine current_fn %1
global %1
%1:
    push rbp
    mov rbp, rsp
    push rbx
    push rsi
    push rdi
    push r12
    push r13
    push r14
    push r15
    sub rsp, 104
%endmacro
%macro END_FN 0
    lea rsp, [rsp+104]
    pop r15
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    pop rbp
    ret
%ifdef WINDOWS
current_fn %+ _end:
section .pdata rdata align=4
    dd current_fn wrt ..imagebase
    dd current_fn %+ _end wrt ..imagebase
    dd current_fn %+ _unwind wrt ..imagebase
section .xdata rdata align=4
current_fn %+ _unwind:
    db 1, 19, 9, 0
    db 19, 0xc2, 15, 0xf0, 13, 0xe0, 11, 0xd0, 9, 0xc0
    db 7, 0x70, 6, 0x60, 5, 0x30, 1, 0x50, 0, 0
section .text
%endif
%endmacro
