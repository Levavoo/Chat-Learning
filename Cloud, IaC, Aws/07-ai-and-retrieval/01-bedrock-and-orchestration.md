---
type: learnpaper
kind: service
technology: Cloud, IaC, and AWS
chapter: 7
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Bedrock, model inference, and application orchestration

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../06-identity/03-oidc-ci-identity.md) · [Next lesson](../07-ai-and-retrieval/02-ingestion-bm25-vectors-rag.md)

This is a **service** lesson: it explains managed AWS capabilities and how an application uses them.

> **In one sentence:** A model generates output; application code decides what information it receives and what to do with the result.

## Learning objectives

Locate model execution separately from the chatbot backend and distinguish inference from orchestration.

## Why it matters

A wrong answer can originate in missing source documents, poor retrieval, incorrect history, prompt construction, or model behaviour. “The AI is broken” hides these different causes.

## Mental model

**Inference** means running a trained model on input to produce output. **Amazon Bedrock** provides managed capabilities for using foundation models and related AI features.

**Orchestration** is the application’s coordination logic: authenticate the request, validate input, fetch context, choose a model, call it, handle errors, and store the result.

A Lambda function can orchestrate a Bedrock call without containing the model’s weights or running the model locally. AWS operates the model-serving infrastructure for the managed API.

## Worked example and walkthrough

The user asks “How do I reset my password?”

1. The backend validates the user and message.
2. It retrieves the relevant FAQ passage.
3. It assembles instructions, the question, and that passage into model input.
4. It calls the chosen Bedrock model using an authorized runtime identity.
5. It processes the returned answer and usage information.
6. It stores the conversation and returns a response.

Illustrative pseudocode, not a Bedrock SDK API example:

```python
def answer_question(question, history, search, model):
    passages = search(question)
    response = model(
        question=question,
        history=history,
        context=passages,
    )
    return response
```

The injected `search` and `model` functions stand for different responsibilities. Their separation makes it possible to test whether retrieval found the right passage without requiring a model call.

## Common mistakes

A model does not automatically know the contents of an S3 bucket. Some ingestion/retrieval mechanism must make relevant content available.

Providing documents as context does not normally retrain the model. It supplies information for that invocation. A model can still produce unsupported claims, so evaluation and appropriate response handling matter.

Calling something an “agent” does not remove the need to understand its model calls, tools, permissions, and stopping conditions. An extra guardrail/model step can also add latency and cost.

## Practice

The correct FAQ passage never reaches the model. Which layer should you inspect first? Expected: ingestion/retrieval and context assembly before assuming the model needs retraining.

## Self-check

- [ ] I can explain where orchestration runs and where inference runs.
- [ ] I can name three non-model causes of a bad answer.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [Amazon Bedrock overview](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Bedrock inference](https://docs.aws.amazon.com/bedrock/latest/userguide/inference.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
