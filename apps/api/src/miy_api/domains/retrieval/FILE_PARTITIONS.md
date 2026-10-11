# Prepared Files descriptors

`prepared_file_partitions.py` owns fixed internal Core setup for Files/company
default and managed descriptors. It is separate from Source file/corpus/tree
mutation, object publication, Core projection acceptance and service activation.
The ordinary allocators and the existing Docs/PMS/Meeting setup remain unchanged.

## Retained identity and caller transaction

Before setup the trusted caller retains a `PreparedFilePartitionSpec` containing
one canonical UUID, exactly `company_default` or `company_managed`, and a positive
PostgreSQL integer metadata version. Setup never generates a UUID or chooses a
different singleton after a conflict. The exact descriptor is namespace `files`,
scope `company`, user NULL, active, with the retained default flag and version.

`prepare_file_partition_descriptor` requires actual descriptor SELECT, INSERT and
UPDATE plus audit INSERT. Current Core platform-admin authority is resolved
through the existing live AuthSession resolver. The existing official ownership
lock compares the exact supplied owner/generation/artifact/state, with fresh
authority after waits. A clean, non-nested READ COMMITTED caller transaction is
required. Local lock/statement timeouts bound admission. Dirty/new/deleted ORM
work and nested transactions are refused before SQL without rollback or close.

Creation uses the retained UUID and stages one existing audit entry in the same
transaction. Exact replay validates all fields under descriptor SHARE and adds
no descriptor or audit. ID/default conflicts refuse; the caller owns rollback.
These helpers neither commit nor close the caller Session. Every returned receipt
is provisional, including exact replay and observation. A receipt does not prove
the caller's COMMIT acknowledgment or Source binding/cutover.

## Current discovery and unknown outcome

`lookup_current_file_default` reads the actual current default UUID/version or
returns no observation. A transitioning descriptor refuses. This read never
allocates; the caller retains its result before any setup or Source binding.

`lookup_prepared_file_partition` observes only the retained spec. It requires
descriptor SELECT and the existing current Core auth/ownership read closure,
performs no row lock, DML or audit, and remains provisional. Current role/session
or ownership changes refuse. Missing is unobserved; wrong kind/version/namespace
or retirement is conflict. After an unacknowledged COMMIT the caller keeps the
same UUID/spec and performs this read only. An absent row is not permission to
retry an allocator or a statement that the unknown COMMIT was rejected.

There is no external effect in this setup slice and no new generic operation
ledger or runner. A caller providing its own COMMIT/unknown handling must preserve
the spec and its transaction outcome rather than interpret Session cleanup as
proof of rejection. AuthSession IDs are internal execution references, not a new
HTTP authentication mechanism or credentials.

## Source admission and remaining gates

`require_prepared_file_source_partition` validates only the retained UUID and a
NULL default-version selector or exact positive managed version. It calls the
separate fixed `miy_read_file_source_partition(uuid,integer)` capability; it does
not SELECT a Core descriptor directly, allocate, write Core or grant user access.
The capability's actual Source principal admission and retained descriptor SHARE
own runtime authority. It must be explicitly installed/prepared under its own
contract; no old Source/Core profile is widened by importing this helper.

Source must separately lock its aggregate and verify the actual corpus/parent/
target binding and current actor/app/ACL after waits and I/O. Default setup does
not make an upload immutable or a tree scan exhaustive. Publication, aggregate
serialization, current authenticated service composition, reconciliation and
matched runtime/schema/roles remain structural gates. No HTTP endpoint, provider,
worker/Beat, service or deployment is enabled here.
