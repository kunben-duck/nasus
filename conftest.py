from __future__ import annotations

import os
import tempfile


# Establish one isolated local state root before pytest imports application
# modules. Individual test modules must not redirect persistence after the
# SQLAlchemy engine has already been constructed.
os.environ.setdefault("NASUS_STATE_DIR", tempfile.mkdtemp(prefix="nasus-pytest-"))
os.environ.setdefault("NASUS_RUNNER_MODE", "protocol_stub")
