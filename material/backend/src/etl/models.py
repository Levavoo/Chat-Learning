from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

class DataType(Enum):
    GENERIC = "binary"
    TEXT = ".txt"
    JSON = ".json"
    XML = ".xml"
    MARKDOWN = ".md"
    PDF = ".pdf"
    HTML = ".html"


@dataclass
class DataObject:
    name: str
    data: str | bytes
    data_type: DataType
    metadata: dict


@dataclass
class SourceObject:
    name: str
    data_type: DataType
    source: str
    metadata: dict


class PipelineItem(BaseModel):
    data_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source_object: SourceObject = Field(
        default_factory=lambda: SourceObject("", DataType.GENERIC, source="", metadata={})
    )
    data_object: DataObject = Field(
        default_factory=lambda: DataObject(name="", data="", data_type=DataType.GENERIC, metadata={})
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class OutputData(BaseModel):
    name: str
    output_id: str = Field(description="The id of the data in its new storage location")
    output_path: str = Field(description="The path to the data in its new storage location")
    metadata: dict = Field(default_factory=dict, description="Optional metadata of the data in its new ")
