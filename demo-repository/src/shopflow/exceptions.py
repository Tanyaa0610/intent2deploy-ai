"""Domain exceptions. Each maps to a specific HTTP status code via the
exception handlers registered in `main.py` — API responses are always a
clean `{"detail": "..."}` JSON body, never a raw stack trace."""
from __future__ import annotations


class ShopFlowError(Exception):
    """Base class for all domain errors. `status_code` drives the HTTP
    response; subclasses should not be caught generically by API code."""

    status_code: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ShopFlowError):
    status_code = 404


class ValidationFailedError(ShopFlowError):
    status_code = 400


class ConflictError(ShopFlowError):
    """A business-rule conflict: the request is well-formed, but the
    current state of the system does not allow it (e.g. cancelling a
    shipped order, refunding more than was captured)."""

    status_code = 409


class UnauthenticatedError(ShopFlowError):
    status_code = 401


class ForbiddenError(ShopFlowError):
    status_code = 403


class PaymentProviderError(ShopFlowError):
    """Raised when the external payment provider cannot complete a
    charge (timeout, decline, etc.) after any retry policy is exhausted."""

    status_code = 502
