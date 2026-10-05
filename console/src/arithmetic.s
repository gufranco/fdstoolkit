.include "speed_limits.inc"

.export compute_speed
.exportzp cycles_x100, speed_x10000, intervals
.importzp iterations, timed_bytes, timed_blocks

ITERATION_CYCLES_SHIFT = 4
WRAP_PENALTY = 7
ARRIVAL_CYCLES = 55
CENTI = 100

.segment "ZEROPAGE"
total: .res 4
operand: .res 4
multiplier: .res 1
factor: .res 4
divisor: .res 2
remainder: .res 3
intervals: .res 2
cycles_x100: .res 2
speed_x10000: .res 2

.segment "CODE"
.proc compute_speed
    sec
    lda timed_bytes
    sbc timed_blocks
    sta intervals
    lda timed_bytes + 1
    sbc timed_blocks + 1
    sta intervals + 1
    ora intervals
    bne measured
    sec
    rts
measured:
    jsr loop_cycles
    jsr add_wrap_penalties
    jsr add_arrival_cycles
    lda #CENTI
    jsr multiply_total
    lda intervals
    sta divisor
    lda intervals + 1
    sta divisor + 1
    jsr divide_total
    lda total
    sta cycles_x100
    lda total + 1
    sta cycles_x100 + 1
    jsr speed_ratio
    clc
    rts
.endproc

.proc loop_cycles
    lda iterations
    sta total
    lda iterations + 1
    sta total + 1
    lda iterations + 2
    sta total + 2
    lda #0
    sta total + 3
    ldx #ITERATION_CYCLES_SHIFT
shift:
    asl total
    rol total + 1
    rol total + 2
    rol total + 3
    dex
    bne shift
    rts
.endproc

.proc add_wrap_penalties
    lda iterations + 1
    sta operand
    lda iterations + 2
    sta operand + 1
    lda #0
    sta operand + 2
    sta operand + 3
    lda #WRAP_PENALTY
    jsr multiply_operand
    jsr add_operand
    lda iterations + 2
    sta operand
    lda #0
    sta operand + 1
    sta operand + 2
    sta operand + 3
    lda #WRAP_PENALTY
    jsr multiply_operand
    jmp add_operand
.endproc

.proc add_arrival_cycles
    lda intervals
    sta operand
    lda intervals + 1
    sta operand + 1
    lda #0
    sta operand + 2
    sta operand + 3
    lda #ARRIVAL_CYCLES
    jsr multiply_operand
    jmp add_operand
.endproc

.proc speed_ratio
    lda #<.loword(SPEED_RATIO_NUMERATOR)
    sta total
    lda #>.loword(SPEED_RATIO_NUMERATOR)
    sta total + 1
    lda #<.hiword(SPEED_RATIO_NUMERATOR)
    sta total + 2
    lda #>.hiword(SPEED_RATIO_NUMERATOR)
    sta total + 3
    lda cycles_x100
    sta divisor
    lda cycles_x100 + 1
    sta divisor + 1
    jsr divide_total
    lda total
    sta speed_x10000
    lda total + 1
    sta speed_x10000 + 1
    rts
.endproc

.proc add_operand
    clc
    ldx #0
    ldy #4
add_byte:
    lda total, x
    adc operand, x
    sta total, x
    inx
    dey
    bne add_byte
    rts
.endproc

.proc multiply_operand
    sta multiplier
    lda operand
    pha
    lda operand + 1
    pha
    lda operand + 2
    pha
    lda operand + 3
    pha
    lda #0
    sta operand
    sta operand + 1
    sta operand + 2
    sta operand + 3
    pla
    sta factor + 3
    pla
    sta factor + 2
    pla
    sta factor + 1
    pla
    sta factor
    ldx #8
next_bit:
    asl operand
    rol operand + 1
    rol operand + 2
    rol operand + 3
    asl multiplier
    bcc skip_add
    clc
    lda operand
    adc factor
    sta operand
    lda operand + 1
    adc factor + 1
    sta operand + 1
    lda operand + 2
    adc factor + 2
    sta operand + 2
    lda operand + 3
    adc factor + 3
    sta operand + 3
skip_add:
    dex
    bne next_bit
    rts
.endproc

.proc multiply_total
    tay
    ldx #3
copy:
    lda total, x
    sta operand, x
    dex
    bpl copy
    tya
    jsr multiply_operand
    ldx #3
store:
    lda operand, x
    sta total, x
    dex
    bpl store
    rts
.endproc

.proc divide_total
    lda #0
    sta remainder
    sta remainder + 1
    sta remainder + 2
    ldx #32
next_bit:
    asl total
    rol total + 1
    rol total + 2
    rol total + 3
    rol remainder
    rol remainder + 1
    rol remainder + 2
    sec
    lda remainder
    sbc divisor
    tay
    lda remainder + 1
    sbc divisor + 1
    sta operand
    lda remainder + 2
    sbc #0
    bcc keep
    sta remainder + 2
    lda operand
    sta remainder + 1
    sty remainder
    inc total
keep:
    dex
    bne next_bit
    rts
.endproc

