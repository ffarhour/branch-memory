"""A stand-in for the SDK client. Tests never touch the network."""

import json
from types import SimpleNamespace


def message(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        _request_id="req_test",
    )


def moves_json(k: int, tag: str = "move") -> str:
    return json.dumps({"moves": [f"{tag} {i}" for i in range(k)]})


class FakeSDK:
    """Answers by prompt type. Pass `script` to override answers for chosen call numbers."""

    def __init__(self, k: int = 4, script: dict | None = None):
        self.k = k
        self.script = script or {}
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        scripted = self.script.get(len(self.requests))
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is not None:
            return scripted
        user = kwargs["messages"][0]["content"]
        if "moves for the next scene" in user:
            return message(moves_json(self.k, f"call{len(self.requests)}"))
        if '"closeness"' in user:
            return message('{"closeness": 2}')
        if '"coherence"' in user:
            return message('{"coherence": 4, "reason": "fine"}')
        if user.rstrip().endswith("sentence only."):
            return message("Someone leaves.")
        return message("She opened the door.\n\nThe yard was empty.")
