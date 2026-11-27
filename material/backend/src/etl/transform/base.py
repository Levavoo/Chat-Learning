from abc import ABC, abstractmethod
from typing import ClassVar

from etl.models import DataType, PipelineItem


class Transform(ABC):
    """Base Object for all transforms.

    Subclass this object to register a new transform.
    The following class variables MUST be set:

        supported_input_types: A list of DataType this transform can accept
        output_type: The output type of this transform.
        transform_type: the typename of this transform. This is what will be used to identify this transform in the config.
    """

    supported_input_types: ClassVar[list[DataType]]
    output_type: DataType

    _registry: ClassVar[dict[str, type["Transform"]]] = {}

    transform_type: str | None = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.transform_type:
            existing = Transform._registry.get(cls.transform_type)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"Duplicate transform type '{cls.transform_type}': "
                    f"Already registered by {existing.__name__}, cannot register {cls.__name__}"
                )
            Transform._registry[cls.transform_type] = cls

    @abstractmethod
    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        """Apply a specific transform to the provided raw data.

        Args:
            item: The input PipelineItem to transform.

        Returns:
            A list of transformed PipelineItems.

        """
        raise NotImplementedError

    @classmethod
    def create(cls, transform_type: str, **kwargs) -> "Transform":
        """Create a new transform object.

        Args:
            transform_type: the type of transform to create.
            **kwargs: (optional) keyword arguments for the creation of the specified transform_type.

        Returns:
            The created Transform object

        Raises:
            ValueError: No Transform with type transform_type registered.

        """
        transform_cls = cls._registry.get(transform_type)
        if not transform_cls:
            raise ValueError(f"Unknown transform type: {transform_type}")
        return transform_cls(**kwargs)
