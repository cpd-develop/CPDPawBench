# -*- coding: utf-8 -*-
"""Fixtures for the remote-eval cases.

The store is the one thing every case needs and no case should configure: a
temporary file per test, opened and closed by the context manager the service
itself uses, so a leaked connection shows up as a failure here rather than as a
locked database three cases later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pawbench.cpd.acp_remote_eval.service.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    with Store(tmp_path / "state.db") as instance:
        yield instance
