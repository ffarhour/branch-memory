"""The buffer of rejected moves, for conditions B (decay) and C (fixed)."""

import math

from pydantic import BaseModel

DROP_BELOW = 0.05


class BufferedMove(BaseModel):
    text: str
    scene_added: int
    weight: float = 1.0


def decayed_weight(age: int, tau: float) -> float:
    """Exponential decay: a move loses a fraction 1/e of its weight every tau scenes."""
    return math.exp(-age / tau)


def context_cap(k: int, tau: float) -> int:
    """Largest buffer condition C may hold, so its context length matches condition B.

    A move in B is dropped once exp(-age/tau) < 0.05, that is, once age > tau * ln(20),
    because 0.05 = 1/20. Each scene adds k-1 moves, so B levels off near this size.
    """
    return (k - 1) * math.ceil(tau * math.log(20))


class Buffer:
    def __init__(self, condition: str, tau: float, k: int, floor: float = DROP_BELOW):
        if condition not in ("B", "C"):
            raise ValueError(f"condition {condition} has no buffer")
        self.condition = condition
        self.tau = tau
        self.floor = floor
        self.cap = context_cap(k, tau)
        self.moves: list[BufferedMove] = []

    def update(self, scene: int, rejected: list[str]) -> None:
        """Age what is held to the current scene, then add this scene's rejected moves."""
        if self.condition == "B":
            for move in self.moves:
                move.weight = decayed_weight(scene - move.scene_added, self.tau)
            self.moves = [m for m in self.moves if m.weight >= self.floor]
        self.moves.extend(BufferedMove(text=text, scene_added=scene) for text in rejected)
        if self.condition == "C":
            # Weights never change in C, so the oldest moves leave first once over the cap.
            self.moves = self.moves[-self.cap:]

    def render(self) -> str:
        lines = ["Unused directions still in the air (weight):"]
        for move in sorted(self.moves, key=lambda m: -m.weight):
            lines.append(f"- [{move.weight:.2f}] {move.text}")
        return "\n".join(lines)

    def snapshot(self) -> list[BufferedMove]:
        return [move.model_copy() for move in self.moves]
