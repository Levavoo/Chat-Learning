# Renate CDK Infrastructure

AWS CDK infrastructure for the Renate AI Chatbot application with two separate stacks for independent deployment.

## Architecture

The infrastructure is split into **two independent stacks**:

### 1. ETL Knowledge Base Stack (`renate-etl-kb-dev`)

**Deploy once or rarely**

Contains:

- Bedrock Knowledge Base with S3 Vectors
- ETL Transform Pipeline (DITA→HTML→Markdown)
- Source S3 buckets for raw data
- Ingestion S3 buckets for processed documents
- SQS queues for ETL processing
- Lambda functions for transformations
- CloudWatch alarms for monitoring

### 2. Chatbot Stack (`renate-chatbot-dev`)

**Deploy frequently**

Contains:

- Angular Frontend (S3 + CloudFront)
- Lambda Backend (API handlers)
- API Gateway (REST API)
- Cognito User Pool (Authentication)
- Bedrock Agent Runtime
- VPC and Networking

**Connection:** The Chatbot stack imports the Knowledge Base ID from the ETL stack via CloudFormation exports.

## Deployment

### Prerequisites

```bash
npm install
npm run build
```

### Initial Deployment (First Time)

⚠️ **IMPORTANT:** Deploy stacks in this **exact order** on first deployment:

```bash
# 1. Deploy ETL Knowledge Base stack first (creates CloudFormation exports)
npx cdk deploy renate-etl-kb-dev --context env=dev

# 2. Deploy Chatbot stack (imports KB ID from ETL stack exports)
npx cdk deploy renate-chatbot-dev --context env=dev
```

**Alternative (using --all):**

```bash
# CDK respects dependency order, but manual sequence is clearer for first deployment
npx cdk deploy --all --context env=dev
```

### Regular Deployment Workflow

After initial setup, you can deploy stacks independently:

```bash
# Deploy only the chatbot stack (most common)
npx cdk deploy renate-chatbot-dev --context env=dev

# Deploy only the ETL stack (rare)
npx cdk deploy renate-etl-kb-dev --context env=dev

# Deploy both stacks
npx cdk deploy --all --context env=dev
```

### Deployment Order Requirements

⚠️ **Important:** The ETL stack must be deployed before the Chatbot stack on first deployment, because:

- Chatbot stack imports `renate-etl-kb-dev-KnowledgeBaseId` from ETL stack exports
- CloudFormation will fail if the export doesn't exist

After initial deployment, you can update either stack independently.

## Stack Outputs

### ETL Knowledge Base Stack Exports

These values are exported for use by the Chatbot stack:

- `renate-etl-kb-dev-KnowledgeBaseId` - Knowledge Base ID for queries
- `renate-etl-kb-dev-KnowledgeBaseArn` - Knowledge Base ARN
- `renate-etl-kb-dev-IngestionBucketName` - S3 bucket for processed documents
- `renate-etl-kb-dev-EtlSourceBucketName` - S3 bucket for raw data
- `renate-etl-kb-dev-ProcessingQueueUrl` - SQS queue for ETL jobs
- `renate-etl-kb-dev-TransformLambdaArn` - ETL transform function

### Chatbot Stack Outputs

- `renate-chatbot-dev-ApiUrl` - API Gateway base URL
- `renate-chatbot-dev-UserPoolId` - Cognito User Pool ID
- `renate-chatbot-dev-UserPoolClientId` - Cognito Client ID
- `renate-chatbot-dev-CloudFrontUrl` - Frontend distribution URL
- `renate-chatbot-dev-VpcId` - VPC ID

## Useful Commands

### Development

```bash
npm run build              # Compile TypeScript to JavaScript
npm run watch              # Watch for changes and compile
npm run test               # Run Jest unit tests
```

### CDK Operations

```bash
# View synthesized CloudFormation
npx cdk synth renate-etl-kb-dev --context env=dev
npx cdk synth renate-chatbot-dev --context env=dev

# Compare deployed stack with current state
npx cdk diff renate-etl-kb-dev --context env=dev
npx cdk diff renate-chatbot-dev --context env=dev

# List all stacks
npx cdk list --context env=dev

# Destroy stacks (reverse order)
npx cdk destroy renate-chatbot-dev --context env=dev
npx cdk destroy renate-etl-kb-dev --context env=dev
```

## Configuration

Stack configuration is centralized in:

- `lib/config/parameter.ts` - **Single source of truth** for all environment configurations (dev/staging/prod)
- `bin/infrastructure.ts` - Stack instantiation using centralized config
- `lib/config/kb/` - Supporting config files (chunking, ETL, seeding)

**Note:** Currently only `dev` environment is configured. Add `staging` and `prod` to `parameter.ts` when ready.

## Stack Dependencies

The Chatbot stack has an explicit dependency on the ETL stack:

```typescript
chatbotStack.addDependency(etlStack);
```

This ensures:

1. ETL stack deploys first when using `--all`
2. CloudFormation knows the deployment order
3. Exports are available before imports

## Benefits of Split Architecture

✅ **Independent deployments** - Update frontend/backend without touching KB
✅ **Faster iteration** - Chatbot stack deploys in ~5-10 min vs ~20 min for both
✅ **Cost optimization** - KB vector indexing only runs when ETL stack updates
✅ **Cleaner separation** - ETL/ML infrastructure separate from app infrastructure
✅ **Lower risk** - Changes to chatbot won't affect KB data

## Trade-offs

⚠️ **Export immutability** - Can't rename exports without recreating consumer stack
⚠️ **Deployment order** - ETL must deploy first (one-time requirement)
⚠️ **Stack dependency** - Can't delete ETL while chatbot uses its exports
