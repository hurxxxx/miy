"""Structured execution for explicit factory-owned database read callables."""

from collections.abc import Callable
from typing import TypeVar, cast

from anyio import CancelScope, CapacityLimiter, create_task_group, to_thread

T = TypeVar("T")


async def run_owned_read(read: Callable[[], T], *, limiter: CapacityLimiter) -> T:
    result: T | None = None
    error: BaseException | None = None

    async def read_owned() -> None:
        nonlocal result, error
        # A raw host Task.cancel() must not cancel the thread's await Future.
        # The structured group joins this private child before releasing the
        # parent admission permit, including repeated host cancellation.
        with CancelScope(shield=True):
            try:
                result = await to_thread.run_sync(
                    read,
                    limiter=CapacityLimiter(1),
                    abandon_on_cancel=False,
                )
            except BaseException as exc:
                # Preserve the original policy/control/cancellation type rather
                # than exposing an ExceptionGroup to the HTTP adapter.
                error = exc

    async with limiter:
        async with create_task_group() as group:
            group.start_soon(read_owned)
    if error is not None:
        raise error
    return cast(T, result)
