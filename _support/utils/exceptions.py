"""Custom exception classes for consistent error responses."""


class AppError(Exception):
    """Base exception for WarmPath application errors."""

    def __init__(self, message: str, code: str, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message=message, code="UNAUTHORIZED", status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message=message, code="FORBIDDEN", status_code=403)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message=message, code="RATE_LIMIT_EXCEEDED", status_code=429)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message=message, code="VALIDATION_ERROR", status_code=422)


class GoneError(AppError):
    def __init__(self, message: str = "This resource is no longer available"):
        super().__init__(message=message, code="GONE", status_code=410)
