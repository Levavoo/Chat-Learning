from typing import Literal

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class LoggingSettings(BaseSettings):
    log_level: Literal["DEBUG", "WARNING", "INFO", "CRITICAL", "ERROR"] = Field(default="DEBUG", alias="LOG_LEVEL")

    model_config = ConfigDict(populate_by_name=True)
