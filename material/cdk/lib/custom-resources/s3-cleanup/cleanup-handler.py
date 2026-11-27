import logging
import os

import boto3
import cfnresponse  # type: ignore[import-untyped]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")


def handler(event, context):  # noqa: C901
    try:
        request_type = event["RequestType"]

        if request_type == "Delete":
            source_bucket = os.environ["SOURCE_BUCKET"]
            ingestion_bucket = os.environ["INGESTION_BUCKET"]
            vector_bucket = os.environ["VECTOR_BUCKET"]

            logger.info("Starting cleanup for dev environment")
            logger.info(f"Source bucket: {source_bucket}")
            logger.info(f"Ingestion bucket: {ingestion_bucket}")
            logger.info(f"Vector bucket: {vector_bucket}")

            cleaned_objects = []

            # Clean source bucket (IN/ prefix only)
            try:
                response = s3_client.list_objects_v2(Bucket=source_bucket, Prefix="IN/")

                if "Contents" in response:
                    for obj in response["Contents"]:
                        s3_client.delete_object(Bucket=source_bucket, Key=obj["Key"])
                        cleaned_objects.append(f"{source_bucket}/{obj['Key']}")

                logger.info(f"Cleaned {len(cleaned_objects)} objects from source bucket")

            except Exception:
                logger.exception("Error cleaning source bucket")

            # Clean ingestion bucket (docs/ prefix only)
            try:
                docs_objects = []
                response = s3_client.list_objects_v2(Bucket=ingestion_bucket, Prefix="docs/")

                if "Contents" in response:
                    for obj in response["Contents"]:
                        s3_client.delete_object(Bucket=ingestion_bucket, Key=obj["Key"])
                        docs_objects.append(f"{ingestion_bucket}/{obj['Key']}")

                logger.info(f"Cleaned {len(docs_objects)} objects from ingestion bucket")
                cleaned_objects.extend(docs_objects)

            except Exception:
                logger.exception("Error cleaning ingestion bucket")

            # Vector bucket cleanup - only clean test vectors, not the index
            try:
                vector_objects = []
                response = s3_client.list_objects_v2(Bucket=vector_bucket, Prefix="test-data/")

                if "Contents" in response:
                    for obj in response["Contents"]:
                        s3_client.delete_object(Bucket=vector_bucket, Key=obj["Key"])
                        vector_objects.append(f"{vector_bucket}/{obj['Key']}")

                logger.info(f"Cleaned {len(vector_objects)} test objects from vector bucket")
                cleaned_objects.extend(vector_objects)

            except Exception:
                logger.exception("Error cleaning vector bucket")

            cfnresponse.send(
                event,
                context,
                cfnresponse.SUCCESS,
                {"CleanedObjects": cleaned_objects, "TotalCleaned": len(cleaned_objects)},
            )

        else:
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})

    except Exception as e:
        logger.exception("Error in cleanup")
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)})
