"""Per-prospect research: find ONE true, specific, recent hook to open a message on.

The single biggest lever on reply rate is the opener, and the opener is only as good
as the fact behind it. Each researcher implements the ``Researcher`` protocol (one new
file per source, like ``sources/`` and ``enrichment/``); ``research_prospect`` runs them
and returns the best hook for the draft stage to feed the writer.
"""

from leia.research.base import Researcher, ResearchHook, research_prospect

__all__ = ["ResearchHook", "Researcher", "research_prospect"]
