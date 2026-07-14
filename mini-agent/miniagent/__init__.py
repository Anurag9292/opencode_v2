"""miniagent: a minimal educational coding-agent harness.

Start with miniagent/impl/loop.py -- the turn loop is the whole idea.
Interfaces live in miniagent/interfaces/, one file per seam.
"""

from .impl.session import LocalSession
from .impl.scripted import ScriptedProvider
from .impl.anthropic import AnthropicProvider
from .impl.permission import Rule

__all__ = ["LocalSession", "ScriptedProvider", "AnthropicProvider", "Rule"]
