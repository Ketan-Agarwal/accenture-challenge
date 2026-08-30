from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
from datetime import date

import pytest

import app.embeddings as embeddings
from app.checks import _compute_refund_eligibility


def test_embeddings_are_offline_safe_and_attempted_once(monkeypatch):
    monkeypatch.setenv("CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS", "1")
    monkeypatch.delenv("CONTROLPLANE_ALLOW_MODEL_DOWNLOAD", raising=False)
    monkeypatch.setattr(embeddings, "_MODEL", None)
    monkeypatch.setattr(embeddings, "_LOAD_ATTEMPTED", False)

    real_import = builtins.__import__
    attempts = 0

    def guarded_import(name, *args, **kwargs):
        nonlocal attempts
        if name == "sentence_transformers":
            attempts += 1
            raise ImportError("optional dependency deliberately unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert embeddings.embeddings_available() is False
    assert embeddings.embeddings_available() is False
    assert attempts == 1


def test_embed_requires_an_explicitly_available_model(monkeypatch):
    monkeypatch.delenv("CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(embeddings, "_MODEL", None)
    monkeypatch.setattr(embeddings, "_LOAD_ATTEMPTED", False)
    with pytest.raises(RuntimeError, match="not enabled"):
        embeddings.embed(["hello"])


def test_embedding_model_is_local_only_without_download_opt_in(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, *, local_files_only: bool):
            captured["model_name"] = model_name
            captured["local_files_only"] = local_files_only

    monkeypatch.setenv("CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS", "1")
    monkeypatch.delenv("CONTROLPLANE_ALLOW_MODEL_DOWNLOAD", raising=False)
    monkeypatch.setattr(embeddings, "_MODEL", None)
    monkeypatch.setattr(embeddings, "_LOAD_ATTEMPTED", False)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    assert embeddings.embeddings_available() is True
    assert captured == {
        "model_name": "all-MiniLM-L6-v2",
        "local_files_only": True,
    }


def test_refund_window_uses_an_explicit_reference_date():
    order = {
        "order_total_inr": "4499.00",
        "fulfilment_issue": "change_of_mind",
        "status": "delivered",
        "order_date": "2026-08-28",
    }
    assert _compute_refund_eligibility(order, today=date(2026, 8, 30))[1] == "RP-03"
    assert _compute_refund_eligibility(order, today=date(2026, 9, 10))[1] == "RP-03:EXPIRED"
