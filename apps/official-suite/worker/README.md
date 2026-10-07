# Official worker / Beat composition artifact

The `miy-official-worker` wheel exports
`miy_official_worker.celery_app:celery_app`. It registers only the four official
task modules (Files storage cleanup, Mail, Meeting and Recording), their 14 task
IDs and three Beat entries. The matching worker wheel exports the platform-only
entry `miy_worker.platform_app:celery_app` with eight modules, 14 task IDs and six
Beat entries. Task implementations still reside in that compatibility wheel;
this entry package does not complete independent source/dependency extraction.

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
