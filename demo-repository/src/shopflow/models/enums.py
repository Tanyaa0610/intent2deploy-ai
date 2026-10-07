from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class NotificationType(str, Enum):
    USER_REGISTERED = "USER_REGISTERED"
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    LOW_INVENTORY = "LOW_INVENTORY"
    REFUND_COMPLETED = "REFUND_COMPLETED"
