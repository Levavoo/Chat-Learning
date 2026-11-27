import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface ConversationTableProps {
  readonly prefix: string;
  readonly envName: string;
}

export class ConversationTable extends Construct {
  public readonly tableName: string;
  public readonly table: dynamodb.TableV2;

  constructor(scope: Construct, id: string, props: ConversationTableProps) {
    super(scope, id);

    this.tableName = `${props.prefix}-conversations-${props.envName}`;

    this.table = new dynamodb.TableV2(this, 'ConversationTable', {
      tableName: this.tableName,
      partitionKey: {
        name: 'session_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'message_id',
        type: dynamodb.AttributeType.STRING,
      },
      billing: dynamodb.Billing.onDemand(),
      removalPolicy: RemovalPolicy.DESTROY,
      // Review envs: 7d; others: CONVERSATION_TTL_DAYS (default 30). DynamoDB
      // deletes within ~48h — backend filters on read for the exact cutoff.
      timeToLiveAttribute: 'ttl',
    });

    // RFC-0009 analytics GSI (domain + created_at). ProjectionType.ALL because
    // RFC-0008 topic-analytics reads `message` from projected items.
    this.table.addGlobalSecondaryIndex({
      indexName: 'domain-created_at-index',
      partitionKey: { name: 'domain', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.NUMBER },
      projectionType: dynamodb.ProjectionType.ALL,
    });
  }
}
