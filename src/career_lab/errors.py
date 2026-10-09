"""Stable machine-readable error codes alongside the existing error messages."""


class CodedValueError(ValueError):
    code = "invalid_request"

    def __init__(self, message, *, code=None, details=None):
        super().__init__(message)
        self.code = code or self.code
        self.details = details


class InternalFailure(RuntimeError):
    """Explicitly classified invalid server state or output, never client input."""
