from etl.models import OutputData, PipelineItem
from etl.output.base import Output
from etl.util.repository.s3 import S3BucketRepository, S3Item, S3Object


class S3BucketOutput(Output):
    """Output object that uses a S3 Bucket repository."""

    repository_type = "S3"

    def __init__(self, repository: S3BucketRepository, path: str = "") -> None:
        self._repository = repository
        self._path = path

    async def export(self, item: PipelineItem) -> OutputData:
        """Export pipeline item to S3 bucket."""
        self.logger.info(f"Exporting item {item.name} to S3 bucket {self._repository.bucket_name} at path {self._path}")
        desc = S3Object(
            object_id=item.data_object.name,
            name=item.name,
            etag="",
            bucket_name="",
            file_extension=item.data_object.data_type.value,
            metadata=item.data_object.metadata,
        )
        if isinstance(item.data_object.data, str):
            data = item.data_object.data.encode("UTF-8")
        else:
            data = item.data_object.data

        s3_item = S3Item(descriptor=desc, data=data)
        self._repository.put(s3_item, sub_path=self._path)
        return OutputData(name=item.name, output_id=item.data_id, output_path="")
