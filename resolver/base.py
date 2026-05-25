"""Abstract base class for individual resolver sources."""
from __future__ import annotations

import abc
import logging
from typing import Optional

from resolver.types import ResolvedObject

logger = logging.getLogger(__name__)


class Resolver(abc.ABC):
    """One source in the resolver chain.

    Subclasses should be cheap to instantiate. Heavy initialization
    (e.g. loading catalog files, opening network sessions) should be lazy
    so that disabling a source via settings has zero cost.
    """

    #: Stable identifier (snake_case). Logged and stored in cache rows.
    name: str = "base"

    #: Network resolvers should set this to True so callers can gate them
    #: behind ``resolver_offline_mode``.
    requires_network: bool = False

    #: Confidence assigned to results returned by this source (0..1).
    default_confidence: float = 1.0

    def is_available(self) -> bool:
        """Whether this resolver can attempt a lookup right now.

        Default: always available. Override in network-bound subclasses
        to e.g. check for ``astroquery`` import success.
        """
        return True

    @abc.abstractmethod
    def resolve(self, query: str) -> Optional[ResolvedObject]:
        """Attempt to resolve ``query``. Return ``None`` on miss.

        Implementations MUST NOT raise on a clean miss. Raise only on
        unexpected internal errors; the chain will catch and continue.
        """
        ...
