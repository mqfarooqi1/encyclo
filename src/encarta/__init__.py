"""Modern Encarta / World Explorer.

An offline-first, source-grounded educational encyclopaedia.

Design contract: SOURCE -> EVIDENCE -> ARTICLE -> CITATION -> VERSION -> REVIEW.
No layer above may assert a fact the layer below does not support.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
