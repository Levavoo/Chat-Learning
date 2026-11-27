import json
import logging
from io import BytesIO
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from pydantic import Field

from etl.util.repository.base import Repository, RepositoryItem, RepositoryObject

logger = logging.getLogger(__name__)


class S3BucketError(Exception):
    message_template: str = "S3 bucket error: {bucket_name}"

    def __init__(self, bucket_name: str, **kwargs):
        self.bucket_name = bucket_name
        for key, value in kwargs.items():
            setattr(self, key, value)
        super().__init__(self.message_template.format(bucket_name=bucket_name, **kwargs))


class BucketNotFoundError(S3BucketError):
    message_template = "Bucket '{bucket_name}' does not exist"


class BucketOtherRegionError(S3BucketError):
    message_template = "Bucket '{bucket_name}' exists in region '{region}', not the configured region"

    def __init__(self, bucket_name: str, region: str):
        super().__init__(bucket_name, region=region)


class BucketAccessDeniedError(S3BucketError):
    message_template = "Access denied to bucket '{bucket_name}'"


class S3Object(RepositoryObject):
    etag: str = Field(...)
    bucket_name: str = Field(...)
    file_extension: str = Field(...)


class S3Item(RepositoryItem[S3Object]):
    pass


class S3BucketRepository(Repository[S3Object, S3Item]):
    repo_type = "S3"

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name

        self._check_bucket_exists(bucket_name)

        self.bucket_name = bucket_name

    def _check_bucket_exists(self, bucket_name: str) -> None:
        client = boto3.client("s3")

        try:
            client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            code = e.response["Error"]["Code"]

            if code in {"404", "NoSuchBucket"}:
                raise BucketNotFoundError(bucket_name) from e
            elif code == "301":
                raise BucketOtherRegionError(bucket_name, e.response.get("Error", {}).get("Region", "?")) from e
            elif code == "403":
                raise BucketAccessDeniedError(bucket_name) from e
            raise
        finally:
            client.close()

    def list_items(self, **kwargs) -> list[S3Object]:
        client = boto3.client("s3")

        prefix = kwargs.get("path", "")
        file_ext = kwargs.get("file_extension", "")

        items: list[S3Object] = []
        cont_token = None
        while True:
            response = (
                client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix, ContinuationToken=cont_token)
                if cont_token
                else client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
            )

            items.extend([
                S3Object(
                    object_id=item["Key"],
                    name=Path(item["Key"]).stem,
                    etag=item["ETag"],
                    bucket_name=self.bucket_name,
                    file_extension=f".{item['Key'].rsplit('.', 1)[-1]}" if "." in item["Key"] else "",
                    metadata=item,
                )
                for item in response.get("Contents", [])
                if not item["Key"].endswith("/")
                and (item["Key"].endswith(file_ext) if file_ext else True)
            ])

            if not response["IsTruncated"]:
                break
            else:
                cont_token = response["NextContinuationToken"]

        client.close()

        return items

    def get(self, object_id: str) -> S3Item:
        client = boto3.client("s3")

        response = client.get_object(Bucket=self.bucket_name, Key=object_id)

        desc = S3Object(
            object_id=object_id,
            name=Path(object_id).stem,
            etag=response["ETag"],
            bucket_name=self.bucket_name,
            file_extension=f".{object_id.rsplit('.', 1)[-1]}" if "." in object_id else "",
            # TODO: handle metadata better
            metadata={},
        )

        item = S3Item(descriptor=desc, data=response["Body"].read())
        return item

    def _truncate_metadata_to_fit(self, metadata: dict, max_bytes: int = 1024) -> dict:
        # Bedrock caps sidecar at 1024 bytes; shed keywords (last) to fit.
        bedrock_metadata = {"metadataAttributes": metadata}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        if len(metadata_json.encode("utf-8")) <= max_bytes:
            return metadata

        if metadata.get("keywords"):
            original_keywords = metadata["keywords"]
            truncated_metadata = metadata.copy()

            if isinstance(original_keywords, list):
                keywords_list = original_keywords
            elif isinstance(original_keywords, str):
                keywords_list = original_keywords.split(", ")
            else:
                keywords_list = []

            for num_keywords in range(len(keywords_list) - 1, 0, -1):
                truncated_metadata["keywords"] = ", ".join(keywords_list[:num_keywords])
                test_bedrock = {"metadataAttributes": truncated_metadata}
                test_json = json.dumps(test_bedrock, indent=2)

                if len(test_json.encode("utf-8")) <= max_bytes:
                    logger.warning(
                        f"Truncated keywords from {len(keywords_list)} to {num_keywords} keywords "
                        f"to fit {max_bytes} byte limit (was {len(metadata_json.encode('utf-8'))} bytes)"
                    )
                    return truncated_metadata

            truncated_metadata.pop("keywords", None)
            test_bedrock = {"metadataAttributes": truncated_metadata}
            test_json = json.dumps(test_bedrock, indent=2)

            if len(test_json.encode("utf-8")) <= max_bytes:
                logger.warning(f"Removed all keywords to fit {max_bytes} byte limit")
                return truncated_metadata

        logger.error(
            f"Metadata still exceeds {max_bytes} bytes even after truncation. "
            f"Size: {len(metadata_json.encode('utf-8'))} bytes"
        )
        return metadata

    def put(self, item: S3Item, **kwargs) -> None:
        sub_path = kwargs.get("sub_path", "").strip("/")
        object_id = f"{(Path(sub_path) / item.name).as_posix()}" if sub_path else item.name
        client = boto3.client("s3")

        content_key = f"{object_id}{item.descriptor.file_extension}"
        client.upload_fileobj(BytesIO(item.data), self.bucket_name, content_key)

        # Metadata sidecar is required for S3 event-driven KB sync.
        meta_key = f"{content_key}.metadata.json"
        metadata = item.descriptor.metadata or {}
        truncated_metadata = self._truncate_metadata_to_fit(metadata)
        bedrock_metadata = {"metadataAttributes": truncated_metadata}
        metadata_bytes = json.dumps(bedrock_metadata, indent=2).encode("utf-8")
        client.upload_fileobj(BytesIO(metadata_bytes), self.bucket_name, meta_key)

        client.close()

    def list_by_stem(self, path: str, stem: str) -> list[str]:
        """List all derived object keys for a document stem.

        Matches ``{path}/{stem}/`` (main chunk folder), ``{path}/{stem}.``
        (single-file docs), and ``{path}/{stem}_`` (sub-document folders).
        """
        base = f"{path.strip('/')}/{stem}" if path else stem
        keys = [obj.object_id for obj in self.list_items(path=f"{base}/")]
        keys += [obj.object_id for obj in self.list_items(path=f"{base}.")]
        keys += [obj.object_id for obj in self.list_items(path=f"{base}_")]
        return keys

    def delete_objects(self, keys: list[str]) -> None:
        # Batches capped at 1000 (S3 DeleteObjects limit).
        if not keys:
            return
        client = boto3.client("s3")
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": [{"Key": k} for k in batch]},
            )
        client.close()
