"""Values the simulator suite shares between its modules.

A module of its own rather than a conftest import: pytest loads conftest files by path,
and this repository already has another ``conftest`` on the import path.
"""

from __future__ import annotations

from typing import Final

WEBHOOK_SECRET: Final = "order-simulator-test-secret"
"""The shared secret both sides of the suite sign and verify with. Test-only, generated
nowhere and committed here because it authenticates nothing outside this process."""
