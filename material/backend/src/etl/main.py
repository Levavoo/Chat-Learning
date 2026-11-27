import asyncio

from dotenv import load_dotenv

from etl.config.settings import settings
from etl.pipeline.base import Pipeline
from etl.pipeline.router import initialize_router
from etl.util.logging_setup import get_logger, set_global_loglevel
from etl.util.repository.base import Repository

logger = get_logger(__name__)


def create_repositories(router) -> dict[str, Repository]:
    repos: dict[str, Repository] = {}
    for name, config in router.list_repositories().items():
        try:
            repos[name] = Repository.create(config.type, **config.to_kwargs())
        except Exception as exc:
            logger.warning(f"Could not initialize repository {name}: {exc}")
    return repos


def build_manual_pipeline_config(route_config, pipeline_config, available_repos: set[str]) -> dict:
    repositories = route_config.match.get("repositories", [])
    if not isinstance(repositories, list):
        repositories = [repositories] if repositories else []

    objects = route_config.pipeline.config.get("objects")

    return {
        "transforms": pipeline_config.transforms,
        "sources": {
            repo_name: {
                "repository": repo_name,
                "path": ".",
                **(({"objects": objects}) if objects else {}),
            }
            for repo_name in repositories
            if repo_name in available_repos
        },
        "destinations": {
            name: {"repository": dest.repository, "path": dest.path} for name, dest in route_config.destinations.items()
        },
    }


async def run_manual_routes(router, repos: dict[str, Repository]) -> None:
    manual_routes = router.get_routes_by_criteria(source="manual")

    if not manual_routes:
        logger.info("No manual routes defined")
        return

    for route_name, route_config in manual_routes.items():
        logger.info(f"Processing route: {route_name}")

        pipeline_config = router.get_pipeline(route_config.pipeline.name)
        if not pipeline_config:
            logger.warning(f"Pipeline {route_config.pipeline.name} not found for route {route_name}")
            continue

        config = build_manual_pipeline_config(route_config, pipeline_config, set(repos.keys()))

        try:
            pipeline = Pipeline.create(config, repos)
            await pipeline.run()
            logger.info(f"Completed route: {route_name}")
        except Exception:
            logger.exception(f"Failed to run route {route_name}")


async def main():
    router = initialize_router()
    repos = create_repositories(router)
    await run_manual_routes(router, repos)


if __name__ == "__main__":
    load_dotenv()
    set_global_loglevel(settings.logging.log_level)
    asyncio.run(main())
