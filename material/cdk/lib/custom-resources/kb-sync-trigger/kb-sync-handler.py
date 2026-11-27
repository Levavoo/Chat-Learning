import logging
import os
import time

import boto3
import cfnresponse  # type: ignore[import-untyped]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_client = boto3.client("bedrock-agent")
s3_client = boto3.client("s3")


def handler(event, context):
    try:
        request_type = event["RequestType"]

        if request_type == "Delete":
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return

        if request_type in ["Create", "Update"]:
            knowledge_base_id = os.environ["KNOWLEDGE_BASE_ID"]
            data_source_id = os.environ["DATA_SOURCE_ID"]
            ingestion_bucket = os.environ["INGESTION_BUCKET"]
            sync_prefix = os.environ.get("SYNC_PREFIX", "docs/")

            logger.info(f"Starting KB sync for KB: {knowledge_base_id}, DS: {data_source_id}")

            # Check if there are documents in the ingestion bucket
            response = s3_client.list_objects_v2(Bucket=ingestion_bucket, Prefix=sync_prefix, MaxKeys=1)

            if "Contents" not in response or len(response["Contents"]) == 0:
                logger.info(f"No documents found in bucket {ingestion_bucket} with prefix {sync_prefix}")
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {"Message": "No documents to sync"})
                return

            # Start ingestion job
            ingestion_job_name = f"sync-{int(time.time())}"

            start_response = bedrock_client.start_ingestion_job(
                knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id, clientToken=ingestion_job_name
            )

            ingestion_job_id = start_response["ingestionJob"]["ingestionJobId"]
            logger.info(f"Started ingestion job: {ingestion_job_id}")

            # Wait for completion
            waiter = bedrock_client.get_waiter("ingestion_job_complete")
            waiter.wait(knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id, ingestionJobId=ingestion_job_id)

            # Get final status
            job_response = bedrock_client.get_ingestion_job(
                knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id, ingestionJobId=ingestion_job_id
            )

            status = job_response["ingestionJob"]["status"]
            logger.info(f"Ingestion job completed with status: {status}")

            if status == "COMPLETE":
                cfnresponse.send(
                    event, context, cfnresponse.SUCCESS, {"IngestionJobId": ingestion_job_id, "Status": status}
                )
            else:
                error_message = job_response["ingestionJob"].get("failureReasons", ["Unknown error"])
                cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": error_message})

    except Exception as e:
        logger.exception("Error in KB sync")
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)})
