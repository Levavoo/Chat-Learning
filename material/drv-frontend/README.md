# DRV Digibro Frontend (Angular)

This is the Angular-based frontend for the DRV GenAI Project, implemented with the DRV design system components.

## Architecture Overview

This Angular frontend integrates with the existing AWS Bedrock Chat backend. It runs alongside the React frontend, providing alternative user interface implementations.

### Technology Stack

- **Angular 19.2**: Modern web framework for building the UI
- **DRV Design System 7**: Component library compliant with DRV design guidelines
- **AWS Cognito**: Authentication provider (via AWS Amplify v6)
- **AWS CloudFront**: Content delivery network for serving the application
- **AWS S3**: Storage for static assets
- **TypeScript 5.5**: Programming language
- **RxJS 7.8**: Reactive programming library for asynchronous operations

## Development

### Prerequisites

- Node.js 22+ (recommended)
- npm 10+
- Angular CLI (`npm install -g @angular/cli`)

### Local Development

1. Install dependencies:

   ```
   npm install
   ```

2. Start the development server:

   ```
   npm run dev
   ```

   Or for a specific environment:

   ```
   npm run local     # Local development configuration
   npm run dev       # Development environment
   npm run prod      # Production environment
   ```

   Navigate to `http://localhost:4200/` in your browser. The application will automatically reload when you make changes to the source files.

### Building

Run `npm run build:prod` to build the project. The build artifacts will be stored in the `dist/ng-digibro-frontend` directory.

### Running Tests

- Unit tests: `npm run test`
- Linting: `npm run lint`

## Deployment

### AWS CDK Deployment

The digibro-frontend is deployed using AWS CDK, which creates a CloudFront distribution and S3 bucket for hosting.

1. Deploy the backend first (if not already deployed):

   ```
   cd ../cdk
   cdk deploy --c envName=digibroDev BedrockRegionResourcesStack FrontendWafStack BedrockChatStack
   ```

2. Deploy the Angular frontend:
   ```
   cdk deploy --context envName=digibro-dev DRVFrontendStack
   ```

### Manual Deployment

You can also deploy the Angular frontend manually using Docker:

1. Build the Docker image:

   ```
   docker build -t digibro-frontend .
   ```

2. Run the container:
   ```
   docker run -p 4200:4200 digibro-frontend
   ```

## Environment Configuration

The application uses the `@ngx-env/builder` package to manage environment variables. Environment variables are loaded from `.env` files based on the current environment:

- `.env.local`: Local development configuration
- `.env.development`: Development environment configuration
- `.env.test`: Test environment configuration
- `.env.production`: Production environment configuration

### Environment Variables

The following environment variables are used:

| Variable                     | Description                           |
| ---------------------------- | ------------------------------------- |
| `NG_APP_API_ENDPOINT`        | API endpoint URL for backend services |
| `NG_APP_USER_POOL_ID`        | AWS Cognito User Pool ID              |
| `NG_APP_USER_POOL_CLIENT_ID` | AWS Cognito User Pool Client ID       |
| `NG_APP_REGION`              | AWS Region                            |

### Getting the Environment Variables

Given that you are having the right aws credentials configured with `aws configure sso` and you have the right aws profile

we can find the right env variables of the stack with the aws cli by getting the outputs of the cloudformations stack:

```bash
aws cloudformation --region $AWS_REGION describe-stacks --stack-name digibro-BedrockChatStack --query 'Stacks[0].Outputs' --profile $AWS_PROFILE |  jq -r '.[] | "\(.OutputKey)=\(.OutputValue)"' > .env.local
```

where `$AWS_REGION` is the default aws region of your profile and the `$AWS_PROFILE` the default aws profile.

Now just rename the env vars to the the correct variable and youre good!

### Accessing Environment Variables

In your TypeScript code, environment variables can be accessed using:

```typescript
const apiEndpoint = import.meta.env.NG_APP_API_ENDPOINT;
const userPoolId = import.meta.env.NG_APP_USER_POOL_ID;
```

Environment variables are injected by the `@ngx-env/builder` during build time.

## Integration with Backend

The Angular frontend integrates with the Bedrock Chat backend using the following methods:

1. REST API calls for data operations
2. AWS Cognito for authentication

## Contributing

Please refer to the main project's contribution guidelines when working with this codebase.

## Troubleshooting

### Common Issues

1. **Authentication errors**: Ensure the Cognito settings are correctly configured in the environment files
2. **API connection issues**: Check the proxy configuration in `proxy.conf.mjs`
3. **Build errors**: Make sure you're using a compatible Node.js version (22+ recommended)

For detailed troubleshooting, check the browser console logs and the Angular CLI output.
