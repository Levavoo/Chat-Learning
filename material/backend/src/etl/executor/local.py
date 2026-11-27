import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from etl.executor.base import BaseExecutor


class LocalThreadedExecutor(BaseExecutor):
    """Local executor using thread pool."""

    def __init__(self, num_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=num_workers)

    async def run(self, pipeline: Callable, **kwargs):
        """Execute pipeline in thread pool."""
        self._executor.submit(self._run_pipeline, pipeline, **kwargs)

    def _run_pipeline(self, pipeline: Callable, **kwargs):
        pipeline_obj = pipeline(**kwargs)
        asyncio.run(pipeline_obj.run())
