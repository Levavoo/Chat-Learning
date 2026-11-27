
import json
from pathlib import Path

import pytest

from etl.util.repository.local_filesystem import (
    FileItem,
    FileObject,
    LocalFileSystemRepository,
)


class TestFileObject:

    def test_create_with_all_fields(self):
        obj = FileObject(
            object_id="path/to/file.txt",
            name="file",
            file_extension=".txt",
            file_path="path/to/file.txt",
            file_size=100,
        )
        assert obj.object_id == "path/to/file.txt"
        assert obj.name == "file"
        assert obj.file_extension == ".txt"
        assert obj.file_path == "path/to/file.txt"
        assert obj.file_size == 100

    def test_missing_file_extension_raises_error(self):
        with pytest.raises(ValueError):
            FileObject(
                object_id="id",
                name="name",
                file_path="path",
                file_size=100,
            )  # type: ignore[arg-type]  # ty: ignore[missing-argument]


class TestFileItem:

    def test_file_path_property(self, sample_data):
        desc = FileObject(
            object_id="id",
            name="test",
            file_extension=".txt",
            file_path="some/path.txt",
            file_size=50,
        )
        item = FileItem(descriptor=desc, data=sample_data)
        assert item.file_path == "some/path.txt"

    def test_file_extension_property(self, sample_data):
        desc = FileObject(
            object_id="id",
            name="test",
            file_extension=".md",
            file_path="path.md",
            file_size=50,
        )
        item = FileItem(descriptor=desc, data=sample_data)
        assert item.file_extension == ".md"


class TestLocalFileSystemRepository:

    @pytest.fixture
    def temp_repo(self, tmp_path):
        return LocalFileSystemRepository(str(tmp_path))

    @pytest.fixture
    def populated_temp_repo(self, tmp_path):
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "data.json").write_text('{"key": "value"}')
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")
        return LocalFileSystemRepository(str(tmp_path))

    def test_init_converts_root_dir_to_absolute_path(self, tmp_path):
        repo = LocalFileSystemRepository(str(tmp_path))
        assert repo.root_dir.is_absolute()
        assert isinstance(repo.root_dir, Path)

    def test_repo_type_is_folder(self):
        assert LocalFileSystemRepository.repo_type == "Folder"

    def test_list_returns_all_files(self, populated_temp_repo):
        files = populated_temp_repo.list_items()
        assert len(files) == 3
        names = {f.name for f in files}
        assert names == {"file1", "file2", "data"}

    def test_list_with_subdirectory_path(self, populated_temp_repo):
        files = populated_temp_repo.list_items(path="subdir")
        assert len(files) == 1
        assert files[0].name == "nested"

    def test_list_with_file_extension_filter(self, populated_temp_repo):
        files = populated_temp_repo.list_items(file_extension=".json")
        assert len(files) == 1
        assert files[0].file_extension == ".json"

    def test_list_nonexistent_directory_raises_value_error(self, temp_repo):
        with pytest.raises(ValueError, match="Directory not found"):
            temp_repo.list_items(path="nonexistent")

    def test_list_returns_correct_file_metadata(self, tmp_path):
        content = "test content"
        (tmp_path / "test.txt").write_text(content)
        repo = LocalFileSystemRepository(str(tmp_path))

        files = repo.list_items()
        assert len(files) == 1
        file_obj = files[0]
        assert file_obj.object_id == "test.txt"
        assert file_obj.name == "test"
        assert file_obj.file_extension == ".txt"
        assert file_obj.file_size == len(content)

    def test_list_excludes_directories(self, tmp_path):
        (tmp_path / "file.txt").write_text("content")
        (tmp_path / "folder").mkdir()
        repo = LocalFileSystemRepository(str(tmp_path))

        files = repo.list_items()
        assert len(files) == 1
        assert files[0].name == "file"

    def test_list_empty_directory_returns_empty_list(self, temp_repo):
        files = temp_repo.list_items()
        assert files == []

    def test_get_returns_file_content(self, populated_temp_repo):
        item = populated_temp_repo.get("file1.txt")
        assert item.data == b"content1"

    def test_get_returns_correct_descriptor(self, populated_temp_repo):
        item = populated_temp_repo.get("data.json")
        assert item.descriptor.name == "data"
        assert item.descriptor.file_extension == ".json"
        assert item.descriptor.object_id == "data.json"

    def test_get_nested_file(self, populated_temp_repo):
        item = populated_temp_repo.get("subdir/nested.txt")
        assert item.data == b"nested content"

    def test_get_nonexistent_file_raises_value_error(self, temp_repo):
        with pytest.raises(ValueError, match="File not found"):
            temp_repo.get("nonexistent.txt")

    def test_get_directory_raises_value_error(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        repo = LocalFileSystemRepository(str(tmp_path))

        with pytest.raises(ValueError, match="File not found"):
            repo.get("subdir")

    def test_get_binary_file(self, tmp_path):
        binary_data = bytes(range(256))
        (tmp_path / "binary.bin").write_bytes(binary_data)
        repo = LocalFileSystemRepository(str(tmp_path))

        item = repo.get("binary.bin")
        assert item.data == binary_data

    def test_put_creates_file(self, temp_repo, tmp_path):
        desc = FileObject(
            object_id="new.txt",
            name="new",
            file_extension=".txt",
            file_path="new.txt",
            file_size=12,
        )
        item = FileItem(descriptor=desc, data=b"new content!")
        temp_repo.put(item)

        created_file = tmp_path / "new.txt"
        assert created_file.exists()
        assert created_file.read_text() == "new content!"

    def test_put_creates_subdirectory_if_needed(self, temp_repo, tmp_path):
        desc = FileObject(
            object_id="deep/nested/file.txt",
            name="file",
            file_extension=".txt",
            file_path="deep/nested/file.txt",
            file_size=7,
        )
        item = FileItem(descriptor=desc, data=b"content")
        temp_repo.put(item, path="deep/nested")

        created_file = tmp_path / "deep" / "nested" / "file.txt"
        assert created_file.exists()

    def test_put_with_metadata_creates_sidecar_file(self, temp_repo, tmp_path, sample_metadata):
        desc = FileObject(
            object_id="doc.txt",
            name="doc",
            file_extension=".txt",
            file_path="doc.txt",
            file_size=4,
            metadata=sample_metadata,
        )
        item = FileItem(descriptor=desc, data=b"data")
        temp_repo.put(item)

        meta_file = tmp_path / "doc.txt.metadata.json"
        assert meta_file.exists()

        meta_content = json.loads(meta_file.read_text())
        assert meta_content == {"metadataAttributes": sample_metadata}

    def test_put_without_metadata_creates_empty_sidecar(self, temp_repo, tmp_path):
        desc = FileObject(
            object_id="simple.txt",
            name="simple",
            file_extension=".txt",
            file_path="simple.txt",
            file_size=7,
        )
        item = FileItem(descriptor=desc, data=b"content")
        temp_repo.put(item)

        meta_file = tmp_path / "simple.txt.metadata.json"
        assert meta_file.exists()
        import json

        assert json.loads(meta_file.read_text()) == {"metadataAttributes": {}}

    def test_put_overwrites_existing_file(self, tmp_path):
        existing = tmp_path / "existing.txt"
        existing.write_text("old content")
        repo = LocalFileSystemRepository(str(tmp_path))

        desc = FileObject(
            object_id="existing.txt",
            name="existing",
            file_extension=".txt",
            file_path="existing.txt",
            file_size=11,
        )
        item = FileItem(descriptor=desc, data=b"new content")
        repo.put(item)

        assert existing.read_text() == "new content"


class TestLocalFileSystemRepositoryFactory:

    def test_create_folder_repository(self, tmp_path):
        from etl.util.repository.base import Repository

        repo = Repository.create("Folder", root_dir=str(tmp_path))
        assert isinstance(repo, LocalFileSystemRepository)
        assert repo.root_dir == tmp_path
