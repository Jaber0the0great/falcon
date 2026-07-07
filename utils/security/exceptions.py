"""Custom security exception hierarchy.

All exceptions inherit from SecurityError. Callers can catch the base type
or handle specific failures individually.
"""


class SecurityError(Exception):
    """Base exception for all security-related failures."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ValidationError(SecurityError):
    """Raised when user input fails validation.

    Example: invalid username format, missing required field, password too short.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message, status_code)


class AuthenticationError(SecurityError):
    """Raised when the user is not authenticated.

    Example: missing session, expired token, invalid credentials.
    """

    def __init__(self, message: str = "Authentication required.", status_code: int = 401) -> None:
        super().__init__(message, status_code)


class AuthorizationError(SecurityError):
    """Raised when the user lacks permission for the requested operation.

    Example: non-admin accessing admin endpoint, non-owner modifying a resource.
    """

    def __init__(self, message: str = "Unauthorized.", status_code: int = 403) -> None:
        super().__init__(message, status_code)


class SanitizationError(SecurityError):
    """Raised when input cannot be safely sanitized.

    Example: a filename contains an unsupported encoding after sanitization.
    """

    def __init__(self, message: str = "Input could not be sanitized.", status_code: int = 400) -> None:
        super().__init__(message, status_code)
