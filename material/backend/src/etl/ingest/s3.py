from etl.ingest.base import Ingest
from etl.models import DataObject, DataType, PipelineItem, SourceObject
from etl.util.repository.s3 import S3BucketRepository


class S3Ingest(Ingest[S3BucketRepository]):
    """Ingest object that uses a S3 Bucket repository."""

    repository_type = "S3"

    def __init__(
        self,
        repository: S3BucketRepository,
        objects: list[str] | None = None,
        path: str = "",
    ) -> None:
        super().__init__(repository, objects)
        self._root_dir = path

    async def ingest(self) -> list[PipelineItem]:
        """Ingest data from S3 bucket."""
        if not self._objects:
            object_list = [obj.object_id for obj in self._repo.list_items(path=self._root_dir)]
        else:
            object_list = self._objects

        items = [self._repo.get(s3_object) for s3_object in object_list]
        items = [item for item in items if item]

        sources = [
            SourceObject(
                # Strip spaces so chunk folder names match _compute_stem.
                name=(item.name or "").replace(" ", ""),
                data_type=DataType(item.descriptor.file_extension),
                source=f"s3://{item.descriptor.bucket_name}/{item.name}",
                metadata=item.metadata,
            )
            for item in items
        ]
        data_objs = [
            DataObject(
                name=(item.name or "").replace(" ", ""),
                data=item.data,
                data_type=DataType(item.descriptor.file_extension),
                metadata=item.metadata,
            )
            for item in items
        ]

        return [
            PipelineItem(name=s.name, source_object=s, data_object=d) for s, d in zip(sources, data_objs, strict=True)
        ]
