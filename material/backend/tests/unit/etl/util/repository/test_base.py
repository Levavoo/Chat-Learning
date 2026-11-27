
import pytest

from etl.util.repository.base import Repository, RepositoryItem, RepositoryObject


class TestRepositoryObject:

    def test_create_with_required_fields(self):
        obj = RepositoryObject(object_id="id1", name="test")
        assert obj.object_id == "id1"
        assert obj.name == "test"
        assert obj.metadata == {}

    def test_create_with_metadata(self, sample_metadata):
        obj = RepositoryObject(object_id="id1", name="test", metadata=sample_metadata)
        assert obj.metadata == sample_metadata

    def test_missing_object_id_raises_validation_error(self):
        with pytest.raises(ValueError):
            RepositoryObject(name="test")

    def test_missing_name_raises_validation_error(self):
        with pytest.raises(ValueError):
            RepositoryObject(object_id="id1")


class TestRepositoryItem:

    def test_id_property_returns_descriptor_object_id(self, sample_data):
        desc = RepositoryObject(object_id="test-id", name="test-name")
        item = RepositoryItem(descriptor=desc, data=sample_data)
        assert item.id == "test-id"

    def test_name_property_returns_descriptor_name(self, sample_data):
        desc = RepositoryObject(object_id="test-id", name="test-name")
        item = RepositoryItem(descriptor=desc, data=sample_data)
        assert item.name == "test-name"

    def test_metadata_property_returns_descriptor_metadata(self, sample_data, sample_metadata):
        desc = RepositoryObject(object_id="test-id", name="test-name", metadata=sample_metadata)
        item = RepositoryItem(descriptor=desc, data=sample_data)
        assert item.metadata == sample_metadata

    def test_data_is_stored_as_bytes(self, sample_data):
        desc = RepositoryObject(object_id="id", name="name")
        item = RepositoryItem(descriptor=desc, data=sample_data)
        assert item.data == sample_data
        assert isinstance(item.data, bytes)


class TestRepositoryRegistry:

    def test_create_with_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown repository type"):
            Repository.create("NonExistentType")

    def test_duplicate_repo_type_raises_value_error(self):

        class DummyRepo1(Repository):
            repo_type = "TestDuplicate"

            def list_items(self, **kwargs):
                return []

            def get(self, object_id):
                pass

            def put(self, item, **kwargs):
                pass

            def delete_objects(self, keys):
                pass

        with pytest.raises(ValueError, match="Duplicate repository type"):

            class DummyRepo2(Repository):
                repo_type = "TestDuplicate"

                def list_items(self, **kwargs):
                    return []

                def get(self, object_id):
                    pass

                def put(self, item, **kwargs):
                    pass

                def delete_objects(self, keys):
                    pass

        # Cleanup
        del Repository._registry["TestDuplicate"]

    def test_subclass_without_repo_type_not_registered(self):
        initial_registry_keys = set(Repository._registry.keys())

        class UnregisteredRepo(Repository):
            def list_items(self, **kwargs):
                return []

            def get(self, object_id):
                pass

            def put(self, item, **kwargs):
                pass

            def delete_objects(self, keys):
                pass

        assert set(Repository._registry.keys()) == initial_registry_keys

    def test_create_returns_correct_repository_instance(self):

        class FactoryTestRepo(Repository):
            repo_type = "FactoryTest"

            def __init__(self, test_param: str):
                self.test_param = test_param

            def list_items(self, **kwargs):
                return []

            def get(self, object_id):
                pass

            def put(self, item, **kwargs):
                pass

            def delete_objects(self, keys):
                pass

        repo = Repository.create("FactoryTest", test_param="value")
        assert isinstance(repo, FactoryTestRepo)
        assert repo.test_param == "value"

        # Cleanup
        del Repository._registry["FactoryTest"]

    def test_registered_repository_types_exist(self):
        # Import to trigger registration
        from etl.util.repository import html_scrape, local_filesystem, s3  # noqa: F401

        assert "S3" in Repository._registry
        assert "Folder" in Repository._registry
        assert "HTML" in Repository._registry
