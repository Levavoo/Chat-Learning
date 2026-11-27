from unittest.mock import MagicMock

import pytest

from etl.ingest.base import Ingest
from etl.ingest.ingest_html import HTMLIngest
from etl.ingest.local_file import LocalFileIngest
from etl.ingest.s3 import S3Ingest


class TestIngestInit:
    def test_stores_repository(self):
        mock_repo = MagicMock()

        class TestIngest(Ingest):
            repository_type = None

            async def ingest(self):
                return []

        ingest = TestIngest(mock_repo, None)

        assert ingest._repo is mock_repo

    def test_stores_objects_list(self):
        mock_repo = MagicMock()
        objects = ["obj1", "obj2"]

        class TestIngest(Ingest):
            repository_type = None

            async def ingest(self):
                return []

        ingest = TestIngest(mock_repo, objects)

        assert ingest._objects == objects

    def test_stores_none_objects(self):
        mock_repo = MagicMock()

        class TestIngest(Ingest):
            repository_type = None

            async def ingest(self):
                return []

        ingest = TestIngest(mock_repo, None)

        assert ingest._objects is None


class TestIngestSubclassRegistration:
    @pytest.fixture(autouse=True)
    def preserve_registry(self):
        original_registry = dict(Ingest._registry)
        yield
        Ingest._registry = original_registry

    def test_registers_subclass_with_repository_type(self):
        class RegisteredIngest(Ingest):
            repository_type = "test_register_type"

            async def ingest(self):
                return []

        assert Ingest._registry.get("test_register_type") is RegisteredIngest

    def test_skips_registration_without_repository_type(self):
        class UnregisteredIngest(Ingest):
            repository_type = None

            async def ingest(self):
                return []

        assert UnregisteredIngest not in Ingest._registry.values()

    def test_raises_on_duplicate_repository_type(self):
        class FirstIngest(Ingest):
            repository_type = "duplicate_type"

            async def ingest(self):
                return []

        with pytest.raises(ValueError, match="Duplicate ingest type"):

            class SecondIngest(Ingest):
                repository_type = "duplicate_type"

                async def ingest(self):
                    return []

    def test_sets_logger_on_subclass(self):
        class LoggedIngest(Ingest):
            repository_type = None

            async def ingest(self):
                return []

        assert hasattr(LoggedIngest, "logger")
        assert LoggedIngest.logger is not None

    def test_allows_same_class_reregistration(self):
        class IdempotentIngest(Ingest):
            repository_type = "idempotent_type"

            async def ingest(self):
                return []

        Ingest._registry["idempotent_type"] = IdempotentIngest

        assert Ingest._registry.get("idempotent_type") is IdempotentIngest


class TestIngestFactory:
    @pytest.fixture(autouse=True)
    def preserve_registry(self):
        original_registry = dict(Ingest._registry)
        yield
        Ingest._registry = original_registry

    def test_raises_when_repository_type_is_none(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = None

        with pytest.raises(ValueError, match="Repository type is None"):
            Ingest.create(mock_repo)

    def test_raises_for_unknown_repository_type(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "unknown_type_xyz"

        with pytest.raises(ValueError, match="Unknown repository type"):
            Ingest.create(mock_repo)

    def test_returns_correct_ingest_class(self):
        class FactoryTestIngest(Ingest):
            repository_type = "factory_test_type"

            async def ingest(self):
                return []

        mock_repo = MagicMock()
        mock_repo.repo_type = "factory_test_type"

        result = Ingest.create(mock_repo, objects=["obj1"])

        assert isinstance(result, FactoryTestIngest)
        assert result._objects == ["obj1"]

    def test_passes_kwargs_to_constructor(self):
        class KwargsTestIngest(Ingest):
            repository_type = "kwargs_test_type"

            def __init__(self, repository, objects, custom_arg=None, **kwargs):
                super().__init__(repository, objects, **kwargs)
                self.custom_arg = custom_arg

            async def ingest(self):
                return []

        mock_repo = MagicMock()
        mock_repo.repo_type = "kwargs_test_type"

        result = Ingest.create(mock_repo, custom_arg="custom_value")

        assert result.custom_arg == "custom_value"  # pyright: ignore[reportAttributeAccessIssue]

    def test_objects_defaults_to_none(self):
        class DefaultTestIngest(Ingest):
            repository_type = "default_test_type"

            async def ingest(self):
                return []

        mock_repo = MagicMock()
        mock_repo.repo_type = "default_test_type"

        result = Ingest.create(mock_repo)

        assert result._objects is None


class TestIngestRegistrationVerification:
    def test_local_file_ingest_registered(self):
        assert Ingest._registry.get("Folder") is LocalFileIngest

    def test_s3_ingest_registered(self):
        assert Ingest._registry.get("S3") is S3Ingest

    def test_html_ingest_registered(self):
        assert Ingest._registry.get("HTML") is HTMLIngest

    def test_factory_creates_local_file_ingest(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "Folder"

        result = Ingest.create(mock_repo)

        assert isinstance(result, LocalFileIngest)

    def test_factory_creates_s3_ingest(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "S3"

        result = Ingest.create(mock_repo)

        assert isinstance(result, S3Ingest)

    def test_factory_creates_html_ingest(self):
        mock_repo = MagicMock()
        mock_repo.repo_type = "HTML"

        result = Ingest.create(mock_repo)

        assert isinstance(result, HTMLIngest)
