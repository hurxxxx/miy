"""Pure contract and real Session ownership boundaries for the fixed Source leaf."""

from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceDeleteSpec,
)


@pytest.fixture
def spec():
    stamp = datetime(2026, 10, 7, 12).isoformat(timespec="microseconds")
    actor = str(uuid4())
    return FileSourceDeleteSpec(
        file_id=str(uuid4()),
        actor_user_id=actor,
        execution_ref=str(uuid4()),
        event_id=uuid4(),
        expected=FileSourceDeleteExpected(
            owner_id=actor,
            retrieval_partition_id=uuid4(),
            storage_key="synthetic/private-object",
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
