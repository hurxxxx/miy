"""Bounded flat Source tree contracts and actual unchanged Source29 transactions."""

from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from test_file_source_mutations_authority import (
    native as native,
)
from test_file_source_mutations_authority import (
    extraction_prepared as extraction_prepared,
    file_source_prepared as file_source_prepared,
    isolated_data_cluster as isolated_data_cluster,
    role_template as role_template,
    world as world,
)

from miy_api.domains.files.source_tree_mutation_contracts import (
    FileSourceFolderDeleteExpected,
    FileSourceFolderDeleteMember,
    FileSourceFolderDeleteSpec,
    FileSourceFolderFileExpected,
)


@pytest.fixture
def spec():
    actor, folder = str(uuid4()), str(uuid4())
    partition = uuid4()
    stamp = datetime(2026, 10, 8, 12).isoformat(timespec="microseconds")
    members = []
    for identifier in sorted(str(uuid4()) for _ in range(2)):
        members.append(
            FileSourceFolderDeleteMember(
                file_id=identifier,
                event_id=uuid4(),
                expected=FileSourceFolderFileExpected(
                    owner_id=actor,
                    retrieval_partition_id=partition,
                    folder_id=folder,
                    storage_key="synthetic/private/" + identifier,
                    filename="synthetic.txt",
                    content_type="text/plain",
                    size_bytes=3,
                    created_at=stamp,
                    updated_at=stamp,
                    extraction_status="ready",
                    extraction_content_checksum=sha256(b"abc").hexdigest(),
                    extracted_at=stamp,
                    tip_event_id=uuid4(),
                    tip_event_digest="a" * 64,
                    tip_source_revision=1,
                ),
            )
        )
    return FileSourceFolderDeleteSpec(
        folder_id=folder,
        actor_user_id=actor,
        execution_ref=str(uuid4()),
        expected=FileSourceFolderDeleteExpected(
            owner_id=actor,
            retrieval_partition_id=partition,
            name="Synthetic folder",
            created_at=stamp,
            updated_at=stamp,
        ),
        members=tuple(members),
    )
