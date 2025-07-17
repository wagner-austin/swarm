from typing import Any, Callable, Concatenate, Generic, ParamSpec, TypeVar

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

class AsyncResult(Generic[_R]):
    def get(self, timeout: float | None = None) -> _R: ...

class Celery:
    conf: Any
    def __init__(self, *a: Any, **kw: Any) -> None: ...
    def task(
        self, *a: Any, **kw: Any
    ) -> Callable[[Callable[Concatenate[Task[Any, _R], _P], _R]], Task[_P, _R]]: ...
    def send_task(self, *a: Any, **kw: Any) -> AsyncResult[Any]: ...
    def signature(self, *a: Any, **kw: Any) -> Any: ...
    def autodiscover_tasks(self, packages: list[str], *args: Any, **kwargs: Any) -> None: ...

def group(*a: Any, **kw: Any) -> Any: ...

__all__: list[str]
