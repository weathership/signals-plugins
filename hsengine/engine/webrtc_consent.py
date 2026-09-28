"""Keep an AgentRTC peer up through a rough ICE consent check.

aioice counts every nominated pair and closes after six STUN misses with no
retransmission. A few lost packets, or a moment when the browser is busy,
then ends the call while audio is still flowing. One round is one miss.
Inbound media means the path is up.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

log = logging.getLogger("hsengine.engine.webrtc.consent")

# aioice sleeps ~5s between rounds. Six rounds is the RFC 7675 window.
CONSENT_ROUNDS = 6
MIN_FAIL_S = 25.0
# A frame in this window means the browser is still on the call.
MEDIA_GRACE_S = 15.0
_INSTALLED = False
_last_media = 0.0


def note_inbound_media() -> None:
    global _last_media
    _last_media = time.monotonic()


def media_age_s() -> float | None:
    if _last_media <= 0.0:
        return None
    return time.monotonic() - _last_media


def consent_should_close(
    *,
    failures: int,
    failed_for_s: float,
    media_age_s: float | None,
) -> bool:
    """True only after a stretch of STUN failure and no recent inbound media."""
    if failures < CONSENT_ROUNDS or failed_for_s < MIN_FAIL_S:
        return False
    if media_age_s is not None and media_age_s <= MEDIA_GRACE_S:
        return False
    return True


def install() -> None:
    """Replace aioice's consent loop. Idempotent. Call before a peer starts."""
    global _INSTALLED
    if _INSTALLED:
        return
    from aioice.ice import Connection
    import aioice.stun as stun

    async def query_consent(self: Connection) -> None:
        failures = 0
        first_fail: float | None = None
        while True:
            await asyncio.sleep(5.0 * (0.8 + 0.4 * random.random()))
            pairs = list(getattr(self, "_nominated", {}).values())
            if not pairs:
                continue
            ok = False
            for pair in pairs:
                request = self.build_request(pair, nominate=False)
                try:
                    await pair.protocol.request(
                        request,
                        pair.remote_addr,
                        integrity_key=self.remote_password.encode("utf8"),
                        retransmissions=2,
                    )
                    ok = True
                    break
                except stun.TransactionError:
                    continue
            if ok:
                failures = 0
                first_fail = None
                continue
            now = time.monotonic()
            failures += 1
            if first_fail is None:
                first_fail = now
            age = now - first_fail
            heard = media_age_s()
            if consent_should_close(
                failures=failures, failed_for_s=age, media_age_s=heard
            ):
                log.info(
                    "ice consent expired rounds=%s age=%.1fs media_age=%s",
                    failures,
                    age,
                    None if heard is None else round(heard, 1),
                )
                self._query_consent_task = None
                await self.close()
                return
            log.info(
                "ice consent miss rounds=%s age=%.1fs media_age=%s; keeping the call",
                failures,
                age,
                None if heard is None else round(heard, 1),
            )

    Connection.query_consent = query_consent  # type: ignore[method-assign]
    _INSTALLED = True
