"""Tool wrappers for the pydantic-ai agent.

Provides all pydantic-ai compatible tools for the agent.
"""

from backend_orchestrator.tools.pydantic_tools import (
    _make_search_kb_tool,
    calculator_pydantic,
    current_time_pydantic,
    get_drv_contact_info_pydantic,
    get_pydantic_tools,
)

search_knowledge_base_pydantic = _make_search_kb_tool()

__all__ = [
    "calculator_pydantic",
    "current_time_pydantic",
    "get_drv_contact_info_pydantic",
    "get_pydantic_tools",
    "search_knowledge_base_pydantic",
]
