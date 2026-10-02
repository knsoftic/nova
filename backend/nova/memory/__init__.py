"""Memory: short-term (current conversation), long-term facts, conversation history and workflows.

Submodules are imported directly (nova.memory.agent, nova.memory.facts, ...): the AI rules use memory.facts, and
importing the agent here would make that a circular import.
"""
