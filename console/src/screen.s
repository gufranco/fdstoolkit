.include "hardware.inc"

.export screen_off, screen_on, clear_screen, set_palette, locate, print_text
.export print_number, print_signed, print_hex
.exportzp text, value

NAMETABLE_HIGH = $20
ROW_SHIFT = 5
NAMETABLE_PAGES = 4
PALETTE_HIGH = $3F
BACKGROUND_BLACK = $0F
TEXT_WHITE = $30
SHOW_BACKGROUND = %00001010
DIGITS = 5
DECIMAL_POINT_AFTER = 3
LEADING_DIGITS = 2
ASCII_ZERO = '0'
ASCII_SPACE = ' '
ASCII_A_MINUS_TEN = 'A' - 10
NIBBLE = $0F

.segment "ZEROPAGE"
text: .res 2
value: .res 2
address: .res 2
digit_index: .res 1
shown: .res 1
decimals: .res 1

.segment "RODATA"
powers_low: .byte <10000, <1000, <100, <10, <1
powers_high: .byte >10000, >1000, >100, >10, >1

.segment "CODE"
.proc wait_vblank
    bit PPU_STATUS
wait:
    bit PPU_STATUS
    bpl wait
    rts
.endproc

.proc screen_off
    jsr wait_vblank
    lda #0
    sta PPU_MASK
    rts
.endproc

.proc screen_on
    jsr wait_vblank
    lda #0
    sta PPU_SCROLL
    sta PPU_SCROLL
    sta PPU_CTRL
    lda #SHOW_BACKGROUND
    sta PPU_MASK
    rts
.endproc

.proc set_palette
    lda PPU_STATUS
    lda #PALETTE_HIGH
    sta PPU_ADDR
    lda #0
    sta PPU_ADDR
    lda #BACKGROUND_BLACK
    sta PPU_DATA
    lda #TEXT_WHITE
    sta PPU_DATA
    sta PPU_DATA
    sta PPU_DATA
    rts
.endproc

.proc clear_screen
    lda PPU_STATUS
    lda #NAMETABLE_HIGH
    sta PPU_ADDR
    lda #0
    sta PPU_ADDR
    ldy #NAMETABLE_PAGES
    ldx #0
    lda #ASCII_SPACE
fill:
    sta PPU_DATA
    inx
    bne fill
    dey
    bne fill
    rts
.endproc

.proc locate
    stx address
    lda #0
    sta address + 1
    ldx #ROW_SHIFT
shift:
    asl address
    rol address + 1
    dex
    bne shift
    tya
    clc
    adc address
    sta address
    lda address + 1
    adc #NAMETABLE_HIGH
    sta address + 1
    lda PPU_STATUS
    lda address + 1
    sta PPU_ADDR
    lda address
    sta PPU_ADDR
    rts
.endproc

.proc print_text
    ldy #0
next:
    lda (text), y
    beq done
    sta PPU_DATA
    iny
    bne next
done:
    rts
.endproc

.proc print_number
    sta decimals
    lda #0
    sta shown
    sta digit_index
next_digit:
    jsr point_if_due
    ldy #ASCII_ZERO
    ldx digit_index
subtract:
    lda value
    sec
    sbc powers_low, x
    pha
    lda value + 1
    sbc powers_high, x
    bcc digit_found
    sta value + 1
    pla
    sta value
    iny
    jmp subtract
digit_found:
    pla
    tya
    jsr emit_digit
    inc digit_index
    lda digit_index
    cmp #DIGITS
    bne next_digit
    rts
.endproc

.proc point_if_due
    lda decimals
    beq done
    lda digit_index
    cmp #DECIMAL_POINT_AFTER
    bne done
    lda #'.'
    sta PPU_DATA
    sta shown
done:
    rts
.endproc

.proc emit_digit
    cmp #ASCII_ZERO
    bne visible
    ldx shown
    bne visible
    ldx digit_index
    cpx #DIGITS - 1
    beq visible
    ldx decimals
    beq blank
    ldx digit_index
    cpx #LEADING_DIGITS
    bcs visible
blank:
    lda #ASCII_SPACE
    sta PPU_DATA
    rts
visible:
    sta PPU_DATA
    sta shown
    rts
.endproc

.proc print_signed
    sta decimals
    lda value + 1
    bpl positive
    lda #0
    sec
    sbc value
    sta value
    lda #0
    sbc value + 1
    sta value + 1
    lda #'-'
    bne sign
positive:
    lda #'+'
sign:
    sta PPU_DATA
    lda decimals
    jmp print_number
.endproc

.proc print_hex
    pha
    lsr a
    lsr a
    lsr a
    lsr a
    jsr hex_digit
    pla
    and #NIBBLE
    jmp hex_digit
.endproc

.proc hex_digit
    cmp #10
    bcs letter
    adc #ASCII_ZERO
    sta PPU_DATA
    rts
letter:
    adc #ASCII_A_MINUS_TEN - 1
    sta PPU_DATA
    rts
.endproc
