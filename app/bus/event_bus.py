"""In-process async pub/sub event bus.

Pipeline parts publish events and subscribe to event types. Delivery is
isolated: one subscriber raising does not stop delivery to the others —
its failure is logged and swallowed so a bad part can't kill a session.
"""

import asyncio
import inspect
import traceback
from collections import defaultdict
from typing import Awaitable, Callable

# A handler takes one event instance. It may be sync or async.
Handler = Callable[[object], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        # event type -> list of handlers
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        """Register `handler` to receive every event of `event_type`."""
        self._subscribers[event_type].append(handler)

    async def publish(self, event: object) -> None:
        """Deliver `event` to every handler subscribed to its type.

        Handlers run sequentially. A handler that raises is logged and
        skipped — delivery to remaining handlers continues.
        """
        for handler in self._subscribers[type(event)]:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 — isolation is the point
                print(f"event bus: handler for {type(event).__name__} failed")
                traceback.print_exc()
