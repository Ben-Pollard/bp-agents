from typing import Literal, TypedDict


class StageContract(TypedDict):
    stage: str
    direction: Literal["input", "output"]
    timestamp: str
    payload: dict


__all__ = ["StageContract"]
