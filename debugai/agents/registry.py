"""Fix agent registry + plugin architecture (Architecture §8.5).

Custom agents register at the front, so they take priority over the built-ins
and inherit the full diagnose-fix-verify loop.

    registry = FixAgentRegistry()
    registry.register(SyllabusAgent("class10_cbse.pdf"))   # custom, checked first
    agent = registry.find_agent(diagnosis)
"""

from __future__ import annotations

from debugai.agents.base import FixAgent
from debugai.agents.builtin import BUILTIN_AGENTS


class FixAgentRegistry:
    def __init__(self, include_builtins: bool = True):
        self.agents: list[FixAgent] = (
            [cls() for cls in BUILTIN_AGENTS] if include_builtins else []
        )

    def register(self, agent: FixAgent) -> None:
        """Register a custom agent — inserted first so it wins over built-ins."""
        self.agents.insert(0, agent)

    def find_agent(self, diagnosis: dict) -> FixAgent | None:
        for agent in self.agents:
            if agent.can_handle(diagnosis):
                return agent
        return None
