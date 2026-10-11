from __future__ import annotations


from miy_api.domains.search.backend_contracts import (
    KeywordAclBranch,
    KeywordAclFilter,
    KeywordSearchHit,
    KeywordSearchResult,
)
from miy_api.domains.search.schemas import KeywordSearchRequest
from miy_api.domains.search.service import (
    _load_authorized_ranked_candidates,
)


def _request(**overrides: object) -> KeywordSearchRequest:
    return KeywordSearchRequest.model_validate(overrides)


def _acl_filter(*branches: KeywordAclBranch) -> KeywordAclFilter:
    return KeywordAclFilter(branches=branches)


def test_keyword_acl_refill_uses_pit_and_search_after_until_authorized_hit() -> None:
    class _Client:
        def __init__(self) -> None:
            self.queries = []
            self.closed: list[str] = []

        def open_point_in_time(self, *, keep_alive: str = "1m") -> str:
            assert keep_alive == "1m"
            return "pit-1"

        def close_point_in_time(self, point_in_time_id: str) -> None:
            self.closed.append(point_in_time_id)

        def search(self, query):
            self.queries.append(query)
            resource_id = "denied" if not query.search_after else "allowed"
            cursor = (1,) if not query.search_after else (2,)
            return KeywordSearchResult(
                hits=(
                    KeywordSearchHit(
                        document={
                            "entity_type": "doc",
                            "entity_id": resource_id,
                        },
                        score=1.0,
                        sort_values=cursor,
                    ),
                )
            )

    class _Policy:
        def authorize_many_resources(self, resources):
            return {
                (resource_type, resource_id)
                for resource_type, resource_id in resources
                if resource_id == "allowed"
            }

    client = _Client()
    rows = _load_authorized_ranked_candidates(
        None,  # Doc-only synthetic candidates do not read Files Source state.
        acl_filter=KeywordAclFilter(),
        policy=_Policy(),
        allowed_entity_types=frozenset({"doc"}),
        request=_request(limit=1),
        backend_timeout_seconds=5.0,
        client=client,
        text_operator="and",
        text_minimum_should_match=None,
        size=1,
    )

    assert [row["entity_id"] for row in rows] == ["allowed"]
    assert len(client.queries) == 2
    assert client.queries[0].point_in_time_id == "pit-1"
    assert client.queries[1].search_after == (1,)
    assert client.closed == ["pit-1"]
