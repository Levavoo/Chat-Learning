from etl.ingest.base import Ingest
from etl.models import DataObject, DataType, PipelineItem, SourceObject
from etl.util.repository.html_scrape import HTMLRepository


class HTMLIngest(Ingest[HTMLRepository]):
    """Ingest object that uses the local file system for HTML files."""

    repository_type = "HTML"

    def __init__(
        self,
        repository: HTMLRepository,
        objects: list[str] | None = None,
        path: str = "",
    ):
        super().__init__(repository, objects)
        self._path = path  # unused; kept for interface consistency

    async def ingest(self) -> list[PipelineItem]:
        """Ingest data from HTML repository."""
        items: list[PipelineItem] = []
        if not self._objects:
            self.logger.warning("No objects specified for HTML ingest - nothing to ingest")
            return items

        file_list = self._objects

        self.logger.debug(f"Ingesting {len(file_list)} files.")
        for object_id in file_list:
            item = self._repo.get(object_id)
            if not item:
                continue
            src = SourceObject(
                name=item.name or "",
                source=item.descriptor.name or "",
                data_type=DataType.HTML,
                metadata={},
            )
            data_object = DataObject(
                name=item.name or "",
                data=item.data,
                data_type=src.data_type,
                metadata={},
            )
            items.append(
                PipelineItem(
                    data_id=item.id,
                    name=item.name or "",
                    source_object=src,
                    data_object=data_object,
                )
            )
        return items
