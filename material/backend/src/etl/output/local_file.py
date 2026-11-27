from etl.models import OutputData, PipelineItem
from etl.output.base import Output
from etl.util.repository.local_filesystem import (
    FileItem,
    FileObject,
    LocalFileSystemRepository,
)


class LocalFileOutput(Output):
    """Output object that uses the local file system."""

    repository_type = "Folder"

    def __init__(self, file_system: LocalFileSystemRepository, path: str = ""):
        self._file_system = file_system
        self._path = path

    async def export(self, item: PipelineItem) -> OutputData:
        """Export pipeline item to local file system."""
        self.logger.debug(f"Exporting item '{item.name}' to local file")
        desc = FileObject(
            object_id=item.data_id,
            name=item.name,
            metadata=item.data_object.metadata,
            file_extension=item.data_object.data_type.value,
            file_path=item.source_object.source,
            file_size=0,
        )

        if isinstance(item.data_object.data, str):
            data = item.data_object.data.encode("UTF-8")
        else:
            data = item.data_object.data

        rep_item = FileItem(descriptor=desc, data=data)
        self._file_system.put(rep_item, path=self._path)
        return OutputData(
            name=item.name,
            output_id=item.data_id,
            output_path=rep_item.file_path or "",
            metadata={},
        )
