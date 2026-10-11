"""Bounded Core-only keyword/vector transport for one exact owned resource pair."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from qdrant_client import QdrantClient, models

from miy_api.domains.rag.provider_factory import get_rag_provider_registry
from miy_api.domains.retrieval.evaluation import retrieval_embedding_generation_identity
from miy_api.domains.search.index_gateway import keyword_index_definition

PROFILE = "rag-inference-v1"
_OWNER_POINT = "00000000-0000-0000-0000-000000000001"
_MAX_RESPONSE = 1024 * 1024


class SearchFailure(Exception):
    def __init__(self, code="search_unavailable", *, uncertain=True):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


@dataclass(frozen=True)
class SearchCandidate:
    record_id: str
    sequence: int
    score: float


def names(workspace_id, generation):
    if type(generation) is not int or not 1 <= generation <= 2**31 - 1:
        raise SearchFailure("search_binding_invalid", uncertain=False)
    key = UUID(workspace_id).hex
    return f"miy-wb-{key}-g{generation}", f"miy_wb_{key}_g{generation}"


def marker(binding):
    if (binding.opensearch_index, binding.qdrant_collection) != names(
        binding.workspace_id, binding.generation
    ):
        raise SearchFailure("search_binding_invalid", uncertain=False)
    if (
        binding.embedding_profile != PROFILE
        or type(binding.embedding_dimensions) is not int
        or not 1 <= binding.embedding_dimensions <= 8192
    ):
        raise SearchFailure("search_embedding_profile_invalid", uncertain=False)
    if not re.fullmatch(r"[a-f0-9]{64}", binding.search_spec_sha256) or not re.fullmatch(
        r"[a-f0-9]{64}", binding.embedding_config_sha256
    ):
        raise SearchFailure("search_binding_invalid", uncertain=False)
    value = {
        "schema": 1,
        "installation": str(UUID(binding.installation_id)),
        "workspace": str(UUID(binding.workspace_id)),
        "generation": binding.generation,
        "search_spec": binding.search_spec_sha256,
        "embedding_profile": binding.embedding_profile,
        "embedding_config": binding.embedding_config_sha256,
        "dimensions": binding.embedding_dimensions,
    }
    return {
        "kind": "owner",
        "binding": value,
        "owner_digest": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
    }


def resolve_embedding_dimensions(settings):
    """Resolve the approved Core profile, never a dimension supplied by an app."""
    if not getattr(settings, "independent_app_search_enabled", False):
        raise SearchFailure("search_configuration_required", uncertain=False)
    if settings.rag_embedding_provider != "inference_gateway":
        raise SearchFailure("search_embedding_profile_invalid", uncertain=False)
    embedding = get_rag_provider_registry().build_embedding(
        settings.rag_embedding_provider, settings
    )
    try:
        vector = embedding.embed_query("MIY embedding profile dimension", timeout_seconds=2)
        if not 1 <= len(vector) <= 8192 or any(
            type(value) not in {int, float} or not math.isfinite(value) for value in vector
        ):
            raise SearchFailure("search_embedding_invalid")
        return len(vector)
    except SearchFailure:
        raise
    except Exception as exc:
        raise SearchFailure("search_embedding_unavailable") from exc


class _Stream(httpx.SyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        size = 0
        for chunk in self.stream:
            size += len(chunk)
            if size > _MAX_RESPONSE:
                raise SearchFailure("search_response_invalid")
            yield chunk

    def close(self):
        self.stream.close()


class _Transport(httpx.BaseTransport):
    def __init__(self):
        self.transport = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        request.headers["Accept-Encoding"] = "identity"
        response = self.transport.handle_request(request)
        if (
            response.is_redirect
            or response.headers.get("content-encoding", "identity") != "identity"
        ):
            response.close()
            raise SearchFailure("search_response_invalid")
        response.stream = _Stream(response.stream)
        return response

    def close(self):
        self.transport.close()


def _endpoint(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SearchFailure("search_configuration_invalid", uncertain=False)
    return value.rstrip("/")


class CoreSearchBackends:
    """Constructed only from typed Core settings; no app can configure this client."""

    def __init__(self, settings):
        if not getattr(settings, "independent_app_search_enabled", False):
            raise SearchFailure("search_configuration_required", uncertain=False)
        if settings.rag_embedding_provider != "inference_gateway":
            raise SearchFailure("search_embedding_profile_invalid", uncertain=False)
        self.profile_hash = retrieval_embedding_generation_identity(settings).config_sha256
        self.embedding = get_rag_provider_registry().build_embedding(
            settings.rag_embedding_provider, settings
        )
        self.keyword = httpx.Client(
            base_url=_endpoint(settings.opensearch_url),
            timeout=2,
            follow_redirects=False,
            trust_env=False,
            transport=_Transport(),
        )
        try:
            self.vector = QdrantClient(
                url=_endpoint(settings.rag_qdrant_url),
                api_key=settings.rag_qdrant_api_key or None,
                prefer_grpc=False,
                check_compatibility=False,
                timeout=2,
                follow_redirects=False,
                trust_env=False,
                transport=_Transport(),
            )
        except Exception:
            self.keyword.close()
            raise

    def close(self):
        self.keyword.close()
        self.vector.close()

    def _binding(self, binding):
        owned = marker(binding)
        if binding.embedding_config_sha256 != self.profile_hash:
            raise SearchFailure("search_embedding_profile_changed", uncertain=False)
        return owned

    def _keyword(self, method, path, *, body=None, allow_missing=False):
        try:
            response = self.keyword.request(method, path, json=body)
            if allow_missing and response.status_code == 404:
                return None
            if response.status_code not in {200, 201}:
                raise SearchFailure()
            value = response.json()
            if not isinstance(value, dict):
                raise SearchFailure("search_response_invalid")
            return value
        except SearchFailure:
            raise
        except (httpx.HTTPError, ValueError, RecursionError) as exc:
            raise SearchFailure() from exc

    def _keyword_owned(self, binding, *, allow_missing=False):
        expected = self._binding(binding)
        result = self._keyword("GET", f"/{binding.opensearch_index}", allow_missing=allow_missing)
        if result is None:
            return False
        try:
            item = result[binding.opensearch_index]
            if (
                item["mappings"]["_meta"] != expected
                or item["settings"]["index"]["uuid"] != binding.opensearch_uuid
            ):
                raise ValueError("identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise SearchFailure("search_resource_identity_mismatch", uncertain=False) from exc
        return True

    def _vector_owned(self, binding, *, allow_missing=False):
        expected = self._binding(binding)
        try:
            if allow_missing:
                exists = self.vector.collection_exists(binding.qdrant_collection)
                if type(exists) is not bool:
                    raise SearchFailure("search_response_invalid")
                if not exists:
                    return False
            info = self.vector.get_collection(binding.qdrant_collection)
            vector = info.config.params.vectors["dense"]
            owner = self.vector.retrieve(
                binding.qdrant_collection, [_OWNER_POINT], with_payload=True, with_vectors=False
            )
            if (
                vector.size != binding.embedding_dimensions
                or vector.distance != models.Distance.COSINE
                or len(owner) != 1
                or owner[0].payload != expected
            ):
                raise SearchFailure("search_resource_identity_mismatch", uncertain=False)
        except SearchFailure:
            raise
        except Exception as exc:
            raise SearchFailure() from exc
        return True

    def prepare(self, binding):
        expected = self._binding(binding)
        existing = self._keyword("GET", f"/{binding.opensearch_index}", allow_missing=True)
        if existing is None:
            definition = keyword_index_definition()
            definition["mappings"]["_meta"] = expected
            definition["mappings"]["properties"].update(
                {
                    "kind": {"type": "keyword"},
                    "app_collection": {"type": "keyword"},
                    "owner_id": {"type": "keyword"},
                    "record_id": {"type": "keyword"},
                    "sequence": {"type": "long"},
                    "owner_digest": {"type": "keyword"},
                    "text": {"type": "text", "analyzer": "korean_nori"},
                }
            )
            if (
                self._keyword("PUT", f"/{binding.opensearch_index}", body=definition).get(
                    "acknowledged"
                )
                is not True
            ):
                raise SearchFailure("search_effect_unknown")
            existing = self._keyword("GET", f"/{binding.opensearch_index}")
        try:
            item = existing[binding.opensearch_index]
            if item["mappings"]["_meta"] != expected:
                raise ValueError("identity")
            actual_uuid = item["settings"]["index"]["uuid"]
            if not isinstance(actual_uuid, str) or not 1 <= len(actual_uuid) <= 100:
                raise ValueError("identity")
            if binding.opensearch_uuid is not None and binding.opensearch_uuid != actual_uuid:
                raise ValueError("identity")
            binding.opensearch_uuid = actual_uuid
            if not self.vector.collection_exists(binding.qdrant_collection):
                if (
                    self.vector.create_collection(
                        binding.qdrant_collection,
                        vectors_config={
                            "dense": models.VectorParams(
                                size=binding.embedding_dimensions, distance=models.Distance.COSINE
                            )
                        },
                    )
                    is not True
                ):
                    raise SearchFailure()
                for field in ("kind", "owner_id", "app_collection", "owner_digest"):
                    self._completed(
                        self.vector.create_payload_index(
                            binding.qdrant_collection,
                            field,
                            models.PayloadSchemaType.KEYWORD,
                            wait=True,
                        )
                    )
                self._completed(
                    self.vector.upsert(
                        binding.qdrant_collection,
                        [
                            models.PointStruct(
                                id=_OWNER_POINT,
                                vector={"dense": [0.0] * binding.embedding_dimensions},
                                payload=expected,
                            )
                        ],
                        wait=True,
                    )
                )
            self._vector_owned(binding)
        except SearchFailure:
            raise
        except Exception as exc:
            raise SearchFailure() from exc

    @staticmethod
    def _completed(result):
        if result.status != models.UpdateStatus.COMPLETED:
            raise SearchFailure("search_effect_unknown")

    def _embed(self, binding, text, *, document=False):
        try:
            if document:
                vectors = self.embedding.embed_texts([text], timeout_seconds=2)
                if len(vectors) != 1:
                    raise SearchFailure("search_embedding_invalid")
                vector = vectors[0]
            else:
                vector = self.embedding.embed_query(text, timeout_seconds=2)
            if len(vector) != binding.embedding_dimensions or any(
                type(value) not in {int, float} or not math.isfinite(value) for value in vector
            ):
                raise SearchFailure("search_embedding_invalid")
            return vector
        except SearchFailure:
            raise
        except Exception as exc:
            raise SearchFailure("search_embedding_unavailable") from exc

    def write_keyword(self, binding, projection, text):
        self._keyword_owned(binding)
        if projection.deleted:
            result = self._keyword(
                "DELETE",
                f"/{binding.opensearch_index}/_doc/{projection.point_id}?refresh=wait_for",
                allow_missing=True,
            )
        else:
            result = self._keyword(
                "PUT",
                f"/{binding.opensearch_index}/_doc/{projection.point_id}?refresh=wait_for",
                body=self._document(binding, projection, text),
            )
        if result is not None and (
            result.get("_id") != projection.point_id
            or result.get("_index") != binding.opensearch_index
            or result.get("result") not in {"created", "updated", "deleted"}
            or result.get("_shards", {}).get("failed") != 0
        ):
            raise SearchFailure("search_effect_unknown")

    def write_semantic(self, binding, projection, text):
        self._vector_owned(binding)
        try:
            if projection.deleted:
                result = self.vector.delete(
                    binding.qdrant_collection,
                    models.PointIdsList(points=[projection.point_id]),
                    wait=True,
                )
            else:
                result = self.vector.upsert(
                    binding.qdrant_collection,
                    [
                        models.PointStruct(
                            id=projection.point_id,
                            vector={"dense": self._embed(binding, text, document=True)},
                            payload=self._document(binding, projection, text),
                        )
                    ],
                    wait=True,
                )
            self._completed(result)
        except SearchFailure:
            raise
        except Exception as exc:
            raise SearchFailure() from exc

    def _document(self, binding, projection, text):
        return {
            "kind": "record",
            "owner_digest": self._binding(binding)["owner_digest"],
            "app_collection": projection.collection,
            "owner_id": projection.owner_id,
            "record_id": projection.record_id,
            "sequence": projection.sequence,
            "text": text,
        }

    def query(self, binding, *, owner_id, collection, mode, query, limit):
        scope = {
            "kind": "record",
            "owner_id": owner_id,
            "app_collection": collection,
            "owner_digest": self._binding(binding)["owner_digest"],
        }
        if mode == "keyword":
            self._keyword_owned(binding)
            result = self._keyword(
                "POST",
                f"/{binding.opensearch_index}/_search",
                body={
                    "size": limit,
                    "_source": ["record_id", "sequence", *scope],
                    "query": {
                        "bool": {
                            "filter": [{"term": {key: value}} for key, value in scope.items()],
                            "must": [{"match": {"text": {"query": query}}}],
                        }
                    },
                },
            )
            try:
                hits = [(item["_source"], item["_score"]) for item in result["hits"]["hits"]]
            except (KeyError, TypeError) as exc:
                raise SearchFailure("search_response_invalid") from exc
        elif mode == "semantic":
            self._vector_owned(binding)
            try:
                result = self.vector.query_points(
                    binding.qdrant_collection,
                    query=self._embed(binding, query),
                    using="dense",
                    query_filter=models.Filter(
                        must=[
                            models.FieldCondition(key=key, match=models.MatchValue(value=value))
                            for key, value in scope.items()
                        ]
                    ),
                    limit=limit,
                    with_payload=["record_id", "sequence", *scope],
                    with_vectors=False,
                )
                hits = [(item.payload, item.score) for item in result.points]
            except SearchFailure:
                raise
            except Exception as exc:
                raise SearchFailure() from exc
        else:
            raise SearchFailure("search_mode_invalid", uncertain=False)
        if len(hits) > limit:
            raise SearchFailure("search_response_invalid")
        candidates, seen = [], set()
        for payload, score in hits:
            try:
                record = str(UUID(payload["record_id"]))
                sequence = payload["sequence"]
                if (
                    any(payload.get(key) != value for key, value in scope.items())
                    or type(sequence) is not int
                    or sequence < 1
                    or type(score) not in {int, float}
                    or not math.isfinite(score)
                    or record in seen
                ):
                    raise ValueError("hit")
            except (KeyError, TypeError, ValueError) as exc:
                raise SearchFailure("search_response_invalid") from exc
            seen.add(record)
            candidates.append(SearchCandidate(record, sequence, float(score)))
        return candidates

    def cleanup(self, binding, *, persist_phase):
        """Resume only the original verified deletion, with positive absence receipts."""
        phase = binding.cleanup_phase
        if phase is None:
            if binding.state != "stopped":
                raise SearchFailure("search_cleanup_held", uncertain=False)
            self._keyword_owned(binding)
            self._vector_owned(binding)
            # The caller commits this exact identity proof before any deletion.
            persist_phase("verified")
            phase = "verified"
        elif binding.state != "cleanup_pending" or phase not in {
            "verified",
            "keyword_removed",
            "vector_removed",
        }:
            raise SearchFailure("search_cleanup_held", uncertain=False)

        # Recheck both targets before changing either. A foreign replacement is
        # never adopted even when another original target has already disappeared.
        keyword_exists = self._keyword_owned(binding, allow_missing=True)
        vector_exists = self._vector_owned(binding, allow_missing=True)
        if keyword_exists:
            result = self._keyword("DELETE", f"/{binding.opensearch_index}")
            if result.get("acknowledged") is not True or self._keyword_owned(
                binding, allow_missing=True
            ):
                raise SearchFailure("search_cleanup_unknown")
        if phase == "verified":
            persist_phase("keyword_removed")
        if vector_exists:
            try:
                if self.vector.delete_collection(binding.qdrant_collection) is not True:
                    raise SearchFailure("search_cleanup_unknown")
            except SearchFailure:
                raise
            except Exception as exc:
                raise SearchFailure("search_cleanup_unknown") from exc
            if self._vector_owned(binding, allow_missing=True):
                raise SearchFailure("search_cleanup_unknown")
        if phase != "vector_removed":
            persist_phase("vector_removed")
