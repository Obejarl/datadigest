"""Accounts mode: your own account (API token, password) and, for administrators, the users."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datadigest import accounts
from datadigest.api.auth import Identity, current_identity, require_admin
from datadigest.db import get_db
from datadigest.models import Dataset, Role, User

router = APIRouter(prefix="/api", tags=["accounts"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    has_token: bool = False
    datasets: int = 0
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class UserIn(BaseModel):
    email: str
    password: str
    role: Role = Role.MEMBER


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


def _out(user: User, datasets: int = 0) -> UserOut:
    out = UserOut.model_validate(user)
    out.has_token, out.datasets = user.token_hash is not None, datasets
    return out


def _me(identity: Identity | None, db: Session) -> User:
    if identity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Accounts are not switched on (AUTH_MODE=accounts)")
    return db.get(User, identity.user_id)


def _user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _bad_request(exc: accounts.AccountError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


# ---------------------------------------------------------------- your own account


@router.get("/me", response_model=UserOut)
def me(identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)):
    user = _me(identity, db)
    count = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_id == user.id))
    return _out(user, count)


@router.post("/me/token")
def create_token(identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)):
    """Make a new API token (replacing the old one). It is shown this once and cannot be read again."""
    user = _me(identity, db)
    token, user.token_hash = accounts.new_token()
    db.commit()
    return {"token": token}


@router.delete("/me/token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)):
    _me(identity, db).token_hash = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordIn, identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)
):
    user = _me(identity, db)
    if not accounts.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The current password is not correct")
    try:
        accounts.check_password_rules(body.new_password)
    except accounts.AccountError as exc:
        raise _bad_request(exc) from exc
    user.password_hash = accounts.hash_password(body.new_password)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- administrators


@router.get("/users", response_model=list[UserOut])
def list_users(_admin: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(Dataset.owner_id, func.count())
            .where(Dataset.owner_id.is_not(None))
            .group_by(Dataset.owner_id)
        ).all()
    )
    return [_out(u, counts.get(u.id, 0)) for u in db.scalars(select(User).order_by(User.created_at))]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, _admin: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return _out(accounts.create_user(db, body.email, body.password, body.role))
    except accounts.AccountError as exc:
        raise _bad_request(exc) from exc


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    admin: Identity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _user(db, user_id)
    # You cannot lock yourself out, so there is always at least one working administrator.
    if user.id == admin.user_id and (body.role == Role.MEMBER or body.is_active is False):
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot demote or disable your own account")
    if body.password is not None:
        try:
            accounts.check_password_rules(body.password)
        except accounts.AccountError as exc:
            raise _bad_request(exc) from exc
        user.password_hash = accounts.hash_password(body.password)
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    return _out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, admin: Identity = Depends(require_admin), db: Session = Depends(get_db)):
    """Removes the account and every dataset it owns."""
    user = _user(db, user_id)
    if user.id == admin.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete your own account")
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
