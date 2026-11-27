from pydantic import ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings


class AwsSettings(BaseSettings):
    access_key_id: SecretStr = Field(..., alias="AWS_ACCESS_KEY_ID")
    secret_access_key: SecretStr = Field(..., alias="AWS_SECRET_ACCESS_KEY")
    region: str = Field(..., alias="AWS_DEFAULT_REGION")

    model_config = ConfigDict(populate_by_name=True)
