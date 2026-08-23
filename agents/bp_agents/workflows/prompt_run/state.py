from typing import TypedDict


class PromptRunState(TypedDict):
    prompt: str
    status: str
    outcome: dict | None
