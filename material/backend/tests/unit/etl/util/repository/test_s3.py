
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from etl.util.repository.base import Repository
from etl.util.repository.s3 import (
    BucketAccessDeniedError,
    BucketNotFoundError,
    BucketOtherRegionError,
    S3BucketError,
    S3BucketRepository,
    S3Item,
    S3Object,
)


class TestS3Object:

    def test_create_with_all_fields(self):
        obj = S3Object(
            object_id="path/to/file.txt",
            name="file",
            etag='"abc123"',
            bucket_name="my-bucket",
            file_extension=".txt",
        )
        assert obj.object_id == "path/to/file.txt"
        assert obj.name == "file"
        assert obj.etag == '"abc123"'
        assert obj.bucket_name == "my-bucket"
        assert obj.file_extension == ".txt"

    def test_missing_etag_raises_error(self):
        with pytest.raises(ValueError):
            S3Object(
                object_id="id",
                name="name",
                bucket_name="bucket",
                file_extension=".txt",
            )

    def test_missing_bucket_name_raises_error(self):
        with pytest.raises(ValueError):
            S3Object(
                object_id="id",
                name="name",
                etag='"etag"',
                file_extension=".txt",
            )


class TestS3Item:

    def test_create_s3_item(self, sample_data):
        desc = S3Object(
            object_id="key.txt",
            name="key",
            etag='"etag"',
            bucket_name="bucket",
            file_extension=".txt",
        )
        item = S3Item(descriptor=desc, data=sample_data)
        assert item.data == sample_data
        assert item.id == "key.txt"
        assert item.name == "key"


class TestBucketExceptions:

    def test_all_bucket_errors_inherit_from_s3_bucket_error(self):
        assert issubclass(BucketNotFoundError, S3BucketError)
        assert issubclass(BucketOtherRegionError, S3BucketError)
        assert issubclass(BucketAccessDeniedError, S3BucketError)

    def test_bucket_not_found_error_exposes_bucket_name(self):
        error = BucketNotFoundError("test-bucket")
        assert error.bucket_name == "test-bucket"
        assert isinstance(error, S3BucketError)

    def test_bucket_other_region_error_exposes_bucket_and_region(self):
        error = BucketOtherRegionError("test-bucket", "eu-west-1")
        assert error.bucket_name == "test-bucket"
        assert error.region == "eu-west-1"  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        assert isinstance(error, S3BucketError)

    def test_bucket_access_denied_error_exposes_bucket_name(self):
        error = BucketAccessDeniedError("test-bucket")
        assert error.bucket_name == "test-bucket"
        assert isinstance(error, S3BucketError)


class TestS3BucketRepository:

    @pytest.fixture
    def mock_s3_client(self):
        with patch("boto3.client") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def s3_repo(self, mock_s3_client):
        return S3BucketRepository("test-bucket")

    def test_repo_type_is_s3(self):
        assert S3BucketRepository.repo_type == "S3"

    def test_init_calls_head_bucket(self, mock_s3_client):
        S3BucketRepository("my-bucket")
        mock_s3_client.head_bucket.assert_called_once_with(Bucket="my-bucket")

    def test_init_bucket_not_found_raises_error(self, mock_s3_client):
        mock_s3_client.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
        with pytest.raises(BucketNotFoundError):
            S3BucketRepository("nonexistent-bucket")

    def test_init_bucket_nosuchbucket_raises_error(self, mock_s3_client):
        mock_s3_client.head_bucket.side_effect = ClientError({"Error": {"Code": "NoSuchBucket"}}, "HeadBucket")
        with pytest.raises(BucketNotFoundError):
            S3BucketRepository("nonexistent-bucket")

    def test_init_bucket_other_region_raises_error(self, mock_s3_client):
        mock_s3_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "301", "Region": "us-west-2"}}, "HeadBucket"
        )
        with pytest.raises(BucketOtherRegionError):
            S3BucketRepository("other-region-bucket")

    def test_init_bucket_access_denied_raises_error(self, mock_s3_client):
        mock_s3_client.head_bucket.side_effect = ClientError({"Error": {"Code": "403"}}, "HeadBucket")
        with pytest.raises(BucketAccessDeniedError):
            S3BucketRepository("private-bucket")

    def test_init_other_client_error_propagates(self, mock_s3_client):
        mock_s3_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Server error"}}, "HeadBucket"
        )
        with pytest.raises(ClientError):
            S3BucketRepository("error-bucket")

    def test_list_returns_objects(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "file1.txt", "ETag": '"etag1"'},
                {"Key": "file2.json", "ETag": '"etag2"'},
            ],
            "IsTruncated": False,
        }

        objects = s3_repo.list_items()
        assert len(objects) == 2
        assert objects[0].object_id == "file1.txt"
        assert objects[0].file_extension == ".txt"
        assert objects[1].object_id == "file2.json"

    def test_list_with_path_prefix(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "prefix/file.txt", "ETag": '"etag"'}],
            "IsTruncated": False,
        }

        s3_repo.list_items(path="prefix/")
        mock_s3_client.list_objects_v2.assert_called_with(Bucket="test-bucket", Prefix="prefix/")

    def test_list_with_file_extension_filter(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "file1.txt", "ETag": '"etag1"'},
                {"Key": "file2.json", "ETag": '"etag2"'},
                {"Key": "file3.txt", "ETag": '"etag3"'},
            ],
            "IsTruncated": False,
        }

        objects = s3_repo.list_items(file_extension=".txt")
        assert len(objects) == 2
        assert all(obj.file_extension == ".txt" for obj in objects)

    def test_list_excludes_folder_objects(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "folder/", "ETag": '"etag1"'},
                {"Key": "file.txt", "ETag": '"etag2"'},
            ],
            "IsTruncated": False,
        }

        objects = s3_repo.list_items()
        assert len(objects) == 1
        assert objects[0].object_id == "file.txt"

    def test_list_handles_pagination(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "file1.txt", "ETag": '"etag1"'}],
                "IsTruncated": True,
                "NextContinuationToken": "token123",
            },
            {
                "Contents": [{"Key": "file2.txt", "ETag": '"etag2"'}],
                "IsTruncated": False,
            },
        ]

        objects = s3_repo.list_items()
        assert len(objects) == 2
        assert mock_s3_client.list_objects_v2.call_count == 2

    def test_list_file_without_extension_has_empty_extension(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "README", "ETag": '"etag"'}],
            "IsTruncated": False,
        }

        objects = s3_repo.list_items()
        assert objects[0].file_extension == ""

    def test_list_sets_bucket_name_in_descriptor(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "file.txt", "ETag": '"etag"'}],
            "IsTruncated": False,
        }

        objects = s3_repo.list_items()
        assert objects[0].bucket_name == "test-bucket"

    def test_get_returns_object_content(self, s3_repo, mock_s3_client, sample_data):
        mock_body = MagicMock()
        mock_body.read.return_value = sample_data
        mock_s3_client.get_object.return_value = {
            "Body": mock_body,
            "ETag": '"etag123"',
        }

        item = s3_repo.get("path/file.txt")
        assert item.data == sample_data
        mock_s3_client.get_object.assert_called_with(Bucket="test-bucket", Key="path/file.txt")

    def test_get_returns_correct_descriptor(self, s3_repo, mock_s3_client):
        mock_body = MagicMock()
        mock_body.read.return_value = b"content"
        mock_s3_client.get_object.return_value = {
            "Body": mock_body,
            "ETag": '"etag123"',
        }

        item = s3_repo.get("folder/document.pdf")
        assert item.descriptor.object_id == "folder/document.pdf"
        assert item.descriptor.name == "document"
        assert item.descriptor.file_extension == ".pdf"
        assert item.descriptor.etag == '"etag123"'
        assert item.descriptor.bucket_name == "test-bucket"

    def test_get_file_without_extension(self, s3_repo, mock_s3_client):
        mock_body = MagicMock()
        mock_body.read.return_value = b"content"
        mock_s3_client.get_object.return_value = {
            "Body": mock_body,
            "ETag": '"etag"',
        }

        item = s3_repo.get("Makefile")
        assert item.descriptor.file_extension == ""

    def test_put_uploads_content(self, s3_repo, mock_s3_client, sample_data):
        desc = S3Object(
            object_id="file.txt",
            name="file",
            etag='"etag"',
            bucket_name="test-bucket",
            file_extension=".txt",
        )
        item = S3Item(descriptor=desc, data=sample_data)

        s3_repo.put(item)

        call_args = mock_s3_client.upload_fileobj.call_args_list[0]
        uploaded_data = call_args[0][0].read()
        assert uploaded_data == sample_data
        assert call_args[0][1] == "test-bucket"
        assert call_args[0][2] == "file.txt"

    def test_put_with_sub_path(self, s3_repo, mock_s3_client, sample_data):
        desc = S3Object(
            object_id="file.txt",
            name="file",
            etag='"etag"',
            bucket_name="test-bucket",
            file_extension=".txt",
        )
        item = S3Item(descriptor=desc, data=sample_data)

        s3_repo.put(item, sub_path="folder/subfolder")

        call_args = mock_s3_client.upload_fileobj.call_args_list[0]
        assert call_args[0][2] == "folder/subfolder/file.txt"

    def test_put_with_metadata_creates_sidecar(self, s3_repo, mock_s3_client, sample_data, sample_metadata):
        desc = S3Object(
            object_id="doc.txt",
            name="doc",
            etag='"etag"',
            bucket_name="test-bucket",
            file_extension=".txt",
            metadata=sample_metadata,
        )
        item = S3Item(descriptor=desc, data=sample_data)

        s3_repo.put(item)

        assert mock_s3_client.upload_fileobj.call_count == 2
        meta_call = mock_s3_client.upload_fileobj.call_args_list[1]
        assert meta_call[0][2] == "doc.txt.metadata.json"

        meta_content = json.loads(meta_call[0][0].read().decode("utf-8"))
        assert meta_content == {"metadataAttributes": sample_metadata}

    def test_put_without_metadata_creates_empty_sidecar(self, s3_repo, mock_s3_client, sample_data):
        desc = S3Object(
            object_id="file.txt",
            name="file",
            etag='"etag"',
            bucket_name="test-bucket",
            file_extension=".txt",
        )
        item = S3Item(descriptor=desc, data=sample_data)

        s3_repo.put(item)

        assert mock_s3_client.upload_fileobj.call_count == 2

    def test_put_closes_client(self, s3_repo, mock_s3_client, sample_data):
        desc = S3Object(
            object_id="file.txt",
            name="file",
            etag='"etag"',
            bucket_name="test-bucket",
            file_extension=".txt",
        )
        item = S3Item(descriptor=desc, data=sample_data)

        s3_repo.put(item)

        mock_s3_client.close.assert_called()


class TestS3BucketRepositoryFactory:

    def test_create_s3_repository(self):
        with patch("boto3.client") as mock:
            mock.return_value = MagicMock()
            repo = Repository.create("S3", bucket_name="test-bucket")
            assert isinstance(repo, S3BucketRepository)
            assert repo.bucket_name == "test-bucket"


class TestS3BucketRepositoryDelete:

    @pytest.fixture
    def mock_s3_client(self):
        with patch("boto3.client") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def s3_repo(self, mock_s3_client):
        return S3BucketRepository("test-bucket")

    def test_delete_objects_calls_api(self, s3_repo, mock_s3_client):
        keys = ["docs/B01/B01_0000.md", "docs/B01/B01_0000.md.metadata.json"]
        s3_repo.delete_objects(keys)
        mock_s3_client.delete_objects.assert_called_once_with(
            Bucket="test-bucket",
            Delete={"Objects": [{"Key": k} for k in keys]},
        )

    def test_delete_objects_no_op_for_empty_list(self, s3_repo, mock_s3_client):
        s3_repo.delete_objects([])
        mock_s3_client.delete_objects.assert_not_called()

    def test_delete_objects_batches_over_1000(self, s3_repo, mock_s3_client):
        keys = [f"docs/doc_{i}.md" for i in range(1500)]
        s3_repo.delete_objects(keys)
        assert mock_s3_client.delete_objects.call_count == 2
        first_batch = mock_s3_client.delete_objects.call_args_list[0][1]["Delete"]["Objects"]
        second_batch = mock_s3_client.delete_objects.call_args_list[1][1]["Delete"]["Objects"]
        assert len(first_batch) == 1000
        assert len(second_batch) == 500

    def test_list_by_stem_matches_chunk_folder(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.side_effect = [
            {
                "Contents": [
                    {"Key": "docs/B01/B01_0000.md", "ETag": '"e1"'},
                    {"Key": "docs/B01/B01_0000.md.metadata.json", "ETag": '"e2"'},
                ],
                "IsTruncated": False,
            },
            # second call (single-file prefix docs/B01.) — empty
            {"IsTruncated": False},
            # third call (sub-doc prefix docs/B01_) — empty
            {"IsTruncated": False},
        ]

        keys = s3_repo.list_by_stem("docs", "B01")
        assert "docs/B01/B01_0000.md" in keys
        assert "docs/B01/B01_0000.md.metadata.json" in keys

    def test_list_by_stem_matches_note_subdocuments(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.side_effect = [
            # docs/B01/ — main chunks
            {"Contents": [{"Key": "docs/B01/B01_0000.md", "ETag": '"e1"'}], "IsTruncated": False},
            # docs/B01. — empty
            {"IsTruncated": False},
            # docs/B01_ — note sub-docs
            {
                "Contents": [
                    {"Key": "docs/B01_note_000/B01_note_000_0000.md", "ETag": '"e2"'},
                    {"Key": "docs/B01_note_000/B01_note_000_0000.md.metadata.json", "ETag": '"e3"'},
                ],
                "IsTruncated": False,
            },
        ]

        keys = s3_repo.list_by_stem("docs", "B01")
        assert "docs/B01/B01_0000.md" in keys
        assert "docs/B01_note_000/B01_note_000_0000.md" in keys
        assert "docs/B01_note_000/B01_note_000_0000.md.metadata.json" in keys

    def test_list_by_stem_matches_single_file(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.side_effect = [
            # folder prefix — empty
            {"IsTruncated": False},
            {
                "Contents": [
                    {"Key": "docs/faq.md", "ETag": '"e1"'},
                    {"Key": "docs/faq.md.metadata.json", "ETag": '"e2"'},
                ],
                "IsTruncated": False,
            },
            # underscore prefix — empty
            {"IsTruncated": False},
        ]

        keys = s3_repo.list_by_stem("docs", "faq")
        assert "docs/faq.md" in keys
        assert "docs/faq.md.metadata.json" in keys

    def test_list_by_stem_no_collision_with_longer_stem(self, s3_repo, mock_s3_client):
        mock_s3_client.list_objects_v2.side_effect = [
            {"IsTruncated": False},  # docs/B01/ — empty
            {"IsTruncated": False},  # docs/B01. — empty
            {"IsTruncated": False},  # docs/B01_ — empty
        ]

        keys = s3_repo.list_by_stem("docs", "B01")
        assert keys == []

        # Confirm the calls used exact boundary prefixes
        calls = mock_s3_client.list_objects_v2.call_args_list
        prefixes = [c.kwargs["Prefix"] for c in calls]
        assert "docs/B01/" in prefixes
        assert "docs/B01." in prefixes
        assert "docs/B01_" in prefixes
        # Must NOT contain plain "docs/B01" (would match B010)
        assert "docs/B01" not in prefixes
