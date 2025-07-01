from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass


@dataclass
class Job:
    id: str  # e.g., "browser.goto", "tankpit.spawn", etc.
    type: str
    args: tuple[str, ...]
    kwargs: dict[str, object]
    reply_to: str  # stream name for the result
    created_ts: float

    def dumps(self) -> str:
        return json.dumps(self.__dict__)

    @staticmethod
    def loads(raw: str) -> Job:
        data = json.loads(raw)
        data["args"] = tuple(data["args"])
        data["kwargs"] = dict(data["kwargs"])
        return Job(**data)


def new_job(type_: str, *args: str, **kwargs: object) -> Job:
    return Job(
        id=str(uuid.uuid4()),
        type=type_,
        args=args,
        kwargs=kwargs,
        reply_to=f"results.{type_}",
        created_ts=time.time(),
    )
