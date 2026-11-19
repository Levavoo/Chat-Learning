"""
Topic: Logging
Goal: Replace print with structured logs
"""

import logging

logging.basicConfig(level=logging.INFO)

logging.info("Program started")
logging.warning("Something might be wrong")
logging.error("Error occurred")