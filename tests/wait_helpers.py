"""Condition polling shared by asynchronous tests."""

import time


def wait_for(pred, timeout=10.0, what="condition", *, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(interval)
    raise AssertionError(f"{what} not reached")
