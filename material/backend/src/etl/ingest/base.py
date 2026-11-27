from abc import ABC, abstractmethod
from logging import Logger
from typing import ClassVar, TypeVar

from etl.models import PipelineItem
from etl.util.logging_setup import get_logger
from etl.util.repository.base import Repository

TType = TypeVar("TType", bound=Repository)


class Ingest[TType: Repository](ABC):
    """Base class and factory for ingest pipeline objects."""

    logger: Logger

    _registry: ClassVar[dict[str, type["Ingest"]]] = {}

    # Set in each subclass; must match a registered repository type.
    repository_type: str | None = None

    _repo: TType
    _objects: list[str] | None

    def __init_subclass__(cls) -> None:
        cls.logger = get_logger(cls.__name__)
        if cls.repository_type:
            existing = Ingest._registry.get(cls.repository_type)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"Duplicate ingest type '{cls.repository_type}': "
                    f"Already registered by {existing.__name__}, cannot register {cls.__name__}"
                )
            Ingest._registry[cls.repository_type] = cls

    def __init__(self, repository: TType, objects: list[str] | None, **kwargs) -> None:
        super().__init__()
        self._repo = repository
        self._objects = objects

    @abstractmethod
    async def ingest(self) -> list[PipelineItem]:
        """Fetch data from a specific source and return raw Data."""
        raise NotImplementedError

    @classmethod
    def create(cls, repository: Repository, objects: list[str] | None = None, **kwargs):
        """Create a new Ingest object by repository type.

        Raises:
            ValueError: Unknown repository type.

        """
        if not repository.repo_type:
            raise ValueError("Repository type is None")
        ingest_cls = cls._registry.get(repository.repo_type)
        if not ingest_cls:
            raise ValueError(f"Unknown repository type: {repository.repo_type}")
        return ingest_cls(repository, objects, **kwargs)
