from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, load_only, undefer

from miy_api.core.app_routes import InternalAppLocation, build_app_href
from miy_api.domains.files.app_catalog import FILES_APP
from miy_api.domains.files.current_content import (
    file_candidate_matches_current_content,
    file_extraction_result_marker,
    load_current_file_content,
)
from miy_api.domains.files.external_projection import (
    external_source_date_markers,
    external_source_keywords,
    external_source_targets,
    external_source_title,
    external_source_updated_at,
    refresh_safe_external_source_metadata,
    safe_external_source_metadata,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.retrieval_contract import (
    FILES_RAG_SOURCE_KIND,
    FILES_RETRIEVAL_ACTIVE,
)
from miy_api.domains.retrieval.partition_adapter_ids import (
    FILES_RETRIEVAL_PARTITION_ADAPTER_ID,
)
from miy_api.domains.search.entity_adapter_registry import (
    SearchEntityAdapter,
    SearchIndexLifecycleHooks,
)
from miy_api.domains.search.index_document import (
    build_search_document,
    search_person,
    trim_search_text,
)
from miy_api.domains.search.schemas import SearchEntityType
from miy_api.domains.search.target_keys import search_target_document_keys
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE


def load_file_search_document(db: Session, file_id: str) -> dict[str, Any] | None:
    file = db.scalar(
        select(FileManagerFile)
        .options(
            joinedload(FileManagerFile.owner),
            joinedload(FileManagerFile.source_metadata),
            undefer(FileManagerFile.extraction_text),
            undefer(FileManagerFile.extraction_metadata),
        )
        .where(
            FileManagerFile.id == file_id,
            FileManagerFile.deleted_at.is_(None),
            FileManagerFile.extraction_status == "ready",
        )
    )
    if file is None:
        return None
    return build_file_search_document(file=file)


def load_file_search_documents(
    db: Session,
) -> list[dict[str, Any]]:
    files = db.scalars(
        select(FileManagerFile)
        .options(
            joinedload(FileManagerFile.owner),
            joinedload(FileManagerFile.source_metadata),
            undefer(FileManagerFile.extraction_text),
            undefer(FileManagerFile.extraction_metadata),
        )
        .where(
            FileManagerFile.deleted_at.is_(None),
            FileManagerFile.extraction_status == "ready",
        )
        .order_by(FileManagerFile.created_at.asc(), FileManagerFile.id.asc())
    ).all()
    return [build_file_search_document(file=file) for file in files]


def load_file_search_document_for_entity(
    db: Session,
    *,
    entity_type: SearchEntityType | str,
    entity_id: str,
) -> dict[str, Any] | None:
    if str(entity_type) != SearchEntityType.FILE.value:
        return None
    return load_file_search_document(db, entity_id)


def build_file_search_document(
    *,
    file: FileManagerFile,
) -> dict[str, Any]:
    body = file.extraction_text or ""
    owner_label = (
        file.owner.display_name or file.owner.full_name if file.owner is not None else None
    )
    return build_search_document(
        entity_type=SearchEntityType.FILE,
        entity_id=file.id,
        title=external_source_title(file),
        summary=trim_search_text(body, 240),
        body=body,
        keywords=" ".join(
            value
            for value in (
                *external_source_keywords(file),
                file.content_type,
                owner_label,
            )
            if value
        ),
        status=file.extraction_status,
        status_label=None,
        visibility=file.visibility,
        people=[search_person("owner", file.owner_id, owner_label)],
        targets=external_source_targets(file),
        owner_user_id=file.owner_id,
        team_ids=[],
        participant_user_ids=[],
        shared_user_ids=[],
        granted_user_ids=[],
        date_markers=external_source_date_markers(file),
        deep_link=_file_deep_link(file=file),
        metadata={
            "resource_type": FILE_MANAGER_FILE_RESOURCE_TYPE,
            "resource_id": file.id,
            "source_kind": FILES_RAG_SOURCE_KIND,
            "folder_id": file.folder_id,
            "content_type": file.content_type,
            "size_bytes": file.size_bytes,
            "content_checksum": file.extraction_content_checksum,
            "extracted_at": file_extraction_result_marker(file.extracted_at),
            "extraction": dict(file.extraction_metadata or {}),
            **safe_external_source_metadata(file),
        },
        source_updated_at=external_source_updated_at(file),
    )


def _file_deep_link(*, file: FileManagerFile) -> str:
    query = {"file": file.id}
    if file.folder_id:
        query["folder"] = file.folder_id
    return build_app_href(
        InternalAppLocation(
            route_id="files.root",
            query_params=query,
        )
    )


def hydrate_file_search_rows_from_source(
    db: Session,
    *,
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep current-content candidates and refresh response-routing/ACL hints.

    Indexed fields remain retrieval candidates only. This helper never grants
    access and never adds a row; the caller must run the source-owned ACL after
    hydration. Missing or out-of-scope source rows are dropped fail-closed.
    """

    file_ids = tuple(
        dict.fromkeys(
            str(row.get("entity_id") or "")
            for row in rows
            if str(row.get("entity_type") or "") == SearchEntityType.FILE.value
            and str(row.get("entity_id") or "")
        )
    )
    if not file_ids:
        return [
            row for row in rows if str(row.get("entity_type") or "") != SearchEntityType.FILE.value
        ]
    with db.no_autoflush:
        files_by_id = (
            {
                file.id: file
                for file in db.scalars(
                    select(FileManagerFile)
                    .options(
                        load_only(
                            FileManagerFile.id,
                            FileManagerFile.owner_id,
                            FileManagerFile.filename,
                            FileManagerFile.folder_id,
                            FileManagerFile.corpus_id,
                            FileManagerFile.content_type,
                            FileManagerFile.size_bytes,
                            FileManagerFile.visibility,
                            FileManagerFile.updated_at,
                            raiseload=True,
                        ),
                        joinedload(FileManagerFile.corpus).load_only(
                            FileManagerCorpus.id,
                            FileManagerCorpus.access_scope_kind,
                            raiseload=True,
                        ),
                        joinedload(FileManagerFile.source_metadata).load_only(
                            FileManagerFileSourceMetadata.file_id,
                            FileManagerFileSourceMetadata.source_kind,
                            FileManagerFileSourceMetadata.title,
                            FileManagerFileSourceMetadata.author,
                            FileManagerFileSourceMetadata.authored_at,
                            FileManagerFileSourceMetadata.department,
                            FileManagerFileSourceMetadata.document_type,
                            FileManagerFileSourceMetadata.source_updated_at,
                            FileManagerFileSourceMetadata.content_checksum,
                            raiseload=True,
                        ),
                    )
                    .where(
                        FileManagerFile.id.in_(file_ids),
                        FileManagerFile.deleted_at.is_(None),
                    )
                    .execution_options(populate_existing=True)
                )
            }
            if file_ids
            else {}
        )
    # This witness follows routing reads: a mutation during hydration cannot
    # pass an earlier content identity into rerank or the response.
    current_content = load_current_file_content(db, file_ids=file_ids)

    hydrated: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("entity_type") or "") != SearchEntityType.FILE.value:
            hydrated.append(row)
            continue
        file = files_by_id.get(str(row.get("entity_id") or ""))
        candidate_metadata = dict(row.get("metadata") or {})
        if file is None or not file_candidate_matches_current_content(
            current_content.get(file.id),
            candidate_checksum=candidate_metadata.get("content_checksum"),
            candidate_partition_id=row.get("retrieval_partition_id"),
            candidate_extracted_at=candidate_metadata.get("extracted_at"),
        ):
            continue
        corpus = file.corpus
        access_scope_kind = corpus.access_scope_kind if corpus is not None else "company"

        fresh = dict(row)
        fresh["visibility"] = access_scope_kind if corpus is not None else file.visibility
        fresh["deep_link"] = _file_deep_link(
            file=file,
        )
        fresh["title"] = external_source_title(file)
        fresh["source_updated_at"] = external_source_updated_at(file).isoformat()
        targets = external_source_targets(file)
        fresh["targets"] = targets
        fresh["target_keys"] = list(
            dict.fromkeys(key for target in targets for key in search_target_document_keys(target))
        )
        fresh["date_markers"] = external_source_date_markers(file)
        metadata = refresh_safe_external_source_metadata(
            candidate_metadata,
            file=file,
        )
        metadata.update(
            {
                "resource_type": FILE_MANAGER_FILE_RESOURCE_TYPE,
                "resource_id": file.id,
                "source_kind": FILES_RAG_SOURCE_KIND,
                "corpus_id": file.corpus_id,
                "access_scope_kind": access_scope_kind,
                "folder_id": file.folder_id,
                "content_type": file.content_type,
                "size_bytes": file.size_bytes,
                # Response conversion drops the top-level partition; retain
                # the admitted candidate envelope rather than manufacture it.
                "content_checksum": candidate_metadata["content_checksum"],
                "retrieval_partition_id": row.get("retrieval_partition_id"),
                "extracted_at": candidate_metadata["extracted_at"],
            }
        )
        fresh["metadata"] = metadata
        hydrated.append(fresh)
    return hydrated


FILES_KEYWORD_SEARCH_ADAPTER = SearchEntityAdapter(
    owner_app=FILES_APP,
    entity_type=SearchEntityType.FILE.value,
    resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
    label="파일",
    label_key="ai.search.entityFile",
    company_loader=load_file_search_documents,
    document_loader=load_file_search_document_for_entity,
    partition_adapter_id=FILES_RETRIEVAL_PARTITION_ADAPTER_ID,
    active=FILES_RETRIEVAL_ACTIVE,
    index_hooks=SearchIndexLifecycleHooks(
        create=("files.enqueue_file_search_index",),
        update=(
            "files.enqueue_file_search_index",
            "files.enqueue_file_search_index_by_id",
        ),
        delete=("files.enqueue_file_search_index",),
    ),
    person_roles=("owner",),
)


__all__ = [
    "FILES_KEYWORD_SEARCH_ADAPTER",
    "build_file_search_document",
    "hydrate_file_search_rows_from_source",
    "load_file_search_document",
    "load_file_search_document_for_entity",
    "load_file_search_documents",
]
