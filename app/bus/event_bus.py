"""In-process async pub/sub event bus.

Delivery is isolated: one subscriber raising does not stop delivery to the
others — its failure is logged so a bad part can't kill a session.
"""

import inspect
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable

Handler = Callable[[object], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event: object) -> None:
        """Deliver `event` to every handler subscribed to its type, in order."""
        for handler in self._subscribers[type(event)]:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 — isolation is the point
                print(f"event bus: handler for {type(event).__name__} failed")
                traceback.print_exc()
