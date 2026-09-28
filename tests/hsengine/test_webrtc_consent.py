"""ICE consent closes a dead path, not a call that is still sending media."""

from hsengine.engine.webrtc_consent import consent_should_close


def test_a_short_stun_gap_does_not_hang_up() -> None:
    assert consent_should_close(failures=2, failed_for_s=10.0, media_age_s=None) is False


def test_thirty_seconds_without_media_hangs_up() -> None:
    assert consent_should_close(failures=6, failed_for_s=30.0, media_age_s=None) is True
    assert consent_should_close(failures=6, failed_for_s=30.0, media_age_s=40.0) is True


def test_inbound_media_keeps_the_call() -> None:
    assert consent_should_close(failures=8, failed_for_s=40.0, media_age_s=1.0) is False
