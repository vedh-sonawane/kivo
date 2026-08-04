"""Kivo backend - the host-side "brain" for the Kivo desk companion.

Layering (dependencies point downward):

    cli / api  →  device  →  protocol  →  transport

See ``docs/architecture.md`` for the full picture.
"""

__version__ = "0.1.0"
