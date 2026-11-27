import json
from pathlib import Path

from etl.util.repository.base import Repository, RepositoryItem, RepositoryObject


class FileObject(RepositoryObject):
    file_extension: str
    file_path: str
    file_size: int


class FileItem(RepositoryItem[FileObject]):
    @property
    def file_path(self):
        return self.descriptor.file_path

    @property
    def file_extension(self):
        return self.descriptor.file_extension


class LocalFileSystemRepository(Repository[FileObject, FileItem]):
    repo_type = "Folder"

    def __init__(self, root_dir: str) -> None:
        self.root_dir: Path = Path(root_dir).absolute()

    def list_items(self, **kwargs) -> list[FileObject]:
        files: list[FileObject] = []
        sub_dir: str = kwargs.get("path", "")
        file_ext: str | None = kwargs.get("file_extension")
        complete_path = self.root_dir / sub_dir

        if not complete_path.exists():
            raise ValueError(f"Directory not found: {complete_path}")
        for file in complete_path.iterdir():
            if file.is_file() and (file.name.endswith(file_ext) if file_ext else True):
                files.append(
                    FileObject(
                        object_id=file.absolute().relative_to(self.root_dir).as_posix(),
                        name=file.stem.split(".")[0],
                        file_extension=file.suffix,
                        file_path=file.absolute().relative_to(self.root_dir).as_posix(),
                        file_size=file.stat().st_size,
                    )
                )
        return files

    def get(self, object_id: str) -> FileItem:
        path = self.root_dir / object_id
        if not path.exists() or path.is_dir():
            raise ValueError(f"File not found: {object_id}")
        with path.open("rb") as file:
            data = file.read()
            desc = FileObject(
                object_id=object_id,
                name=path.stem.split(".")[0],
                file_extension=path.suffix,
                file_path=path.absolute().relative_to(self.root_dir).as_posix(),
                file_size=path.stat().st_size,
            )
            item = FileItem(descriptor=desc, data=data)
            return item

    def put(self, item: FileItem, **kwargs) -> None:
        path = self.root_dir / kwargs.get("path", "") / f"{item.name}{item.file_extension}"
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="UTF-8") as file:
            file.write(item.data.decode("UTF-8"))

        # Metadata sidecar is required for S3 event-driven KB sync.
        meta_path = Path(str(path) + ".metadata.json")
        bedrock_metadata = {"metadataAttributes": item.descriptor.metadata or {}}
        with meta_path.open("w", encoding="UTF-8") as meta_file:
            json.dump(bedrock_metadata, meta_file, indent=2)

    def delete_objects(self, keys: list[str]) -> None:
        for key in keys:
            path = self.root_dir / key
            if path.exists():
                path.unlink()
