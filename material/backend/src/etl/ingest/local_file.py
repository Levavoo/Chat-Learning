from etl.ingest.base import Ingest
from etl.models import DataObject, DataType, PipelineItem, SourceObject
from etl.util.repository.local_filesystem import LocalFileSystemRepository


class LocalFileIngest(Ingest[LocalFileSystemRepository]):
    """Ingest object that uses the local file system."""

    repository_type = "Folder"

    def __init__(
        self,
        repository: LocalFileSystemRepository,
        objects: list[str] | None = None,
        path: str = "",
    ):
        super().__init__(repository, objects)
        self._path = path

    async def ingest(self) -> list[PipelineItem]:
        """Ingest data from local file system."""
        items: list[PipelineItem] = []
        file_list = (
            [obj.object_id for obj in self._repo.list_items(path=self._path)] if not self._objects else self._objects
        )

        self.logger.debug(f"Ingesting {len(file_list)} files.")
        for object_id in file_list:
            item = self._repo.get(object_id)
            if not item:
                continue
            src = SourceObject(
                name=item.name or "",
                source=item.file_path or "",
                data_type=DataType(item.file_extension),
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
