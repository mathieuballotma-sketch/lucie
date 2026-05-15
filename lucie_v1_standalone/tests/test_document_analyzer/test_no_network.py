"""Garantit que `analyze_document()` ne fait AUCUN appel réseau.

Invariant Beaume : 100% local. Le test patch `socket.socket.connect` pour
lever une exception si jamais le code tentait d'établir une connexion
sortante pendant le parsing. Un seul appel = test red.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from lucie_v1_standalone.document_analyzer import analyze_document


class NetworkCalledError(AssertionError):
    """Levée si du code tente d'ouvrir un socket réseau pendant le test."""


def _blocking_socket_connect(*args, **kwargs):
    raise NetworkCalledError(
        f"socket.connect appelé pendant analyze_document : {args!r}"
    )


def test_no_network_call_during_analyze(monkeypatch, fixture_lic_eco_pdf):
    """Bloque socket.socket.connect — analyze_document doit passer sans souci."""
    monkeypatch.setattr(socket.socket, "connect", _blocking_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocking_socket_connect)

    result = asyncio.run(analyze_document(str(fixture_lic_eco_pdf)))

    assert result.subject_detected == "droit_social"
    # Pas de NetworkCalledError levée = aucun appel réseau pendant l'analyse.


def test_no_network_call_for_out_of_scope_pharma(monkeypatch, fixture_pharma_pdf):
    """Même contrôle réseau, mais sur un cas refusé (pharma) : le retriever
    n'est même pas appelé. On vérifie que rien d'autre ne sort non plus."""
    monkeypatch.setattr(socket.socket, "connect", _blocking_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocking_socket_connect)

    result = asyncio.run(analyze_document(str(fixture_pharma_pdf)))

    assert result.subject_detected is None
    assert result.refusal_reason is not None
