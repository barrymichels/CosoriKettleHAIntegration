"""Golden packets taken from the working ESPHome implementation."""

from cosori_kettle_ble.protocol import CosoriProtocol

ON_BASE = bytes.fromhex(
    "a512191d0010014040000000d45c8c00000000000000003c690000000001100e000001"
)
OFF_BASE = bytes.fromhex(
    "a5121c1d000c014040000000d45c8c00000000000100003c690000000001100e000001"
)
COMPACT = bytes.fromhex("a5225e0c0083014140000104d4648c000000")


def test_registration_and_commands_match_esphome():
    protocol = CosoriProtocol()
    assert protocol.build_hello_min() == [
        bytes.fromhex("a5220024008a0081d10036343238376139313765"),
        bytes.fromhex("3734366130373331313636623736663433643563"),
        bytes.fromhex("6262"),
    ]
    assert protocol.build_poll().hex() == "a522010400b300404000"
    assert protocol.build_hello5().hex() == "a5220208007a00f2a3000001100e"
    assert protocol.build_setpoint(212).hex() == "a522030900a200f0a30004d401100e"


def test_status_matches_real_capture():
    status = CosoriProtocol().parse_status(ON_BASE)
    assert status is not None
    assert status.current_temp_f == 92
    assert status.target_temp_f == 212
    assert status.on_base is True
    assert status.heating is False


def test_compact_preserves_off_base():
    protocol = CosoriProtocol()
    protocol.parse_status(OFF_BASE)
    status = protocol.parse_status(COMPACT)
    assert status is not None
    assert status.current_temp_f == 100
    assert status.target_temp_f == 212
    assert status.heating is True
    assert status.on_base is False


def test_fragmentation_and_multiple_frames():
    protocol = CosoriProtocol()
    assert protocol.feed(b"noise" + ON_BASE[:20]) == []
    statuses = protocol.feed(ON_BASE[20:] + OFF_BASE + COMPACT)
    assert [status.on_base for status in statuses] == [True, False, False]
    assert statuses[-1].current_temp_f == 100


def test_checksum_errors_and_bad_lengths_do_not_block_following_frames():
    bad = bytearray(ON_BASE)
    bad[7] ^= 0xFF
    protocol = CosoriProtocol()
    assert protocol.feed(b"\xa5\x12\x00\xff\xff\x00" + bad + ON_BASE) == [
        CosoriProtocol().parse_status(ON_BASE)
    ]


def test_non_status_frame_does_not_replace_status_sequence():
    protocol = CosoriProtocol()
    protocol.parse_status(ON_BASE)
    protocol.parse_status(bytes.fromhex("a5225e04005600404000"))
    assert protocol.build_ctrl().hex() == "a512190400aa00414000"


def test_sequences_wrap_like_esphome():
    protocol = CosoriProtocol()
    sequences = [protocol.build_poll()[2] for _ in range(257)]
    assert sequences[:2] == [1, 2]
    assert sequences[-3:] == [255, 0, 1]


def test_setpoint_outside_the_command_range_is_not_a_target():
    """A setpoint the integration could never write must not become its target."""
    packet = bytearray(ON_BASE)
    packet[12] = 80
    packet[5] = CosoriProtocol._calculate_checksum(bytes(packet[:5] + packet[6:]))
    status = CosoriProtocol().parse_status(bytes(packet))
    assert status is not None
    assert status.target_temp_f is None
    assert status.current_temp_f == 92
    assert status.on_base is True
