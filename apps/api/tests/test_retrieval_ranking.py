from __future__ import annotations


from miy_api.domains.retrieval.contracts import RetrievalHit


def _hit(
    *,
    source: str,
    resource_id: str,
    score: float,
    excerpt: str,
    methods: list[str],
    source_kind: str = "manual",
) -> RetrievalHit:
    return RetrievalHit(
        source=source,
        source_kind=source_kind,
        resource_type="docs_native_doc",
        resource_id=resource_id,
        title=f"Document {resource_id}",
        excerpt=excerpt,
        score=score,
        citation=f"/docs/{resource_id}" if source == "keyword" else f"{resource_id}:0",
        methods=methods,
        metadata={"scope_kind": "company"},
    )
