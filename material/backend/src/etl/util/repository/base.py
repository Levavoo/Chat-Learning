from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class RepositoryObject(BaseModel):
    object_id: str = Field(...)
    name: str = Field(...)
    metadata: dict[str, Any] = Field(default_factory=dict)


TDesc = TypeVar("TDesc", bound=RepositoryObject)


class RepositoryItem[TDesc: RepositoryObject](BaseModel):
    descriptor: TDesc
    data: bytes

    @property
    def id(self) -> str:
        return self.descriptor.object_id

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def metadata(self) -> dict[str, Any]:
        return self.descriptor.metadata

    model_config = ConfigDict(arbitrary_types_allowed=True)


TItem = TypeVar("TItem", bound=RepositoryItem)


class Repository[TDesc: RepositoryObject, TItem: RepositoryItem](ABC):
    _registry: ClassVar[dict[str, type["Repository"]]] = {}

    repo_type: str | None = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.repo_type:
            existing = Repository._registry.get(cls.repo_type)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"Duplicate repository type '{cls.repo_type}': "
                    f"Already registered by {existing.__name__}, cannot register {cls.__name__}"
                )
            Repository._registry[cls.repo_type] = cls

    @abstractmethod
    def list_items(self, **kwargs) -> list[TDesc]:
        raise NotImplementedError

    @abstractmethod
    def get(self, object_id: str) -> TItem:
        raise NotImplementedError

    @abstractmethod
    def put(self, item: TItem, **kwargs) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_objects(self, keys: list[str]) -> None:
        raise NotImplementedError

    @classmethod
    def create(cls, repo_type, **kwargs):
        repo_cls = cls._registry.get(repo_type)
        if not repo_cls:
            raise ValueError(f"Unknown repository type: {repo_type}")
        return repo_cls(**kwargs)
