from typing import Any, Callable, Concatenate, Generic, ParamSpec, TypeVar

from celery.result import AsyncResult

_P = ParamSpec("_P")
_R = TypeVar("_R")

class Task(Generic[_P, _R]):
    name: str
    request: Any
    app: Any
    def delay(self, *args: Any, **kwargs: Any) -> AsyncResult[_R]: ...
    def apply_async(self, *args: Any, **kwargs: Any) -> AsyncResult[_R]: ...
    def retry(self, **kwargs: Any) -> None: ...
    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None: ...
    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None: ...
    def on_success(
        self, retval: _R, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None: ...

class Control:
    def ping(self, timeout: float | None = None) -> list[dict[str, Any]]: ...

class Celery:
    conf: Any
    control: Control
    def __init__(self, *a: Any, **kw: Any) -> None: ...
    def task(
        self, *a: Any, **kw: Any
    ) -> Callable[[Callable[Concatenate[Task[Any, _R], _P], _R]], Task[_P, _R]]: ...
    def send_task(self, *a: Any, **kw: Any) -> AsyncResult[Any]: ...
    def signature(self, *a: Any, **kw: Any) -> Any: ...
    def autodiscover_tasks(self, packages: list[str], *args: Any, **kwargs: Any) -> None: ...
    def worker_main(self, argv: list[str] | None = None) -> None: ...

def group(*a: Any, **kw: Any) -> Any: ...

__all__: list[str]
