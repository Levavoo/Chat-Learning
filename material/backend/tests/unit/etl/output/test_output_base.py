from unittest.mock import MagicMock

import pytest

from etl.output.base import Output
from etl.output.local_file import LocalFileOutput
from etl.output.s3 import S3BucketOutput


class TestOutputInit:
    def test_init_accepts_repository(self):
        mock_repo = MagicMock()

        class TestOutput(Output):
            repository_type = None

            async def export(self, item):
                return MagicMock()

        TestOutput(mock_repo)

    def test_init_accepts_kwargs(self):
        mock_repo = MagicMock()

        class TestOutput(Output):
            repository_type = None

            async def export(self, item):
                return MagicMock()

        TestOutput(mock_repo, extra_param="value")


class TestOutputSubclassRegistration:
    @pytest.fixture(autouse=True)
    def preserve_registry(self):
        original_registry = dict(Output._registry)
        yield
        Output._registry = original_registry

    def test_registers_subclass_with_repository_type(self):
        class RegisteredOutput(Output):
            repository_type = "test_output_type"

            async def export(self, item):
                return MagicMock()

        assert Output._registry.get("test_output_type") is RegisteredOutput

    def test_skips_registration_without_repository_type(self):
        class UnregisteredOutput(Output):
            repository_type = None

            async def export(self, item):
                return MagicMock()

        assert UnregisteredOutput not in Output._registry.values()

    def test_raises_on_duplicate_repository_type(self):
        class FirstOutput(Output):
            repository_type = "duplicate_output_type"

            async def export(self, item):
                return MagicMock()

        with pytest.raises(ValueError, match="Duplicate output type"):

            class SecondOutput(Output):
                repository_type = "duplicate_output_type"

                async def export(self, item):
                    return MagicMock()

    def test_sets_logger_on_subclass(self):
        class LoggedOutput(Output):
            repository_type = None

            async def export(self, item):
                return MagicMock()

        assert hasattr(LoggedOutput, "logger")
        assert LoggedOutput.logger is not None

    def test_allows_same_class_reregistration(self):
        class IdempotentOutput(Output):
            repository_type = "idempotent_output_type"

            async def export(self, item):
                return MagicMock()

        Output._registry["idempotent_output_type"] = IdempotentOutput

        assert Output._registry.get("idempotent_output_type") is IdempotentOutput


class TestOutputFactory:
    @pytest.fixture(autouse=True)
    def preserve_registry(self):
        original_registry = dict(Output._registry)
        yield
        Output._registry = original_registry

    def test_raises_when_repository_type_is_none(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = None

        with pytest.raises(ValueError, match="Repository type is None"):
            Output.create(mock_repo)

    def test_raises_for_unknown_repository_type(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "unknown_output_type_xyz"

        with pytest.raises(ValueError, match="Unknown repository type"):
            Output.create(mock_repo)

    def test_returns_correct_output_class(self):
        class FactoryTestOutput(Output):
            repository_type = "factory_output_test"

            def __init__(self, repository, **kwargs):
                super().__init__(repository, **kwargs)
                self.repo = repository

            async def export(self, item):
                return MagicMock()

        mock_repo = MagicMock()
        mock_repo.repo_type = "factory_output_test"

        result = Output.create(mock_repo)

        assert isinstance(result, FactoryTestOutput)
        assert result.repo is mock_repo

    def test_passes_kwargs_to_constructor(self):
        class KwargsTestOutput(Output):
            repository_type = "kwargs_output_test"

            def __init__(self, repository, custom_arg=None, **kwargs):
                super().__init__(repository, **kwargs)
                self.custom_arg = custom_arg

            async def export(self, item):
                return MagicMock()

        mock_repo = MagicMock()
        mock_repo.repo_type = "kwargs_output_test"

        result = Output.create(mock_repo, custom_arg="custom_value")

        assert result.custom_arg == "custom_value"  # pyright: ignore[reportAttributeAccessIssue]


class TestOutputRegistrationVerification:
    def test_local_file_output_registered(self):
        assert Output._registry.get("Folder") is LocalFileOutput

    def test_s3_bucket_output_registered(self):
        assert Output._registry.get("S3") is S3BucketOutput

    def test_factory_creates_local_file_output(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "Folder"

        result = Output.create(mock_repo)

        assert isinstance(result, LocalFileOutput)

    def test_factory_creates_s3_bucket_output(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "S3"

        result = Output.create(mock_repo)

        assert isinstance(result, S3BucketOutput)
