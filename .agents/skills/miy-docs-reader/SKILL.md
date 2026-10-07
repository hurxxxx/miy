---
name: miy-docs-reader
description: Read native local MIY Docs pages or recent updates through verified development storage. Excludes repository Markdown, remote/production data, and database writes.
---

# Local Docs Reader

[read_miy_doc.py](scripts/read_miy_doc.py) reads local PostgreSQL-backed Docs. It verifies development profile, loopback DSN/database, Compose labels, and bucket before querying; remote/production identities fail closed. Credentials stay private and database operations stay read-only.

```bash
python3 .agents/skills/miy-docs-reader/scripts/read_miy_doc.py '/apps/docs/<doc_id>?page=<page_id>'
python3 .agents/skills/miy-docs-reader/scripts/read_miy_doc.py --updates --limit 20
python3 .agents/skills/miy-docs-reader/scripts/read_miy_doc.py --copy-media /tmp/miy-doc-media '/apps/docs/<doc_id>?page=<page_id>'
```

Copy media only when needed into an explicitly selected empty directory. Limits: 20 files, 50 MiB per file, 30 seconds per subprocess. The helper cleans temporary media/private config on success or failure and never overwrites existing files. Report source identity, ownership, page IDs/timestamps, extracted content, and media metadata within the requested scope.
