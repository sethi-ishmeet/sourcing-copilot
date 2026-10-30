"""The pretend LinkedIn never delivers the same message twice, and its failure switches
behave as documented."""

from __future__ import annotations

import pytest

from sourcing_copilot.copilot.linkedin import PretendLinkedIn, SendFailed


def test_same_key_twice_returns_the_original_receipt():
    linkedin = PretendLinkedIn()
    first = linkedin.send("cand_001", "hello", idempotency_key="run_1")
    second = linkedin.send("cand_001", "hello", idempotency_key="run_1")
    assert first.message_id == second.message_id
    assert linkedin.sent_count == 1
    assert len(linkedin.attempts) == 2


def test_different_keys_are_different_messages():
    linkedin = PretendLinkedIn()
    linkedin.send("cand_001", "hello", idempotency_key="run_1")
    linkedin.send("cand_001", "hello", idempotency_key="run_2")
    assert linkedin.sent_count == 2


def test_dropped_connection_after_accepting_does_not_duplicate_on_retry():
    linkedin = PretendLinkedIn(fail_times=1)
    with pytest.raises(SendFailed, match="connection dropped"):
        linkedin.send("cand_001", "hello", idempotency_key="run_1")
    receipt = linkedin.send("cand_001", "hello", idempotency_key="run_1")
    assert linkedin.sent_count == 1
    assert receipt.attempts == 1  # the receipt is from the first, accepted attempt


def test_when_down_nothing_is_accepted():
    linkedin = PretendLinkedIn(down=True)
    for _ in range(3):
        with pytest.raises(SendFailed, match="not responding"):
            linkedin.send("cand_001", "hello", idempotency_key="run_1")
    assert linkedin.sent_count == 0
    assert len(linkedin.attempts) == 3
