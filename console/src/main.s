.include "hardware.inc"
.include "speed_limits.inc"

.import measure_speed, compute_speed
.import screen_off, screen_on, clear_screen, set_palette, locate, print_text
.import print_number, print_signed, print_hex
.importzp text, value, cycles_x100, speed_x10000, intervals, rewrite_count

RATIO_ONE = 10000
TWO_DECIMALS = 2
NO_DECIMALS = 0
ROW_TITLE = 2
ROW_FIRST = 5
COLUMN_LEFT = 2
COLUMN_VALUE = 20
ROW_CYCLES = 5
ROW_TARGET = 6
ROW_SPEED = 7
ROW_BYTES = 8
ROW_COARSE = 10
ROW_FINE = 11
ROW_ULTRA = 12
ROW_ADVICE = 14
ROW_STREAK = 16
ROW_WARNING = 18
ROW_ERROR = 19
ROW_AGAIN = 22
COLUMN_VERDICT = 14

.macro show row, column, label
    ldx #row
    ldy #column
    jsr locate
    lda #<label
    sta text
    lda #>label
    sta text + 1
    jsr print_text
.endmacro

.segment "ZEROPAGE"
disk_error: .res 1
ultra_streak: .res 1
buttons: .res 1
lower_limit: .res 2
upper_limit: .res 2

.segment "RODATA"
title: .byte "FDSTOOLKIT  DRIVE SPEED", 0
step_connect: .byte "1 CONNECT THE DISK DRIVE", 0
step_insert: .byte "2 INSERT A FACTORY DISK", 0
step_press: .byte "3 PRESS A", 0
explain_first: .byte "EVERY FILE IS READ AND ITS", 0
explain_second: .byte "BYTES TIMED BY THE CPU CLOCK", 0
measuring: .byte "MEASURING, WAIT", 0
label_cycles: .byte "CYCLES PER BYTE", 0
label_target: .byte "TARGET", 0
label_speed: .byte "SPEED", 0
label_bytes: .byte "BYTES TIMED", 0
label_coarse: .byte "COARSE 10%", 0
label_fine: .byte "FINE    5%", 0
label_ultra: .byte "ULTRA   1%", 0
verdict_pass: .byte "PASS", 0
verdict_fail: .byte "FAIL", 0
advice_lower: .byte "LOWER THE MOTOR SPEED", 0
advice_raise: .byte "RAISE THE MOTOR SPEED", 0
advice_hold: .byte "SPEED IS WITHIN 1%, HOLD IT", 0
label_streak: .byte "ULTRA PASSES IN A ROW", 0
warning_rewritten: .byte "REWRITTEN DISK: USE A FACTORY ONE", 0
label_error: .byte "DISK ERROR $", 0
nothing_timed: .byte "NO FILE DATA COULD BE TIMED", 0
press_again: .byte "PRESS A TO MEASURE AGAIN", 0

.segment "CODE"
.proc license_bypass
    lda #0
    sta PPU_CTRL
    lda #<ignore_interrupt
    sta NMI_VECTOR_3
    lda #>ignore_interrupt
    sta NMI_VECTOR_3 + 1
    lda #RESET_FLAG_GAME
    sta RESET_FLAG
    lda #RESET_TYPE_GAME
    sta RESET_TYPE
    jmp (BIOS_RESET_VECTOR)
.endproc

.proc ignore_interrupt
    rti
.endproc

.proc reset
    sei
    cld
    ldx #$FF
    txs
    lda #0
    sta PPU_CTRL
    sta PPU_CTRL_MIRROR
    sta ultra_streak
    jsr draw_intro
main_loop:
    jsr wait_for_a
    jsr draw_measuring
    jsr measure_speed
    sta disk_error
    jsr draw_results
    jmp main_loop
.endproc

.proc draw_intro
    jsr screen_off
    jsr set_palette
    jsr clear_screen
    show ROW_TITLE, COLUMN_LEFT, title
    show ROW_FIRST, COLUMN_LEFT, step_connect
    show ROW_FIRST + 1, COLUMN_LEFT, step_insert
    show ROW_FIRST + 2, COLUMN_LEFT, step_press
    show ROW_FIRST + 4, COLUMN_LEFT, explain_first
    show ROW_FIRST + 5, COLUMN_LEFT, explain_second
    jmp screen_on
.endproc

.proc draw_measuring
    jsr screen_off
    jsr clear_screen
    show ROW_TITLE, COLUMN_LEFT, title
    show ROW_FIRST, COLUMN_LEFT, measuring
    jmp screen_on
.endproc

.proc draw_results
    jsr compute_speed
    php
    jsr screen_off
    jsr clear_screen
    show ROW_TITLE, COLUMN_LEFT, title
    plp
    bcs nothing
    jsr draw_measurement
    jmp footer
nothing:
    show ROW_FIRST, COLUMN_LEFT, nothing_timed
footer:
    jsr draw_disk_notes
    show ROW_AGAIN, COLUMN_LEFT, press_again
    jmp screen_on
.endproc

.proc draw_measurement
    show ROW_CYCLES, COLUMN_LEFT, label_cycles
    ldx #ROW_CYCLES
    ldy #COLUMN_VALUE
    jsr locate
    lda cycles_x100
    sta value
    lda cycles_x100 + 1
    sta value + 1
    lda #TWO_DECIMALS
    jsr print_number
    show ROW_TARGET, COLUMN_LEFT, label_target
    ldx #ROW_TARGET
    ldy #COLUMN_VALUE
    jsr locate
    lda #<NOMINAL_CYCLES_X100
    sta value
    lda #>NOMINAL_CYCLES_X100
    sta value + 1
    lda #TWO_DECIMALS
    jsr print_number
    jsr draw_speed
    jsr draw_bytes
    jsr draw_bands
    jmp draw_advice
.endproc

.proc draw_speed
    show ROW_SPEED, COLUMN_LEFT, label_speed
    ldx #ROW_SPEED
    ldy #COLUMN_VALUE - 1
    jsr locate
    sec
    lda speed_x10000
    sbc #<RATIO_ONE
    sta value
    lda speed_x10000 + 1
    sbc #>RATIO_ONE
    sta value + 1
    lda #TWO_DECIMALS
    jsr print_signed
    lda #'%'
    sta PPU_DATA
    rts
.endproc

.proc draw_bytes
    show ROW_BYTES, COLUMN_LEFT, label_bytes
    ldx #ROW_BYTES
    ldy #COLUMN_VALUE
    jsr locate
    lda intervals
    sta value
    lda intervals + 1
    sta value + 1
    lda #NO_DECIMALS
    jmp print_number
.endproc

.proc draw_bands
    show ROW_COARSE, COLUMN_LEFT, label_coarse
    lda #<COARSE_FAST_LIMIT
    ldx #>COARSE_FAST_LIMIT
    ldy #<COARSE_SLOW_LIMIT
    jsr set_limits
    lda #>COARSE_SLOW_LIMIT
    ldx #ROW_COARSE
    jsr draw_verdict
    show ROW_FINE, COLUMN_LEFT, label_fine
    lda #<FINE_FAST_LIMIT
    ldx #>FINE_FAST_LIMIT
    ldy #<FINE_SLOW_LIMIT
    jsr set_limits
    lda #>FINE_SLOW_LIMIT
    ldx #ROW_FINE
    jsr draw_verdict
    show ROW_ULTRA, COLUMN_LEFT, label_ultra
    lda #<ULTRA_FAST_LIMIT
    ldx #>ULTRA_FAST_LIMIT
    ldy #<ULTRA_SLOW_LIMIT
    jsr set_limits
    lda #>ULTRA_SLOW_LIMIT
    ldx #ROW_ULTRA
    jsr draw_verdict
    jmp update_streak
.endproc

.proc set_limits
    sta lower_limit
    stx lower_limit + 1
    sty upper_limit
    rts
.endproc

.proc draw_verdict
    sta upper_limit + 1
    ldy #COLUMN_VERDICT
    jsr locate
    jsr within_limits
    bcc fail
    lda #<verdict_pass
    ldx #>verdict_pass
    jmp print_label
fail:
    lda #<verdict_fail
    ldx #>verdict_fail
    jmp print_label
.endproc

.proc within_limits
    lda cycles_x100
    cmp lower_limit
    lda cycles_x100 + 1
    sbc lower_limit + 1
    bcc outside
    lda upper_limit
    cmp cycles_x100
    lda upper_limit + 1
    sbc cycles_x100 + 1
    bcc outside
    sec
    rts
outside:
    clc
    rts
.endproc

.proc print_label
    sta text
    stx text + 1
    jmp print_text
.endproc

.proc update_streak
    jsr within_limits
    bcs passed
    lda #0
    sta ultra_streak
    rts
passed:
    inc ultra_streak
    rts
.endproc

.proc draw_advice
    ldx #ROW_ADVICE
    ldy #COLUMN_LEFT
    jsr locate
    lda ultra_streak
    bne hold
    lda cycles_x100
    cmp #<NOMINAL_CYCLES_X100
    lda cycles_x100 + 1
    sbc #>NOMINAL_CYCLES_X100
    bcs raise
    lda #<advice_lower
    ldx #>advice_lower
    jmp print_label
raise:
    lda #<advice_raise
    ldx #>advice_raise
    jmp print_label
hold:
    lda #<advice_hold
    ldx #>advice_hold
    jsr print_label
    show ROW_STREAK, COLUMN_LEFT, label_streak
    lda ultra_streak
    sta value
    lda #0
    sta value + 1
    lda #NO_DECIMALS
    jmp print_number
.endproc

.proc draw_disk_notes
    lda rewrite_count
    beq error
    show ROW_WARNING, COLUMN_LEFT, warning_rewritten
error:
    lda disk_error
    beq done
    show ROW_ERROR, COLUMN_LEFT, label_error
    lda disk_error
    jsr print_hex
done:
    rts
.endproc

.proc wait_for_a
release:
    jsr read_buttons
    and #BUTTON_A
    bne release
press:
    jsr read_buttons
    and #BUTTON_A
    beq press
    rts
.endproc

.proc read_buttons
    lda #1
    sta JOYPAD_PORT
    lda #0
    sta JOYPAD_PORT
    ldx #8
next:
    lda JOYPAD_PORT
    lsr a
    rol buttons
    dex
    bne next
    lda buttons
    rts
.endproc

.segment "VECTORS"
.addr ignore_interrupt, ignore_interrupt, license_bypass, reset, ignore_interrupt

.segment "BOOT"
.byte LICENSE_BYPASS_CTRL
