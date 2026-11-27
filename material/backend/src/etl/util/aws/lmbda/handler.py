from abc import ABC, abstractmethod
from typing import ClassVar

from etl.util.logging_setup import get_logger


class LambdaHandler(ABC):
    r"""Base class and builder for Lambda handlers. Subclass and implement this to create a new Lambda event handler type.

    Class variable \"_event_source\" needs to be set to a matching aws event and is used to identify this handler type.
    There can only ever be one handler registered for each \"_event_source\".
    """

    _registry: ClassVar[dict[str, type["LambdaHandler"]]] = {}
    _event_source: str | None = None

    def __init_subclass__(cls) -> None:
        cls.logger = get_logger(cls.__name__)
        if cls._event_source:
            if cls._event_source in LambdaHandler._registry:
                raise ValueError(f"Duplicate handler: {cls._event_source}")
            LambdaHandler._registry[cls._event_source] = cls

    @abstractmethod
    async def handle_event(self, event, context):
        raise NotImplementedError

    @classmethod
    def get_handler(cls, event_source: str):
        handler_cls = cls._registry.get(event_source, None)

        if not handler_cls:
            raise ValueError(f"No handler for: {event_source}")
        return handler_cls()
