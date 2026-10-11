# Official worker / Beat composition artifact

## Explicit first-party consumers

`miy_official_worker.runtime:celery_app` owns official consumption;
`miy_worker.first_party_platform:celery_app` owns platform consumption.
`miy_worker.first_party_beat:celery_app` is the one shared scheduler for the
unchanged nine schedules. Neither owned consumer can start Beat, and that
scheduler cannot start a worker. They use native Celery registration/publication,
the existing shared first-party DB/ACL/claim/lease/transaction rules, and the
existing fixed legacy writer identity. Source-only roles and the inactive
delegated profiles below remain closed.

The actual four official task implementations now live in
`src/miy_official_worker/tasks`, inside the official wheel. Public
`miy_worker.tasks.*` entries are same-module compatibility aliases, so IDs,
functions, monkeypatch targets and private state retain one owner. Installed
legacy artifacts need the matching official worker wheel; a repository checkout
uses a narrow source fallback. No second copy of the task body is maintained.

The owned queues retain `miy.platform.<legacy-queue>` and
`miy.official.<legacy-queue>`. The explicit runtime selects a small standard
Celery Router which translates the known legacy queue of each task, preserving
ID, arguments, keyword arguments and retry/lease rules. Explicit unrelated
queue/exchange/routing-key destinations and unknown tasks refuse before broker
access. Every queue has its own direct exchange and routing key. Consumers check
the exact complete owned queue set before starting; no missing queue is created
implicitly. Queue namespaces are accidental-consumption boundaries; deployment
owns broker credentials/network and first-party service trust.

The exact consumer list can be read without starting a runtime:

```bash
python -m miy_worker.first_party_queues --profile official
python -m miy_worker.first_party_queues --profile platform
```

Before switching, stop old API producers and the old Beat, let existing legacy
workers finish, and verify every old queue is empty, every expected old consumer
has no active/reserved/scheduled work (including ETA/retry), and the consumer
inventory is complete. Uncertain or remaining work holds cutover. Do not purge,
blindly copy broker messages or republish them under new IDs. Then retire those
consumers and start the owned consumers, one scheduler and namespace producers
as the same deployment transition. Durable pending/expired-lease jobs stay in
the same DB and use the existing same-job recovery/republish path. A factory does
not assume this operational drain happened or create a new recovery engine.

## Inactive delegated profile

The `miy-official-worker` wheel exports
`miy_official_worker.celery_app:celery_app`. It registers only the four official
task modules (Files storage cleanup, Mail, Meeting and Recording), their 14 task
IDs and three Beat entries. The matching worker wheel exports the platform-only
entry `miy_worker.platform_app:celery_app` with eight modules, 14 task IDs and six
Beat entries. Its canonical module names resolve the same owned official task
source through the compatibility aliases described above. Shared API/runtime
dependencies still live in their matching compatibility wheels.

Both entries are **inactive**. Worker/Beat construction, task publication,
broker connection and direct/eager task execution raise
`worker_profile_not_activated`. No environment variable, broker URL or CLI queue
option enables them. Inspection imports no legacy bootstrap, installs no Beat
health hook and initializes no runtime database or platform extensions. Its
Mail decorator uses the existing typed lease default without reading runtime
settings. A real runtime must later use its verified deployment configuration.

The platform and official route plans use `miy.platform.<old-queue>` and
`miy.official.<old-queue>`. These names never replace the active legacy routes.
One profile/app is bound per process; trying to combine them or import an
unowned task module is refused instead of silently inheriting cached Celery
registrations. The standard Celery registry, scheduling and task options remain
the underlying contracts; there is no additional scheduler or agent engine.

The [worker owner](../../worker/README.md) documents the active legacy behavior
and activation prerequisites. The [local artifact check](../../../ops/official-suite-worker/README.md)
packages matching API/worker/entry wheels without starting a service. No broker
ACL, queue consumer, Beat owner, database principal or production release is
created by this artifact.
