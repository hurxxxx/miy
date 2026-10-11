from __future__ import annotations


from miy_api.domains.search.backend_contracts import (
    KeywordSearchHit,
    KeywordSearchQuery,
    KeywordSearchResult,
)


class FakeKeywordClient:
    def __init__(
        self,
        *,
        index_exists: bool = True,
        document_count: int = 1,
        entity_counts: dict[str, int] | None = None,
        has_hit: bool = True,
        hit_entity_type: str = "doc",
    ) -> None:
        self._index_exists = index_exists
        self._document_count = document_count
        self._entity_counts = entity_counts or {}
        self._has_hit = has_hit
        self._hit_entity_type = hit_entity_type
        self.query: KeywordSearchQuery | None = None

    def index_exists(self) -> bool:
        return self._index_exists

    def count_company_documents(
        self,
        *,
        entity_types: tuple[str, ...] = (),
    ) -> int:
        if entity_types:
            assert len(entity_types) == 1
            return self._entity_counts.get(entity_types[0], self._document_count)
        return self._document_count

    def search(self, query: KeywordSearchQuery) -> KeywordSearchResult:
        self.query = query
        if not self._has_hit:
            return KeywordSearchResult(hits=())
        return KeywordSearchResult(
            hits=(
                KeywordSearchHit(
                    document={
                        "entity_type": self._hit_entity_type,
                    },
                    score=1.0,
                ),
            )
        )
