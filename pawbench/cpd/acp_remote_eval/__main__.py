# -*- coding: utf-8 -*-
"""``python -m pawbench.cpd.acp_remote_eval --config <file>``.

The command the README, the example config and the service docstrings all
promise.  It only parses argv and starts the loop; the wiring is
:func:`.service.daemon.build_service`.
"""

from __future__ import annotations

import sys

from .service.daemon import main

if __name__ == "__main__":
    sys.exit(main())
