"""Actionable adapter failures.

HTTP responses later wrap these codes. A stack trace stays in the local log.
"""


class AdapterError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
