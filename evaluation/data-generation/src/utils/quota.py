"""The daily request budget (``config/settings.yaml``: ``rpd_limit``) as a clean stop, not a crash.

A stage that hits the budget keeps what it already wrote (every model
stage writes per item and resumes with ``--resume``), says how to continue,
and exits with ``EXIT_DAILY_LIMIT`` so ``run_all`` stops the pipeline
without a traceback.
"""
from __future__ import annotations

import functools
import sys
from typing import Callable

#: EX_TEMPFAIL: try again later.
EXIT_DAILY_LIMIT = 75


class DailyLimitReached(RuntimeError):
    """The configured requests-per-day budget is used up for today (UTC)."""

    def __init__(self, provider: str, limit: int):
        super().__init__(f"Configured {provider} daily request limit reached ({limit}); adjust config/settings.yaml")
        self.provider, self.limit = provider, limit


def advice(error: DailyLimitReached) -> str:
    return (f"{error.provider} daily budget of {error.limit} requests is used up for today (UTC). "
            "Progress is saved. Continue tomorrow with --resume, or raise "
            f"`{error.provider.lower()}.rpd_limit` in config/settings.yaml if your account allows more.")


def stop_on_daily_limit(main: Callable[[], None]) -> Callable[[], None]:
    """Wrap a stage's ``main``: on the daily budget, print the advice and exit ``EXIT_DAILY_LIMIT``."""

    @functools.wraps(main)
    def run() -> None:
        try:
            main()
        except DailyLimitReached as error:
            print(f"\nSTOPPED: {advice(error)}", flush=True)
            sys.exit(EXIT_DAILY_LIMIT)

    return run
