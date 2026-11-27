"""Email domain validation for Cognito Pre Sign-up trigger."""

import json
import os
from typing import Any

from aws_lambda_powertools import Logger

logger = Logger()

ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR = os.environ.get("ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR")
ALLOWED_SIGN_UP_EMAIL_DOMAINS = (
    json.loads(ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR) if ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR else []
)


def check_email_domain(email: str) -> bool:
    """Check if registered user has the right email domain."""
    if email.count("@") != 1:
        return False

    domain = email.split("@")[1]
    return domain in ALLOWED_SIGN_UP_EMAIL_DOMAINS


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Cognito Pre Sign-up Lambda Trigger.

    :param event: The event from Cognito.
    :param context: The Lambda execution context.
    :return: The response to Cognito.
    """
    try:
        logger.info("Pre-signup trigger invoked", extra={"event": event})
        email = event["request"]["userAttributes"]["email"]

        if check_email_domain(email):
            logger.info("Email domain approved", extra={"email": email})
            return event
        else:
            error_message = f"Invalid email domain: {email}"
            logger.warning(error_message, extra={"email": email, "allowed_domains": ALLOWED_SIGN_UP_EMAIL_DOMAINS})
            raise ValueError(error_message)  # noqa: TRY301

    except KeyError as e:
        error_message = f"Missing required field in event: {e}"
        logger.exception(error_message, extra={"error": str(e)})
        raise ValueError(error_message) from e
    except Exception as e:
        error_message = f"Error occurred: {e}"
        logger.exception(error_message)
        raise
