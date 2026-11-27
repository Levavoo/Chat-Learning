from abc import ABC, abstractmethod
from logging import Logger
from typing import ClassVar

from etl.models import OutputData, PipelineItem
from etl.util.logging_setup import get_logger
from etl.util.repository.base import Repository


class Output(ABC):
    """Base class and factory for Output pipeline objects."""

    logger: Logger

    _registry: ClassVar[dict[str, type["Output"]]] = {}

    # Set in each subclass; must match a registered repository type.
    repository_type: str | None = None

    def __init_subclass__(cls) -> None:
        cls.logger = get_logger(cls.__name__)
        if cls.repository_type:
            existing = Output._registry.get(cls.repository_type)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"Duplicate output type '{cls.repository_type}': "
                    f"Already registered by {existing.__name__}, cannot register {cls.__name__}"
                )
            Output._registry[cls.repository_type] = cls

    def __init__(self, repository: Repository, **kwargs) -> None:
        super().__init__()

    @abstractmethod
    async def export(self, item: PipelineItem) -> OutputData:
        """Export the transformed data to a specific repository."""
        raise NotImplementedError

    @classmethod
    def create(cls, repository: Repository, **kwargs):
        """Create an output instance by repository type."""
        if not repository.repo_type:
            raise ValueError("Repository type is None")
        output_cls = cls._registry.get(repository.repo_type)
        if not output_cls:
            raise ValueError(f"Unknown repository type: {repository.repo_type}")
        return output_cls(repository, **kwargs)
