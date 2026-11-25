---
type: glossary
status: evolving
tags: [glossary, reference]
---

# Glossary

An alphabetical reference for technical vocabulary. Each entry uses **Term — classification — short definition** and corresponds to **exactly one** identically named checkbox in [[Terms]]. Definitions are introductory; consult linked learnpapers and official documentation for detail.

**Workflow:** Add or update the entry here and its checkbox in [[Terms]] together. Checkbox completion means a definition is present, not that you have mastered the topic. Alias names such as CloudWatch / AWS CloudWatch have been consolidated to prevent duplicates.

**Entries:** 335.

## A

- **A/B testing — technique:** Compare randomized variants and measure which performs better.
- **Access token — security concept:** Credential granting time- and scope-limited access to an API.
- **ACL (Access Control List) — security concept:** Rules specifying allowed or denied access to a resource. A network ACL filters traffic; other ACLs can govern files or objects.
- **Agent — AI concept:** System that plans and takes actions toward a goal using models or rules.
- **Agent search — AI technique:** Searching sources or tools during an agent's task.
- **Agent tool — AI concept:** External function or capability an agent can call.
- **ALB (Application Load Balancer) — AWS service:** Distributes application traffic using rules such as host or path.
- **Angular — framework:** TypeScript-based web application framework.
- **Angular components — framework concept:** Reusable units combining a view and its behavior.
- **Angular guards — framework feature:** Checks controlling client-side route navigation.
- **Angular interceptors — framework feature:** Functions processing HTTP requests and responses.
- **Angular reactive forms — framework feature:** Model-driven form controls with explicit state and validation.
- **API — concept:** An interface through which one program can request data or actions from another.
- **API authorizer — security component:** Checks caller identity or permission before an API operation.
- **API endpoint — concept:** Specific address and operation exposed by an API.
- **API Gateway — AWS service:** Managed entry point to publish, secure and monitor APIs.
- **API latency — performance metric:** Time between requesting an API operation and receiving its response.
- **Application — software concept:** Software that performs user or business tasks. One application can comprise a frontend, backend services, and data stores; it is not the machine running it.
- **arc42 — documentation template:** Structured template for documenting software architecture.
- **Architecture Decision Record (ADR) — documentation practice:** Short record of an architectural choice and its consequences.
- **Artifact — concept:** Output of a build or workflow, such as a binary or report.
- **Asynchronous processing — execution model:** Starting work without waiting synchronously for its completion.
- **Authentication — security concept:** Verifying an asserted user or service identity.
- **Authorization — security concept:** Deciding which actions a principal may perform.
- **Availability Zone (AZ) — AWS infrastructure concept:** One or more discrete data centers with redundant facilities in an AWS Region, designed for fault isolation from other Availability Zones.
- **AWS — platform:** Amazon's cloud platform for compute, storage, databases, networking and more.
- **AWS Amplify — AWS service:** Tools and hosting capabilities for web and mobile applications.
- **AWS Bedrock — service:** Managed AWS access to foundation models and related generative-AI capabilities.
- **AWS CDK — infrastructure framework:** Defines AWS infrastructure using programming languages and synthesizes CloudFormation templates for deployment. An AWS SDK instead provides direct API calls from code.
- **AWS CloudFormation — AWS service:** Provisions and updates infrastructure from templates, organizing related resources into stacks; AWS CDK can generate these templates.
- **AWS CloudFront — AWS service:** A CDN that delivers static and dynamic content through edge locations, caching eligible responses according to configuration and forwarding other requests to an origin.
- **AWS CloudWatch — service:** AWS monitoring service for metrics, logs and alarms.
- **AWS Cognito — AWS service:** Provides application identity capabilities, including user sign-in through user pools and temporary AWS credentials through identity pools. Application users are not automatically IAM users.
- **AWS DynamoDB — AWS service:** Managed NoSQL database supporting key-value and document data. Applications store and retrieve items using designed keys and access patterns; it is not S3 object storage.
- **AWS EC2 — AWS service:** Cloud service providing virtual computing instances.
- **AWS ECR — service:** AWS Elastic Container Registry, used to store container images.
- **AWS ECS — AWS service:** Amazon Elastic Container Service, which schedules and manages containers as tasks and services using compute capacity such as EC2 or Fargate.
- **AWS Fargate — serverless compute technology:** Runs containers with ECS or EKS without requiring you to provision the underlying servers. You still configure the workload, resource requirements, networking, and permissions.
- **AWS IAM — service/concept:** Identity and access management; in AWS, controls permissions for users and workloads.
- **AWS Lambda — AWS service:** Executes functions in response to events while AWS manages the underlying compute infrastructure. The team supplies code, dependencies, configuration, and permissions; execution environments may be reused.
- **AWS Organizations — AWS service:** Groups AWS accounts for centralized governance and consolidated billing. Organizational units can group accounts for policy management.
- **AWS Route 53 — AWS service:** Managed DNS, domain registration, and health-check capabilities. DNS records help clients locate endpoints; Route 53 does not host the application code.
- **AWS S3 — AWS service:** Managed object storage for objects in buckets. It can serve static website assets without you managing a web-server instance; it does not execute backend application code.
- **AWS S3 Vectors — AWS service:** Amazon S3 capabilities for storing and querying vector data.
- **AWS SDK — software library family:** Language-specific libraries for calling AWS APIs from application or automation code, such as reading S3 objects. Unlike CDK, an SDK does not inherently manage declarative infrastructure state.
- **AWS Secrets Manager — AWS service:** Managed storage and rotation for secrets.
- **AWS SQS — service:** AWS managed message queue for decoupling application components.
- **AWS Systems Manager (SSM) — service family:** AWS Systems Manager, for managing and operating infrastructure.
- **AWS WAF — AWS service:** Web application firewall for controlling HTTP traffic.
- **AWS X-Ray — AWS service:** Tracing service for analyzing distributed application requests.

## B

- **Backend orchestrator — architecture component:** Coordinates server-side calls to services, tools and data stores.
- **Batch processing — execution model:** Processes a collected set of records or tasks as a job, rather than handling each as an interactive user request; common on mainframes and other platforms.
- **Batching — concept:** Processing a group of items together instead of one at a time.
- **BatchSpanProcessor — library component:** OpenTelemetry component batching spans before export.
- **BM25 — retrieval algorithm:** Ranks documents for a text query using term frequency, term rarity, and document-length normalization. It is a keyword-based algorithm, not an AWS service or an embedding model.
- **Bootstrap infrastructure — infrastructure concept:** Initial resources needed to deploy further infrastructure.
- **Bot control — security concept:** Detection or restriction of automated traffic.
- **Branch — concept:** A movable Git reference identifying the latest commit on a line of work.
- **Branch protection — feature:** Rules restricting changes to selected branches, potentially requiring reviews or checks.
- **Build pipeline — DevOps process:** Automated steps turning source into validated build output.
- **Buildah — tool:** A tool for building container images.

## C

- **Cache — storage concept:** A store of reusable copies or computed results intended to reduce retrieval time or repeated work. For example, the CloudFront CDN caches eligible content at AWS edge locations rather than fetching it from the origin for every request.
- **Cache hit — caching concept:** A request finds a usable cached entry and can reuse it.
- **Cache invalidation — caching technique:** Marks or removes cached entries so subsequent requests do not reuse outdated data.
- **Cache miss — caching concept:** A request cannot use a cached entry and must obtain or compute the result elsewhere.
- **Caching — technique:** Using a cache to reuse data or computation results; requires decisions about keys, freshness, expiry, and invalidation.
- **CDN (Content Delivery Network) — technology:** A distributed network that caches and delivers content closer to users.
- **Change-based CI triggers — CI concept:** Start jobs based on particular changed paths or files.
- **Chat session — application concept:** Conversation interactions associated with one session.
- **Chunking — technique/concept:** Splitting documents into smaller units for indexing or processing.
- **Chunking by hierarchy — retrieval technique:** Split documents at structural levels such as headings.
- **Chunking by section — retrieval technique:** Divide documents along section boundaries.
- **Chunking by semantic similarity — retrieval technique:** Select chunk boundaries based on topical relatedness.
- **CI job — automation concept:** A configured unit of work executed as part of a CI pipeline.
- **CI/CD — practice/concept:** Automated checking, building, and delivery of software changes.
- **ClickHouse — database:** Column-oriented database for fast analytical queries.
- **Clone (git clone) — command:** Create a local copy of a Git repository including commit history.
- **Cloud account — cloud concept:** Isolated cloud ownership, billing and resource boundary.
- **Cloud region — cloud concept:** Geographic area where cloud services run.
- **Cocogitto — tool:** Utility supporting Conventional Commits and version workflows.
- **Cold start — execution concept:** Startup delay while initializing a new execution environment.
- **Commit — concept:** A recorded snapshot of a project with metadata and parent references.
- **Commit-msg hook — Git mechanism:** A local Git hook that can inspect or reject a proposed commit message.
- **Concurrency — execution concept:** Overlapping progress of multiple tasks, not necessarily parallel execution.
- **Container — technology:** A packaged application and its runtime dependencies that run using operating-system isolation.
- **Container image — artifact:** Packaged filesystem and metadata from which containers run.
- **Container registry — service:** Storage and distribution service for container images.
- **Containerization — technology:** OS-level isolation and packaging of applications.
- **Content safety — AI governance concept:** Policies and controls for harmful or disallowed content.
- **Context window — AI concept:** Token budget a model can handle in one context.
- **Conventional Commits — convention:** Structured commit messages such as feat and fix.
- **CORS — web security mechanism:** Browser rules for cross-origin requests using HTTP headers.
- **Cross-region inference — cloud AI concept:** Routing model inference to different cloud regions.

## D

- **Data at rest — security concept:** Information stored on disks or other media.
- **Data in transit — security concept:** Information moving between devices or services.
- **Data minimization — privacy principle:** Using no more personal data than needed for the purpose.
- **Database TTL — database feature:** Configured expiration of data after a period.
- **Dead-letter queue (DLQ) — concept:** A place to retain messages that could not be processed successfully.
- **Dependency injection — design pattern:** Providing collaborators externally rather than constructing them internally.
- **Dependency management — software process:** Declaring and updating required packages or libraries.
- **Deployment — DevOps process:** Releasing a particular application version to an environment.
- **Deployment artifact — artifact:** Packaged software used for deployment.
- **Dev environment — environment:** Setup in which software is developed and initially tested.
- **Distributed tracing — observability technique:** Following an individual request across several services.
- **DITA — documentation standard:** Darwin Information Typing Architecture for modular documentation.
- **DITA XML — markup format:** XML-based representation of DITA content.
- **DNS (Domain Name System) — network service/protocol:** Resolves domain names into records, including addresses and aliases used to locate services; DNS does not itself serve the website.
- **Docker — technology/tool:** Tooling for building and running containerized applications.
- **Docker Compose — tool:** Declarative setup for multi-container applications.
- **DSGVO / GDPR — regulation:** EU rules governing processing and protection of personal data.
- **Dynamic content — web concept:** Content generated or selected using current input or context, such as a personalized API response. Cacheability depends on its semantics and configuration.

## E

- **E2E testing — testing concept:** Testing a complete user workflow through connected components.
- **Edge location — AWS infrastructure concept:** A site in AWS's edge network used by services such as CloudFront to deliver content with low latency. It is not an Availability Zone where you deploy arbitrary EC2 instances.
- **ElastiCache — AWS service:** Managed in-memory caching service.
- **ELB (Elastic Load Balancing) — AWS service family:** Distributes incoming traffic across targets. Application Load Balancers and Network Load Balancers are different types of load balancer within this family.
- **Embedding — concept:** A numeric representation that can capture useful patterns or semantic relationships.
- **Environment variables — configuration concept:** Process-level named values used for configuration.
- **ETL (Extract, Transform, Load) — data engineering process:** Extract data, transform it and load a target system.
- **Event notification — architecture concept:** Message signaling that something occurred.
- **Event-driven architecture — architecture style:** Components react to emitted events.
- **Exponential backoff — retry strategy:** Increase retry delays progressively, often with jitter.

## F

- **Fail-closed — security principle:** Deny access when necessary checks fail.
- **Fail-open — resilience behavior:** Allow access or progress if a check fails.
- **False positive — evaluation concept:** Negative case incorrectly classified as positive.
- **Feature branch — concept:** A branch for developing changes separately before integration.
- **Feedback correlation — observability concept:** Link user feedback to its original request or trace.
- **Fetch (git fetch) — command:** Download commits and update remote-tracking references without merging the current branch.
- **Fork (GitHub) — feature:** A separate GitHub repository derived from another repository, often under another owner.
- **Forward engineering — process:** Build or implement a system or database from a model, design or specification.
- **Foundation model — AI concept:** Broadly pretrained model adaptable to many downstream tasks.
- **Framework — concept:** A reusable structure that provides conventions and components for building software.
- **Frontend — application layer:** User-facing part of an application.
- **Frontend routing — web concept:** Mapping client URLs to application views.

## G

- **Git — tool:** Distributed version-control system for tracking file changes.
- **Git tag — Git concept:** A named reference to a Git object, usually a commit marking a release.
- **GitHub — platform:** A Git hosting and collaboration platform with repositories, pull requests and automation.
- **GitHub Actions — service:** GitHub automation running workflows for CI/CD and other repository events.
- **GitHub CLI (gh) — tool:** Command-line tool for GitHub issues, pull requests and repository operations.
- **GitLab CI/CD — DevOps service:** GitLab pipelines for automated testing and delivery.
- **GitLab Runner — DevOps tool:** Agent executing configured GitLab pipeline jobs.
- **GitOps — operations practice:** Managing desired system state using version-controlled declarations.
- **Glossary enrichment — documentation process:** Adding clearer terminology definitions and context.
- **Guardrail — concept:** A control intended to restrict or check unsafe or unwanted system behavior.
- **Guardrail agent — AI architecture concept:** Component checking or constraining agent actions and outputs.

## H

- **Health check — operations concept:** Test or endpoint indicating service health.
- **History conversion — data migration concept:** Transform stored interaction history to another format.
- **Hosting — operations concept:** Making application content or functionality available through operating infrastructure. Static hosting serves files; backend hosting also executes server-side application code.
- **HTTP — protocol:** Request-response protocol used for communication on the web.
- **HTTP status code — protocol concept:** Three-digit result indicator in an HTTP response.
- **HTTPS — protocol:** HTTP protected with TLS encryption.
- **Hybrid search — retrieval technique:** Combine keyword matching and vector-based retrieval.
- **HyDE (Hypothetical Document Embeddings) — technique/concept:** Hypothetical Document Embeddings, a retrieval technique that uses a generated hypothetical answer or document to help search.

## I

- **IAM group policy — AWS security concept:** An identity-based policy attached to an IAM user group, contributing permissions for its members. It can contain allows or denies, and cannot override an applicable explicit deny or SCP restriction.
- **IAM role — AWS security concept:** Assumable AWS identity granting temporary permissions.
- **IAM trust policy — AWS security policy:** Policy specifying who can assume a role.
- **Identity provider (IdP) — security component:** Authenticates identities and provides identity assertions.
- **Inbound traffic — network concept:** Traffic arriving at the resource or boundary being considered. Always specify the perspective, such as a backend network interface.
- **Index (Git staging area) — concept:** Git's intermediate record of content selected for the next commit.
- **Infrastructure — computing concept:** Compute, storage, networking, and supporting services that allow applications to operate; it can include physical, virtual, and managed resources.
- **Infrastructure apply — IaC operation:** Executes infrastructure changes through provider APIs. In Terraform/OpenTofu it can consume a saved plan or generate a plan first.
- **Infrastructure as Code (IaC) — practice/concept:** Infrastructure as Code, the practice of defining infrastructure with versioned configuration.
- **Infrastructure drift — IaC concept:** A difference between the actual infrastructure and its declared or previously recorded state, often caused by changes outside the IaC workflow.
- **Infrastructure plan — IaC operation:** Previews proposed resource changes before applying them. Planning may read live resources but does not execute the proposed provisioning changes.
- **Infrastructure state — IaC concept:** A tool's record mapping configuration to managed resources and their attributes. Terraform/OpenTofu use it during planning and updates; it may contain sensitive data.
- **Integration test — testing concept:** Check interactions between multiple components.
- **Internet gateway — AWS networking component:** Connects a VPC to the internet. Routes, addressing, and traffic rules also determine whether a particular resource is reachable.
- **IP-based rate limiting — security control:** Limit requests according to source IP.

## J

- **Jasmine — testing framework:** JavaScript behavior-driven testing framework.
- **Jest — testing framework:** JavaScript and TypeScript testing framework.
- **Job template — CI configuration concept:** Reusable job settings inherited by other job definitions.
- **JSON — data format:** Text notation for objects, arrays and primitive values.
- **JSON Web Token (JWT) — token format:** Compact claims representation that may be signed or encrypted.

## K

- **Karma — testing tool:** JavaScript test runner commonly using browsers.
- **Knowledge base — information system:** Organized searchable body of information.
- **Knowledge base synchronization — data process:** Keep indexed knowledge aligned with its sources.

## L

- **Langfuse — tool/platform:** Observability and evaluation tooling for LLM applications.
- **Least privilege — security principle:** Grant only permissions required for a task.
- **Linting — concept:** Static checks for code style, common errors and selected correctness rules.
- **LLM (Large Language Model) — AI model:** Model trained at scale to predict and generate language tokens.
- **LLM inference — AI execution:** Run a trained language model on a prompt.
- **LLM observability — operations practice:** Track model traces, quality, cost and latency.
- **LLM prompt — AI concept:** Instructions and context supplied to a model.
- **LLM trace — observability concept:** Recorded sequence of model and tool operations.
- **Load balancer — networking component:** Distributes requests or connections among targets, often using health checks to avoid unavailable targets.
- **LocalStack — development tool:** Local implementation of selected AWS-like APIs.
- **Log filtering — operations technique:** Choose log entries by conditions or criteria.

## M

- **Main branch — concept:** A conventional primary branch name; Git repositories can use other names.
- **Mainframe — computing platform:** An enterprise computing platform designed for reliable high-volume transactions and batch processing. It can run many applications and operating-system environments; it is not itself an application or a synonym for monolithic architecture.
- **Make — tool:** Runs named build or automation targets described in a Makefile.
- **Makefile — build configuration:** File defining tasks and dependencies for make.
- **Managed service — cloud concept:** Service operated and maintained substantially by its provider.
- **Merge — operation:** Integrate changes and histories from different branches.
- **Merge conflict — concept:** A conflict Git cannot automatically reconcile when integrating changes.
- **Merge request (MR) — collaboration feature:** GitLab proposal to review and merge a branch.
- **Mermaid — tool/notation:** Text-based syntax for diagrams embedded in Markdown.
- **Microservices — architecture-style:** Divides an application into independently deployable services communicating through APIs or messaging. This adds network and operational complexity; containers or Lambda functions alone do not establish this architecture.
- **MkDocs — documentation tool:** Markdown-oriented static documentation generator.
- **Model context — AI concept:** Information available to a model during response generation.
- **ModelMessage — library type:** Structured representation of a model conversation message.
- **Modular monolith — architecture-style:** An application organized into clear internal modules but deployed as one unit; modular code does not require separately deployed services.
- **Monitoring — operations practice:** Collect metrics and events to identify system issues.
- **Monolith — architecture-style:** An application deployed as one principal unit. It can have internal modules and multiple running replicas; it does not necessarily mean one physical server.
- **Monorepo — repository strategy:** One repository holding multiple projects or packages.
- **Multi-AZ — cloud availability concept:** Deploy resources across availability zones for resilience.
- **Multi-turn conversation — AI interaction concept:** Dialogue where later messages depend on earlier ones.
- **MVC (Model–View–Controller) — architectural pattern:** Separate model data, views and controller interaction logic.

## N

- **NAT Gateway — network service:** Provide outbound connectivity for private network resources.
- **Network ACL (NACL) — AWS network control:** Subnet-level ordered allow/deny rules. It is stateless: return traffic must also be allowed by the relevant rules.
- **Network subnet — network concept:** IP network subdivision identified by a prefix.
- **Nix — tool/technology:** Reproducible package and environment management using declarative expressions.
- **Nova Lite — AI model:** Amazon Nova Lite foundation model.
- **npm — tool:** Package manager and script runner for the JavaScript ecosystem.

## O

- **Observability — operations concept:** Understand internal system behavior from logs, metrics and traces.
- **OIDC (OpenID Connect) — protocol:** OpenID Connect, an identity layer built on OAuth 2.0.
- **OpenTelemetry (OTel) — observability framework:** Vendor-neutral APIs and conventions for telemetry.
- **OpenTofu — IaC tool:** An open-source tool derived from Terraform that manages infrastructure through declarative configuration, providers, plans, and state. It is a separate project; compatibility must be checked for the versions and features used.
- **Organizational unit (OU) — AWS Organizations concept:** A grouping of AWS accounts, and optionally nested OUs, used to organize policy application. Distinct from an IAM user group.
- **Origin — CDN concept:** The configured source from which a CDN obtains content, such as an S3 bucket or an HTTP application server.
- **OTLP (OpenTelemetry Protocol) — protocol:** Protocol for transferring OpenTelemetry data.
- **Outbound traffic — network concept:** Traffic leaving the resource or boundary being considered. A backend calling another API generates outbound traffic from the backend's perspective.
- **OWASP Top 10 — security resource:** OWASP list of major web application risk categories.

## P

- **Packer — infrastructure tool:** Build repeatable virtual machine images.
- **Partial success — system behavior:** Some requested operations succeed while others fail.
- **PEP 8 — standard/concept:** Python's style guide for code formatting conventions.
- **Performance percentile (p95) — performance metric:** Value at or below which about 95 percent of observations lie.
- **PII (Personally Identifiable Information) — privacy concept:** Information that can identify an individual.
- **Pipeline — automation concept:** Series of automated build, data or processing stages.
- **Pipeline stage — CI concept:** A named group of jobs in a pipeline; its scheduling semantics depend on the platform.
- **PostgreSQL — database:** Open-source relational database.
- **Pre-commit hook — Git mechanism:** Check or script running before a commit is finalized.
- **Precision (retrieval) — retrieval metric:** Proportion of returned items that are relevant.
- **Private subnet — cloud network concept:** Subnet without a direct internet gateway route.
- **Process — operating-system concept:** A running instance of a program with execution state and resources managed by the operating system.
- **Prompt injection — AI security attack:** Untrusted text trying to override an AI application's instructions.
- **Prompt template — AI development concept:** Reusable prompt with fields populated from context.
- **Provider (IaC) — plugin concept:** A plugin through which Terraform or OpenTofu reads and manages resource types using a platform's APIs, such as AWS APIs.
- **Provisioned concurrency — AWS Lambda feature:** Pre-initialized Lambda environments reducing cold-start latency.
- **Public subnet — cloud network concept:** Subnet with an internet gateway route; exposure also needs other configuration.
- **Pull (git pull) — command:** Fetch remote commits and integrate them into a local branch.
- **Pull request (PR) — feature:** A proposal on GitHub to review and integrate commits from one branch into another.
- **Push (git push) — command:** Send Git objects and request updates to remote branch references.
- **Pydantic — Python library:** Python package for runtime validation using type annotations.
- **PydanticAI — framework:** Python framework for building model-powered applications and agents.
- **pytest — framework:** Python testing framework.

## Q

- **QA environment — software environment:** Environment for testing software quality.
- **Quality attribute — architecture concept:** Nonfunctional property such as availability or security.
- **Quality scenario — architecture technique:** Concrete example for assessing a quality attribute.
- **Query expansion — retrieval technique:** Add related terms or alternatives to a search query.
- **Queue depth — messaging metric:** Number of messages currently awaiting processing.
- **Queueing system — concept:** A system buffering work or messages so producers and consumers operate independently.

## R

- **RAG (Retrieval-Augmented Generation) — architectural pattern:** Retrieval-Augmented Generation, where retrieved content supplements an LLM prompt.
- **Rate limiting — reliability control:** Restrict requests allowed during a time window.
- **Rebase — operation:** Replay commits on a new base to make a revised history.
- **Recall (retrieval) — retrieval metric:** Proportion of relevant items that were retrieved.
- **Redis — data store:** In-memory data structure server for caching and more.
- **Regex (regular expression) — text processing concept:** Pattern language for searching and replacing text.
- **Remote (Git) — concept:** A named connection to another repository; origin is a conventional name.
- **Remote-tracking branch — concept:** A local record of the last fetched remote branch position, such as origin/main.
- **Repository pattern — design pattern:** Separate data access from application-level logic.
- **REST — architecture-style:** Architectural style using resource-oriented, stateless interactions.
- **REST API — interface concept:** Resource-oriented HTTP API following REST principles.
- **Retrieval — retrieval concept:** Find relevant data or documents for a query.
- **Retrieval reranking — technique/concept:** Reordering retrieved results using an additional relevance model.
- **Review environment — deployment environment:** Temporary deployment for reviewing proposed changes.
- **Rootless container build — security technique:** Build container images without privileged daemon access.
- **Route table — network configuration:** Rules mapping destination address ranges to network targets, determining where traffic is forwarded.
- **Ruff — tool:** Fast Python linter and formatter.

## S

- **S3 bucket — concept:** A named container for objects stored in S3.
- **S3 event notification — AWS feature:** S3 event emitted after configured object operations.
- **S3 object storage — cloud storage concept:** Store discrete objects and metadata in buckets.
- **S3 server-side encryption (SSE-S3) — AWS feature:** S3 encryption at rest using keys managed by S3.
- **S3 static website hosting — AWS feature:** Serves stored website objects such as HTML, CSS, JavaScript, and images. JavaScript can run in the browser, but S3 does not execute backend Python or PHP. The S3 website endpoint itself does not support HTTPS; HTTPS delivery needs a service such as CloudFront with an appropriate origin setup.
- **Security group — AWS network control:** Stateful allow rules for supported resources through associated network interfaces. Response traffic for tracked allowed connections is automatically permitted; security groups have no explicit deny rules.
- **Semantic versioning (SemVer) — versioning convention:** Major-minor-patch software versioning rules.
- **Server — computing concept:** Software providing a service to clients, or the physical/virtual machine hosting such software. Clarify which meaning is intended; one machine can run many server processes.
- **Serverless — execution model:** The provider provisions and manages underlying servers while the team configures and operates its workload. Servers still exist; the term does not mean every request uses a new machine or that the team has no operational responsibilities.
- **Serverless microservices — architecture style:** Independently deployed services running on managed serverless infrastructure.
- **Service control policy (SCP) — AWS Organizations policy:** Sets maximum available permissions for affected principals in member accounts; does not grant access. IAM permissions are still needed. SCPs do not restrict the management account and have documented exceptions such as service-linked roles.
- **Service layer — architectural pattern:** Layer implementing application operations and business logic.
- **Session ID — application identifier:** Identifier associated with a conversation or session.
- **Session isolation — security concept:** Keep sessions and their data separated between users.
- **Session persistence — application concept:** Maintain session state across requests or restarts.
- **Session storage — data concept:** Storage containing session-related information.
- **ShellCheck — linting tool:** Static analysis for shell scripts.
- **Single Page Application (SPA) — web architecture:** Browser app that updates views without full navigation reloads.
- **Smoke test — testing concept:** Quick checks that the core application runs.
- **SNS (Simple Notification Service) — AWS service:** Managed publish-subscribe notification service.
- **Software architecture — engineering concept:** System-level components, relationships and design constraints.
- **Source citation — documentation concept:** Reference identifying the original source of information.
- **Squash merge — operation:** Combine multiple changes into one new commit in the target branch.
- **Staging area — concept:** The contents selected for the next Git commit, also called the index.
- **Stateful application — application design concept:** Retains interaction-specific state between requests, for example in process memory. This is different from a firewall tracking network connections.
- **Stateful filtering — network security concept:** Uses tracked connection state when evaluating traffic, allowing responses to permitted connections without separate reverse-direction permission rules.
- **Stateless application — application design concept:** Can handle a request without relying on interaction-specific state retained in that particular instance from previous requests. It can still use a database or external session store.
- **Stateless filtering — network security concept:** Evaluates traffic without using prior connection state to automatically admit responses. Both directions need appropriate rules.
- **Static content — web concept:** Files served as stored rather than generated by backend code for each request. Static JavaScript files may still enable interactive behavior in the browser.
- **Static type checking — development technique:** Check type consistency without running a program.
- **Structured exception handling — programming concept:** Handling errors through defined exception control blocks.
- **System context — architecture concept:** External users and systems interacting with the system of interest.
- **System prompt — AI concept:** High-priority instructions supplied to a model by an application.

## T

- **Technical debt — engineering concept:** Future maintenance cost from design or implementation shortcuts.
- **Terraform — IaC tool:** HashiCorp's tool for defining desired infrastructure and managing resources through providers, plans, and state. It is not restricted to AWS; OpenTofu is a related but separate project.
- **Test coverage — testing metric:** Measurement of code exercised by tests; it does not prove that results were asserted correctly.
- **Test pyramid — testing strategy:** Prefer many fast unit tests and fewer broad integration and UI tests.
- **Throttling — system control:** Deliberately limit or slow work to control resource load.
- **TLS — protocol:** Cryptographic protocol for securing data in transit.
- **Token budget — AI resource concept:** Maximum number of tokens allocated to an operation.
- **Token usage — AI metric:** Count of input and output tokens processed.
- **Tool calling — AI capability:** Allow a model to request execution of external functions.
- **Tracing — observability technique:** Track execution steps and timing across a request.
- **Transaction monitor — technology:** Middleware coordinating online transactions and shared resources in enterprise systems.
- **Transaction processing — execution model:** Handles individual business operations, such as updating an account, with required consistency guarantees. Interactive transaction workloads are common on mainframes but are not exclusive to them.
- **Transform chain — data processing concept:** Sequence of operations progressively transforming an input.
- **TTL (Time to Live) — data lifecycle concept:** Expiration duration for cached or stored records.
- **ty (Python type checker) — development tool:** Python type checking utility called ty.
- **TypeScript — language:** JavaScript with a static type system.

## U

- **Unit test — testing concept:** Automated check of one small unit of behavior.
- **User pool — AWS Cognito concept:** Directory of Cognito users and authentication settings.
- **uv — tool:** Fast Python package and project manager.

## V

- **Validation — data quality process:** Check information against required rules.
- **Vector database — database concept:** Store embeddings and support similarity queries.
- **Vector search — retrieval technique:** Search by closeness of numeric vectors.
- **Vendor lock-in — architecture tradeoff:** High switching cost due to provider-specific dependencies.
- **Version bump — release process:** Increase a declared software version.
- **Virtual machine (VM) — virtualization concept:** A software-defined computer with its own guest operating system running on virtualized hardware.
- **Virtual Private Cloud (VPC) — service/concept:** Virtual Private Cloud, an isolated logical network in AWS.
- **Virtual private gateway (VGW) — AWS networking component:** A gateway attached to a VPC that can terminate AWS Site-to-Site VPN connections and support suitable Direct Connect connectivity. This is the intended term when these notes mention 'VPG gateway'.

## W

- **Web Application Firewall (WAF) — security component:** HTTP traffic filter protecting web applications.
- **WebACL — AWS security configuration:** AWS WAF rule collection controlling traffic.
- **Windows Group Policy — Windows management feature:** Centrally configures user and computer settings, commonly using Active Directory Group Policy Objects. It is not an AWS IAM group policy or an Organizations SCP.
- **Worker — execution component:** Process consuming and handling queued tasks.
- **Working tree — concept:** The files checked out for local editing in a Git repository.
- **Workload identity — security concept:** Identity assigned to a running service or application.
- **Workspace — development concept:** Area grouping project files and development configuration.

## Y

- **YAML — data format:** Human-readable serialization format commonly used for configuration.

## Sources for cloud and infrastructure terms

These introductory definitions support the planned [[Cloud, IaC, Aws/README|Cloud, IaC, and AWS library]]. They do not mark the lessons as completed.

- [AWS VPC security](https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Security.html)
- [Security group connection tracking](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)
- [AWS VPC FAQ: gateways and connectivity](https://aws.amazon.com/vpc/faqs/)
- [AWS Organizations SCPs](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)
- [S3 website hosting](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html)
- [CloudFront and edge locations](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html)
- [Fargate for ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
- [AWS CDK](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
- [OpenTofu introduction](https://opentofu.org/docs/intro/)
- [Terraform introduction](https://developer.hashicorp.com/terraform/intro)
- [IBM: mainframe workloads](https://www.ibm.com/docs/en/zos-basic-skills?topic=today-mainframe-workloads-batch-online-transaction-processing)
- [Microsoft: Windows Group Policy](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/group-policy/group-policy-overview)

## Navigation

- [[Terms]] — synchronized index and checklist
- [[Home]]
- [[Knowledge Spine]]
