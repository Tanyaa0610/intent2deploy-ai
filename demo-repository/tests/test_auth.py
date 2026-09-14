import pytest

from src.auth.service import AuthService, InvalidCredentialsError
from src.users.model import UserRepository


@pytest.fixture
def auth_service() -> AuthService:
    return AuthService(UserRepository())


def test_register_creates_user(auth_service: AuthService) -> None:
    user = auth_service.register("alice", "alice@example.com", "correcthorse1")
    assert user.username == "alice"
    assert user.email == "alice@example.com"


def test_register_duplicate_username_raises(auth_service: AuthService) -> None:
    auth_service.register("alice", "alice@example.com", "correcthorse1")
    with pytest.raises(ValueError):
        auth_service.register("alice", "alice2@example.com", "anotherpass1")


def test_login_success_returns_token(auth_service: AuthService) -> None:
    auth_service.register("bob", "bob@example.com", "secretpass1")
    token = auth_service.login("bob", "secretpass1")
    assert isinstance(token, str) and len(token) > 10


def test_login_wrong_password_raises(auth_service: AuthService) -> None:
    auth_service.register("bob", "bob@example.com", "secretpass1")
    with pytest.raises(InvalidCredentialsError):
        auth_service.login("bob", "wrongpassword")


def test_login_unknown_user_raises(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.login("ghost", "whatever")


def test_validate_token_roundtrip(auth_service: AuthService) -> None:
    auth_service.register("carol", "carol@example.com", "passw0rd1")
    token = auth_service.login("carol", "passw0rd1")
    assert auth_service.validate_token(token) == "carol"


def test_validate_token_unknown_returns_none(auth_service: AuthService) -> None:
    assert auth_service.validate_token("not-a-real-token") is None


def test_logout_invalidates_token(auth_service: AuthService) -> None:
    auth_service.register("dave", "dave@example.com", "passw0rd1")
    token = auth_service.login("dave", "passw0rd1")
    auth_service.logout(token)
    assert auth_service.validate_token(token) is None
