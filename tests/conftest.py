import sys
from pathlib import Path

import pytest

# The HA test plugin ships its own custom_components package; add ours to it.
import custom_components

custom_components.__path__.append(str(Path(__file__).parents[1] / "custom_components"))

if sys.platform == "win32":
    # asyncio on Windows needs a loopback socket pair; the HA plugin blocks all sockets.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
