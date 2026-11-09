import socket

import pytest

import pmsys


def test_version() -> None:
    assert pmsys.__version__ == "0.1.0"


def test_network_is_blocked() -> None:
    """Spec (a): tests unitarios con la red bloqueada."""
    with pytest.raises(RuntimeError, match=r"[Ss]ocket"):
        socket.create_connection(("example.com", 80), timeout=1)
