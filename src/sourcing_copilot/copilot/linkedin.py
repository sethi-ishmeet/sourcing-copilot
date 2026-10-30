"""A pretend LinkedIn. It remembers every message by idempotency key so a retry after a
dropped connection never sends the same message twice. Failure switches let tests and
demos make it misbehave on purpose."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from .schemas import SendReceipt


class SendFailed(Exception):
    """The send did not complete. The caller may retry with the same idempotency key."""


class PretendLinkedIn:
    def __init__(
        self,
        fail_times: int = 0,
        down: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        # fail_times: accept the message, then drop the connection N times before the
        # caller sees a success. This is the nasty case: the message went out but the
        # caller does not know. down: refuse every call without accepting anything.
        self.fail_times = fail_times
        self.down = down
        self._now = now or (lambda: datetime.now(UTC))
        self.delivered: dict[str, SendReceipt] = {}  # idempotency_key -> receipt
        self.attempts: list[dict] = []

    @property
    def sent_count(self) -> int:
        return len(self.delivered)

    def send(self, candidate_id: str, message: str, idempotency_key: str) -> SendReceipt:
        attempt = {"candidate_id": candidate_id, "key": idempotency_key, "at": self._now()}
        self.attempts.append(attempt)

        if self.down:
            raise SendFailed("LinkedIn is not responding")

        if idempotency_key in self.delivered:
            # Already delivered. Return the original receipt instead of sending again.
            return self.delivered[idempotency_key]

        receipt = SendReceipt(
            message_id=f"msg_{uuid4().hex[:10]}",
            candidate_id=candidate_id,
            sent_at=self._now().isoformat(timespec="seconds"),
            attempts=len([a for a in self.attempts if a["key"] == idempotency_key]),
        )
        self.delivered[idempotency_key] = receipt

        if self.fail_times > 0:
            self.fail_times -= 1
            raise SendFailed("connection dropped after the message was accepted")
        return receipt
