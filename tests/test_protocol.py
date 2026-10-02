"""Golden packets taken from the working ESPHome implementation."""

import pytest
from cosori_kettle_ble.protocol import (
    CosoriProtocol,
    parse_registration_handshake,
    validate_registration_packets,
)

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


def test_custom_mode_setpoint_matches_reference_bytes():
    """Every non-boil setpoint uses MODE_CUSTOM, so pin its own golden packet."""
    assert (
        CosoriProtocol().build_setpoint(176).hex() == "a522010900c600f0a30006b001100e"
    )


@pytest.mark.parametrize("temp_f", [103, 213, 0, 1000])
def test_setpoint_outside_the_wire_range_is_rejected(temp_f):
    with pytest.raises(ValueError, match="Setpoint must be between"):
        CosoriProtocol().build_setpoint(temp_f)


def test_default_registration_is_a_valid_handshake():
    """The default registration is fragmented, so it is validated assembled."""
    validate_registration_packets(CosoriProtocol.build_hello_min())


def test_handshake_may_not_command_the_heating_element():
    """A captured control frame must never be accepted as a registration."""
    registration = b"".join(CosoriProtocol.build_hello_min())
    for frame in (
        CosoriProtocol().build_setpoint(212),
        CosoriProtocol().build_hello5(),
        CosoriProtocol().build_ctrl(),
        CosoriProtocol().build_f4(),
    ):
        with pytest.raises(ValueError, match="heating element"):
            validate_registration_packets([registration, frame])


@pytest.mark.parametrize(
    "packets",
    [
        [b"first", b"second", b"third"],
        [b""],
        [b"".join(CosoriProtocol.build_hello_min()) * 7],
        [CosoriProtocol.build_hello_min()[0]],
        [CosoriProtocol().build_poll()[:5]],
    ],
)
def test_malformed_handshake_is_rejected(packets):
    with pytest.raises(ValueError):
        validate_registration_packets(packets)


@pytest.mark.parametrize(
    "values",
    [
        42,
        [None],
        [42],
        [b"a522"],
        "a5220024008a0081d10036343238376139313765",
    ],
)
def test_handshake_of_the_wrong_kind_is_a_value_error(values):
    """A corrupted entry must fail as a validation error, never a crash."""
    with pytest.raises(ValueError, match="sequence of hexadecimal strings"):
        parse_registration_handshake(values)


def test_status_sequence_zero_is_not_treated_as_no_status():
    """A legitimate status sequence of zero must survive later rx frames."""
    protocol = CosoriProtocol()
    zero_seq = bytearray(ON_BASE)
    zero_seq[2] = 0
    zero_seq[5] = CosoriProtocol._calculate_checksum(bytes(zero_seq[:5] + zero_seq[6:]))
    protocol.parse_status(bytes(zero_seq))
    protocol.parse_status(bytes.fromhex("a5225e04005600404000"))
    assert protocol.build_ctrl()[2] == 0


@pytest.mark.parametrize(
    ("reading", "accepted"), [(39, False), (40, True), (230, True), (231, False)]
)
def test_water_reading_plausibility_boundaries(reading, accepted):
    """Corrupt-frame rejection must apply exactly outside 40-230F."""
    packet = bytearray(ON_BASE)
    packet[13] = reading
    packet[5] = CosoriProtocol._calculate_checksum(bytes(packet[:5] + packet[6:]))
    status = CosoriProtocol().parse_status(bytes(packet))
    assert (status is not None) is accepted


def test_only_extended_frames_carry_base_information():
    protocol = CosoriProtocol()
    assert protocol.parse_status(ON_BASE).includes_base is True
    protocol.parse_status(OFF_BASE)
    assert protocol.parse_status(COMPACT).includes_base is False
