.include "hardware.inc"

.export measure_speed
.exportzp iterations, timed_bytes, timed_blocks, rewrite_count

.segment "ZEROPAGE"
iterations: .res 3
timed_bytes: .res 2
timed_blocks: .res 2
remaining: .res 2
files_left: .res 1
rewrite_count: .res 1

.segment "BSS"
disk_info: .res DISK_INFO_BYTES + 1
file_header: .res FILE_HEADER_BYTES + 1

.segment "TIMED"
time_until_done:
    lda FDS_DISK_STATUS
    and #BYTE_READY
    bne byte_arrived
    inc iterations
    bne time_until_done
    inc iterations + 1
    bne time_until_done
    inc iterations + 2
    jmp time_until_done
byte_arrived:
    lda FDS_DATA_READ
    inc timed_bytes
    bne timed_without_carry
    inc timed_bytes + 1
    jmp timed_counted
timed_without_carry:
    nop
    nop
    lda timed_bytes
timed_counted:
    lda remaining
    bne remaining_without_borrow
    dec remaining + 1
    jmp remaining_borrowed
remaining_without_borrow:
    nop
    nop
    lda remaining
remaining_borrowed:
    dec remaining
    lda remaining
    ora remaining + 1
    bne time_until_done
    rts
timed_loop_end:
.assert >time_until_done = >timed_loop_end, error, "the timed loop must stay in one page"

.segment "CODE"
.proc measure_speed
    tsx
    stx BIOS_ERROR_STACK
    jsr clear_totals
    jsr BIOS_WAIT_FOR_READY
    ldy #FIRST_GAP_DELAY_LONG
    jsr BIOS_DELAY
    ldy #FIRST_GAP_DELAY_REST
    jsr BIOS_DELAY
    jsr read_disk_info
    jsr read_file_amount
    lda files_left
    beq finished
next_file:
    jsr read_file_header
    jsr time_file_data
    dec files_left
    bne next_file
finished:
    jsr stop_motor
    lda #0
    rts
.endproc

.proc clear_totals
    lda #0
    sta iterations
    sta iterations + 1
    sta iterations + 2
    sta timed_bytes
    sta timed_bytes + 1
    sta timed_blocks
    sta timed_blocks + 1
    sta rewrite_count
    rts
.endproc

.proc read_disk_info
    lda #BLOCK_DISK_INFO
    jsr BIOS_CHECK_BLOCK_TYPE
    ldx #1
read_next:
    jsr BIOS_TRANSFER_BYTE
    sta disk_info, x
    inx
    cpx #DISK_INFO_BYTES + 1
    bne read_next
    lda disk_info + DISK_INFO_REWRITE_COUNT
    sta rewrite_count
    jmp BIOS_END_OF_BLOCK_READ
.endproc

.proc read_file_amount
    lda #BLOCK_FILE_AMOUNT
    jsr BIOS_CHECK_BLOCK_TYPE
    jsr BIOS_TRANSFER_BYTE
    sta files_left
    jmp BIOS_END_OF_BLOCK_READ
.endproc

.proc read_file_header
    lda #BLOCK_FILE_HEADER
    jsr BIOS_CHECK_BLOCK_TYPE
    ldx #1
read_next:
    jsr BIOS_TRANSFER_BYTE
    sta file_header, x
    inx
    cpx #FILE_HEADER_BYTES + 1
    bne read_next
    jmp BIOS_END_OF_BLOCK_READ
.endproc

.proc time_file_data
    lda file_header + HEADER_SIZE_LOW
    sta remaining
    lda file_header + HEADER_SIZE_HIGH
    sta remaining + 1
    lda #BLOCK_FILE_DATA
    jsr BIOS_CHECK_BLOCK_TYPE
    lda FDS_CONTROL_MIRROR
    and #<~CONTROL_IRQ
    sta FDS_CONTROL_MIRROR
    sta FDS_CONTROL
    jsr skip_short_block
    bcs data_read
    jsr wait_byte
    jsr decrement_remaining
    jsr wait_for_byte_ready
    inc timed_blocks
    bne entered
    inc timed_blocks + 1
entered:
    jsr byte_arrived
data_read:
    jmp finish_block
.endproc

.proc skip_short_block
    lda remaining + 1
    bne long_enough
    lda remaining
    cmp #2
    bcs long_enough
read_rest:
    lda remaining
    beq done
    jsr wait_byte
    jsr decrement_remaining
    jmp read_rest
done:
    sec
    rts
long_enough:
    clc
    rts
.endproc

.proc wait_for_byte_ready
poll:
    lda FDS_DISK_STATUS
    and #BYTE_READY
    beq poll
    rts
.endproc

.proc wait_byte
    jsr wait_for_byte_ready
    lda FDS_DATA_READ
    rts
.endproc

.proc decrement_remaining
    lda remaining
    bne no_borrow
    dec remaining + 1
no_borrow:
    dec remaining
    rts
.endproc

.proc finish_block
    jsr wait_byte
    lda FDS_DISK_STATUS
    and #END_OF_HEAD
    beq crc_next
    ldx #ERROR_END_OF_HEAD
    jmp BIOS_ERROR
crc_next:
    lda FDS_CONTROL_MIRROR
    ora #CONTROL_CRC
    sta FDS_CONTROL_MIRROR
    sta FDS_CONTROL
    jsr wait_byte
    lda FDS_DISK_STATUS
    and #CRC_FAILED
    beq crc_passed
    ldx #ERROR_CRC
    jmp BIOS_ERROR
crc_passed:
    lda FDS_CONTROL_MIRROR
    and #CONTROL_KEEP_AT_BLOCK_END
    ora #CONTROL_READ_IDLE
    sta FDS_CONTROL_MIRROR
    sta FDS_CONTROL
    rts
.endproc

.proc stop_motor
    lda FDS_CONTROL_MIRROR
    and #CONTROL_KEEP_MIRRORING
    ora #CONTROL_MOTOR_STOPPED
    sta FDS_CONTROL_MIRROR
    sta FDS_CONTROL
    rts
.endproc
