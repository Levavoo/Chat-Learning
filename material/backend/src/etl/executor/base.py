from abc import ABC, abstractmethod
from collections.abc import Callable

# NOTE: Unused. Future hook for environment-specific executors.


class BaseExecutor(ABC):
    """Executor that manages ETL-pipeline execution for a specific environment."""

    @abstractmethod
    async def run(self, pipeline: Callable, **kwargs):
        """Execute the pipeline."""
        raise NotImplementedError
