import pytest

from src.users.model import UserRepository


def test_create_and_get_by_username() -> None:
    repo = UserRepository()
    repo.create("alice", "alice@example.com", "hash", "salt")
    user = repo.get_by_username("alice")
    assert user is not None
    assert user.email == "alice@example.com"


def test_create_duplicate_raises() -> None:
    repo = UserRepository()
    repo.create("alice", "alice@example.com", "hash", "salt")
    with pytest.raises(ValueError):
        repo.create("alice", "other@example.com", "hash2", "salt2")


def test_get_by_id() -> None:
    repo = UserRepository()
    created = repo.create("bob", "bob@example.com", "hash", "salt")
    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.username == "bob"


def test_update_password() -> None:
    repo = UserRepository()
    repo.create("carol", "carol@example.com", "oldhash", "oldsalt")
    repo.update_password("carol", "newhash", "newsalt")
    user = repo.get_by_username("carol")
    assert user is not None
    assert user.password_hash == "newhash"
    assert user.salt == "newsalt"


def test_update_password_unknown_user_raises() -> None:
    repo = UserRepository()
    with pytest.raises(KeyError):
        repo.update_password("ghost", "hash", "salt")
