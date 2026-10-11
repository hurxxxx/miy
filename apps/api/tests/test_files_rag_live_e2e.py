from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import pytest


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "files_rag_live_e2e.py"
    spec = importlib.util.spec_from_file_location("test_files_rag_live_e2e_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeLiveState:
    def __init__(self) -> None:
        self.admitted = set()
        self.metadata_version = 1
        self.partition_id = "partition-stable"
        self.corpus_id = "corpus-e2e"
        self.files: dict[str, dict[str, str]] = {}
        self.deleted = False


class _FakeLiveApi:
    def __init__(self, state: _FakeLiveState, *, principal: str) -> None:
        self.state = state
        self.principal = principal

    def identity(self):
        return {
            "id": f"id-{self.principal}",
            "system_roles": ["platform_admin"] if self.principal == "actor" else [],
        }

    def validate_acl_group(self, group_id):
        assert group_id == "e2e-group" and not self.state.admitted

    def replace_acl_group_members(self, group_id, user_ids):
        assert self.principal == "actor" and group_id == "e2e-group"
        self.state.admitted = set(user_ids)

    def assert_app_denied(self):
        assert self.principal != "actor" and f"id-{self.principal}" not in self.state.admitted

    def preflight(self) -> None:
        assert self.principal == "actor" or f"id-{self.principal}" in self.state.admitted

    def create_corpus(self, name: str):
        assert self.principal == "actor"
        assert "private" not in name
        return {
            "id": self.state.corpus_id,
            "access_scope_kind": "company",
            "retrieval_partition_id": self.state.partition_id,
            "metadata_version": 1,
        }

    def upload(self, corpus_id: str, canary):
        assert self.principal == "actor" and corpus_id == self.state.corpus_id
        file_id = f"file-{len(self.state.files) + 1}"
        self.state.files[file_id] = {
            "sha256": canary.content_sha256,
            "upload_name": canary.upload_name,
            "size_bytes": str(canary.size_bytes),
        }
        return {"id": file_id, "filename": canary.upload_name, "rag_status": "pending"}

    def wait_ready(self, file_ids, **_kwargs):
        assert set(file_ids) == set(self.state.files)
        return {file_id: "ready" for file_id in file_ids}

    def search(self, *, query: str, strategy: str, page: int, page_size: int):
        assert query and query not in {"private body", "alpha private evidence"}
        visible = self.principal == "actor" or f"id-{self.principal}" in self.state.admitted
        ids = sorted(self.state.files) if visible and not self.state.deleted else []
        start = (page - 1) * page_size
        methods = {
            "keyword": ["bm25"],
            "semantic": ["semantic", "vector", "dense_vector"],
            "hybrid": ["bm25", "semantic", "vector", "dense_vector", "rrf"],
        }[strategy]
        hits = [
            {
                "rank": index + 1,
                "file_id": file_id,
                "score": float(len(ids) - index),
                "methods": methods,
                "snippet": {
                    "text": "bounded safe snippet",
                    "highlights": ([{"start": 0, "end": 7}] if strategy == "keyword" else []),
                },
            }
            for index, file_id in enumerate(ids)
        ][start : start + page_size]
        return {
            "query": query,
            "strategy": strategy,
            "page": page,
            "page_size": page_size,
            "hits": hits,
            "has_more": start + page_size < len(ids),
            "max_ranked_results": 100,
            "latency_ms": 7,
            "trace_id": None,
        }

    def fresh_download(self, file_id: str):
        assert self.principal == "actor" or f"id-{self.principal}" in self.state.admitted
        row = self.state.files[file_id]
        return (
            f"http://127.0.0.1:8001/api/v1/content#grant=test-{self.state.metadata_version}",
            row["sha256"],
            int(row["size_bytes"]),
        )

    def assert_stale_download_denied(self, url: str) -> None:
        assert parse_qs(urlparse(url).fragment)["grant"]
        assert self.state.deleted or f"id-{self.principal}" not in self.state.admitted

    def bulk_delete(self, file_ids) -> None:
        assert set(file_ids) == set(self.state.files)
        self.state.deleted = True


class _FakeProjectionInspector:
    def __init__(self, state: _FakeLiveState) -> None:
        self.state = state

    def wait_projected(self, *, corpus_id: str, file_ids, **_kwargs):
        assert corpus_id == self.state.corpus_id
        return {
            "retrieval_partition_id": self.state.partition_id,
            "resource_count": len(file_ids),
            "head_count": len(file_ids),
            "event_count": len(file_ids),
            "search_job_count": len(file_ids),
            "rag_job_count": len(file_ids),
            "opensearch_record_count": len(file_ids),
            "qdrant_record_count": len(file_ids),
            "fingerprint_sha256": "a" * 64,
        }

    def snapshot(self, *, corpus_id: str, file_ids):
        return self.wait_projected(corpus_id=corpus_id, file_ids=file_ids)

    def content_probe(self, *, file_ids):
        return "do not report body content", sorted(file_ids)[0]

    def cleanup_target(self, *, corpus_id: str):
        assert corpus_id == self.state.corpus_id
        active_ids = () if self.state.deleted else tuple(sorted(self.state.files))
        return active_ids

    def wait_removed(self, *, corpus_id: str, file_ids, **_kwargs):
        assert self.state.deleted
        return {
            "resource_count": len(file_ids),
            "deleted_head_count": len(file_ids),
            "opensearch_record_count": 0,
            "qdrant_record_count": 0,
            "storage_object_count": 0,
            "search_delete_succeeded_count": len(file_ids),
            "rag_delete_succeeded_count": len(file_ids),
        }


def test_upload_commit_then_client_failure_recovers_unknown_file_ids(
    tmp_path: Path,
) -> None:
    live = _load_script_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.txt").write_text(
        "private evidence remains searchable after extraction",
        encoding="utf-8",
    )
    canaries = live.select_live_canaries(
        source,
        max_canaries=1,
        max_total_bytes=1024,
        workers=1,
        run_nonce=b"upload-loss-test-nonce",
    )
    state = _FakeLiveState()

    class ResponseLostAfterCommit(_FakeLiveApi):
        def upload(self, corpus_id: str, canary):
            super().upload(corpus_id, canary)
            raise live.LiveE2EContractError("simulated_upload_response_loss")

        def bulk_delete(self, file_ids) -> None:
            super().bulk_delete(file_ids)
            raise live.LiveE2EContractError("simulated_delete_response_loss")

    try:
        live.run_live_e2e(
            source=source,
            canaries=canaries,
            acl_group_id="e2e-group",
            actor_api=ResponseLostAfterCommit(state, principal="actor"),
            observer_a_api=_FakeLiveApi(state, principal="observer-a"),
            observer_b_api=_FakeLiveApi(state, principal="observer-b"),
            inspector=_FakeProjectionInspector(state),
            timeout_seconds=10,
            poll_interval_seconds=0.01,
        )
    except live.LiveE2EContractError as error:
        assert error.code == "simulated_upload_response_loss"
    else:
        raise AssertionError("lost upload response was accepted")
    assert state.files
    assert state.deleted is True


def test_group_membership_commit_then_client_failure_cleans_canaries_and_revokes_test_grants(
    tmp_path: Path,
) -> None:
    live = _load_script_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.txt").write_text(
        "private evidence remains searchable after extraction", encoding="utf-8"
    )
    canaries = live.select_live_canaries(
        source, max_canaries=1, max_total_bytes=1024, workers=1, run_nonce=b"group-loss-test-nonce"
    )
    state = _FakeLiveState()

    class ResponseLostAfterGroupCommit(_FakeLiveApi):
        def replace_acl_group_members(self, group_id, user_ids):
            super().replace_acl_group_members(group_id, user_ids)
            if user_ids == ["id-observer-b"]:
                raise live.LiveE2EContractError("simulated_group_response_loss")

    with pytest.raises(live.LiveE2EContractError, match="simulated_group_response_loss"):
        live.run_live_e2e(
            source=source,
            canaries=canaries,
            acl_group_id="e2e-group",
            actor_api=ResponseLostAfterGroupCommit(state, principal="actor"),
            observer_a_api=_FakeLiveApi(state, principal="observer-a"),
            observer_b_api=_FakeLiveApi(state, principal="observer-b"),
            inspector=_FakeProjectionInspector(state),
            timeout_seconds=10,
            poll_interval_seconds=0.01,
        )
    assert state.deleted is True
    assert state.admitted == set()
