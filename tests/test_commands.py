from custom_components.ha_onecontrol.protocol.commands import CommandBuilder


def test_build_action_hbridge_encodes_open_close_stop() -> None:
    builder = CommandBuilder()

    open_command = builder.build_action_hbridge(1, 0x12, builder.HBRIDGE_OPEN)
    assert open_command[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x12,
        builder.HBRIDGE_OPEN_CMD,
    ])

    close_command = builder.build_action_hbridge(2, 0x34, builder.HBRIDGE_CLOSE)
    assert close_command[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        2,
        0x34,
        builder.HBRIDGE_CLOSE_CMD,
    ])

    stop_command = builder.build_action_hbridge(3, 0x56, builder.HBRIDGE_STOP)
    assert stop_command[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        3,
        0x56,
        builder.HBRIDGE_STOP_CMD,
    ])


def test_build_action_hbridge_advanced_commands() -> None:
    """Advanced H-Bridge commands (Clear Latch, Home Reset, Auto Open, Auto Close)."""
    builder = CommandBuilder()

    clear_latch = builder.build_action_hbridge(1, 0x0A, builder.HBRIDGE_CLEAR_LATCH)
    assert clear_latch[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0A,
        builder.HBRIDGE_CLEAR_LATCH_CMD,
    ])

    home_reset = builder.build_action_hbridge(1, 0x0A, builder.HBRIDGE_HOME_RESET)
    assert home_reset[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0A,
        builder.HBRIDGE_HOME_RESET_CMD,
    ])

    auto_open = builder.build_action_hbridge(2, 0x0B, builder.HBRIDGE_AUTO_OPEN)
    assert auto_open[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        2,
        0x0B,
        builder.HBRIDGE_AUTO_OPEN_CMD,
    ])

    auto_close = builder.build_action_hbridge(2, 0x0B, builder.HBRIDGE_AUTO_CLOSE)
    assert auto_close[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        2,
        0x0B,
        builder.HBRIDGE_AUTO_CLOSE_CMD,
    ])


def test_build_action_hbridge_raw_command_bytes() -> None:
    """Raw command bytes (0x83-0x86) pass through unchanged."""
    builder = CommandBuilder()

    # Clear Latch via raw byte
    cmd = builder.build_action_hbridge(1, 0x0C, 0x83)
    assert cmd[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0C,
        0x83,
    ])

    # Home Reset via raw byte
    cmd = builder.build_action_hbridge(1, 0x0C, 0x84)
    assert cmd[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0C,
        0x84,
    ])

    # Auto Open via raw byte
    cmd = builder.build_action_hbridge(1, 0x0C, 0x85)
    assert cmd[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0C,
        0x85,
    ])

    # Auto Close via raw byte
    cmd = builder.build_action_hbridge(1, 0x0C, 0x86)
    assert cmd[-4:] == bytes([
        builder.CMD_ACTION_HBRIDGE,
        1,
        0x0C,
        0x86,
    ])


def test_hbridge_command_byte_mapping() -> None:
    """_hbridge_command_byte maps logical directions and passes through raw bytes."""
    builder = CommandBuilder()

    # Logical directions → command bytes
    assert builder._hbridge_command_byte(builder.HBRIDGE_STOP) == builder.HBRIDGE_STOP_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_OPEN) == builder.HBRIDGE_OPEN_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_CLOSE) == builder.HBRIDGE_CLOSE_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_CLEAR_LATCH) == builder.HBRIDGE_CLEAR_LATCH_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_HOME_RESET) == builder.HBRIDGE_HOME_RESET_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_AUTO_OPEN) == builder.HBRIDGE_AUTO_OPEN_CMD
    assert builder._hbridge_command_byte(builder.HBRIDGE_AUTO_CLOSE) == builder.HBRIDGE_AUTO_CLOSE_CMD

    # Raw command bytes pass through unchanged (high bit set)
    assert builder._hbridge_command_byte(0x80) == 0x80
    assert builder._hbridge_command_byte(0x83) == 0x83
    assert builder._hbridge_command_byte(0x86) == 0x86

    # Unknown direction values fall back to STOP
    assert builder._hbridge_command_byte(0x07) == builder.HBRIDGE_STOP_CMD
    assert builder._hbridge_command_byte(0xFF) == 0xFF  # high bit set → passthrough
