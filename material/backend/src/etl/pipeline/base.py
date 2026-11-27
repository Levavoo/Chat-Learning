import asyncio
from collections.abc import Sequence
from typing import Any

from etl.ingest.base import Ingest
from etl.models import PipelineItem
from etl.output.base import Output
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger
from etl.util.repository.base import Repository

pipeline_logger = get_logger("pipeline")


class Pipeline:
    """Pipeline for ETL operations."""

    def __init__(
        self,
        ingest: Sequence[Ingest],
        transforms: Sequence[Transform],
        output: Sequence[Output],
        env_variables: dict[str, Any],
    ) -> None:
        self.ingest = ingest
        self.transforms = transforms
        self.output = output
        self._validate_transform_chain()
        self.variables = env_variables

    def _validate_transform_chain(self):
        """Validate that the transforms can be executed as a valid chain.

        Raises:
            TypeError: Invalid transform chain.

        """
        for i in range(len(self.transforms) - 1):
            current = self.transforms[i]
            next_transform = self.transforms[i + 1]
            allowed_inputs = next_transform.supported_input_types
            if isinstance(allowed_inputs, list):
                if current.output_type in allowed_inputs:
                    continue
            else:
                if current == allowed_inputs:
                    continue

            raise TypeError(f"Transform mismatch: {current.__class__.__name__} -> {next_transform.__class__.__name__}")

    async def run(self):
        """Run ingests, transform chain, then exports."""
        items = await asyncio.gather(*[ingest.ingest() for ingest in self.ingest])
        items = [item for row in items for item in row]

        transformed_items_lists = await asyncio.gather(*[self._run_transforms(item) for item in items])
        transformed_items = [item for sublist in transformed_items_lists for item in sublist]

        await asyncio.gather(*[output.export(item) for item in transformed_items for output in self.output])

    async def _run_transforms(self, item: PipelineItem) -> list[PipelineItem]:
        """Run a transform chain for an item async."""
        items = [item]
        for transform in self.transforms:
            new_items = []
            for current_item in items:
                new_items.extend(transform.apply(current_item))
            items = new_items
        return items

    @classmethod
    def create(
        cls,
        pipeline_config: dict[str, Any],
        repositories: dict[str, Repository],
    ) -> "Pipeline":
        """Create a new Pipeline from config."""
        ingests = []
        ingest_targets = pipeline_config.get("sources", {})
        for target_name, configuration in ingest_targets.items():
            repo = repositories.get(configuration.pop("repository"))
            if not repo:
                pipeline_logger.warning(f"Could not find repository for ingest {target_name}")
                continue
            ingests.append(Ingest.create(repo, **configuration))

        outputs = []
        output_targets = pipeline_config.get("destinations", {})
        for target_name, configuration in output_targets.items():
            repo = repositories.get(configuration.pop("repository"))
            if not repo:
                pipeline_logger.warning(f"Could not find repository for output {target_name}")
                continue
            outputs.append(Output.create(repo, **configuration))

        transforms = []
        for transform in pipeline_config.get("transforms", []):
            transforms.append(Transform.create(transform))

        return Pipeline(ingests, transforms, outputs, {})
