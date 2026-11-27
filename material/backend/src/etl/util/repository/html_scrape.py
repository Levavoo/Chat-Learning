from etl.util.repository.base import Repository, RepositoryItem, RepositoryObject


class HTMLObject(RepositoryObject):
    pass


class HTMLItem(RepositoryItem[HTMLObject]):
    pass


class HTMLRepository(Repository[HTMLObject, HTMLItem]):
    repo_type = "HTML"

    def __init__(self, root_url: str) -> None:
        self.root_url: str = root_url.rstrip("/") + "/"

    def list_items(self, **kwargs) -> list[HTMLObject]:
        raise NotImplementedError("Listing is not supported for HTMLRepository.")

    def get(self, object_id: str) -> HTMLItem:
        url = self.root_url + object_id.lstrip("/")
        import requests

        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            raise ValueError(f"Failed to retrieve {object_id}")

        data = response.content
        desc = HTMLObject(
            object_id=object_id,
            name=object_id.split("/")[-1],
            metadata={"source_url": url},
        )
        return HTMLItem(descriptor=desc, data=data)

    def put(self, item: HTMLItem, **kwargs) -> None:
        raise NotImplementedError("Putting is not supported for HTMLRepository.")

    def delete_objects(self, keys: list[str]) -> None:
        raise NotImplementedError("Deleting is not supported for HTMLRepository.")
