
import pytest


@pytest.fixture
def base_metadata() -> dict:
    return {"source": "test.md", "doc_type": "test"}


@pytest.fixture
def markdown_with_h2_sections() -> str:
    return """# Document Title

Introduction paragraph.

## Section One

Content for section one.

## Section Two

Content for section two.

## Section Three

Content for section three.
"""


@pytest.fixture
def markdown_with_h2_and_h3() -> str:
    return """# Document Title

## Main Section

Intro to main section.

### Subsection A

Content for subsection A.

### Subsection B

Content for subsection B.

## Another Section

Some other content.
"""


@pytest.fixture
def markdown_with_table() -> str:
    return """## Section

| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |
"""


@pytest.fixture
def markdown_with_tip_note() -> str:
    return """## Section

**Unser Tipp**

This is a helpful tip.
"""


@pytest.fixture
def markdown_with_important_note() -> str:
    return """## Section

**Bitte beachten Sie**

This is important.
"""


@pytest.fixture
def glossary_content() -> str:
    return """# Glossary

API

Application Programming Interface. A set of protocols and tools.

SDK

Software Development Kit. A collection of tools for development.

REST

Representational State Transfer. An architectural style.
"""


@pytest.fixture
def large_section_content() -> str:
    return "## Large Section\n\n" + ("Lorem ipsum dolor sit amet. " * 200)
