from miy_api.domains.files.archive_planner import (
    ArchivePlanFile,
    ArchivePlanFolder,
)


def folder(
    id: str,
    name: str,
    *,
    parent_id: str | None = None,
) -> ArchivePlanFolder:
    return ArchivePlanFolder(id=id, parent_id=parent_id, name=name)


def file(
    id: str,
    filename: str,
    *,
    folder_id: str | None = None,
) -> ArchivePlanFile:
    return ArchivePlanFile(id=id, folder_id=folder_id, filename=filename)
