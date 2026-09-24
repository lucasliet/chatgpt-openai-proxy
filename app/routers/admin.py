"""Administração de usuários e API keys — prefixo /admin.

Todas as rotas exigem o header ``X-Admin-Key`` (env ``ADMIN_API_KEY``). Se a
env não for definida, uma chave aleatória é gerada no boot e impressa nos
logs (visível no dashboard de logs do FastAPI Cloud).

Endpoints:

- ``GET  /admin/users`` — lista usuários (com status da credencial OAuth) e
  suas keys.
- ``POST /admin/users`` — cria usuário manualmente (body: ``{"name": ...}``);
  sem credencial OAuth até que o usuário complete o /login.
- ``DELETE /admin/users/{user_id}`` — remove usuário, credenciais e keys.
- ``GET  /admin/users/{user_id}/keys`` — lista keys do usuário.
- ``POST /admin/users/{user_id}/keys`` — cria key (body opcional
  ``{"label": ...}``); a chave completa é retornada **uma única vez**.
- ``POST /admin/keys/{key_id}/revoke`` — revoga uma key.

Contas costumam ser criadas pelo próprio fluxo de login (``/login``): o
usuário autentica a assinatura ChatGPT via OAuth e recebe a API key na hora.
"""

import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import get_session
from ..models import ApiKey, User
from ..security import (
    generate_api_key,
    hash_api_key,
    key_prefix,
    require_admin,
)

router = APIRouter(dependencies=[Depends(require_admin)])


class UserCreate(BaseModel):
    name: str


class KeyCreate(BaseModel):
    label: str = ""


def _mask(value: str) -> str:
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _credential_status(user: User) -> dict:
    if not user.access_token:
        return {"authenticated": False}
    now = int(time.time() * 1000)
    return {
        "authenticated": True,
        "account_id": _mask(user.account_id),
        "expires_at": user.expires_at,
        "expired": user.expires_at <= now,
        "has_refresh_token": bool(user.refresh_token),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _key_json(key: ApiKey) -> dict:
    return {
        "id": key.id,
        "prefix": key.prefix,
        "label": key.label,
        "created_at": key.created_at.isoformat(),
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


@router.get("/users")
def list_users(session: Annotated[Session, Depends(get_session)]):
    users = session.exec(select(User)).all()
    keys = session.exec(select(ApiKey)).all()
    keys_by_user: dict[int, list[ApiKey]] = {}
    for key in keys:
        keys_by_user.setdefault(key.user_id, []).append(key)

    return {
        "users": [
            {
                "id": user.id,
                "name": user.name,
                "created_at": user.created_at.isoformat(),
                "credential": _credential_status(user),
                "keys": [_key_json(key) for key in keys_by_user.get(user.id, [])],
            }
            for user in users
        ]
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, session: Annotated[Session, Depends(get_session)]):
    existing = session.exec(select(User).where(User.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail={"error": {"message": "Usuário já existe.", "type": "conflict"}})

    user = User(name=payload.name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"id": user.id, "name": user.name, "created_at": user.created_at.isoformat()}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, session: Annotated[Session, Depends(get_session)]):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"error": {"message": "Usuário não encontrado.", "type": "not_found"}})

    for key in session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all():
        session.delete(key)
    session.delete(user)
    session.commit()
    return None


@router.get("/users/{user_id}/keys")
def list_user_keys(user_id: int, session: Annotated[Session, Depends(get_session)]):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"error": {"message": "Usuário não encontrado.", "type": "not_found"}})

    keys = session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()
    return {"user_id": user_id, "keys": [_key_json(key) for key in keys]}


@router.post("/users/{user_id}/keys", status_code=status.HTTP_201_CREATED)
def create_user_key(
    user_id: int, payload: KeyCreate, session: Annotated[Session, Depends(get_session)]
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"error": {"message": "Usuário não encontrado.", "type": "not_found"}})

    raw_key = generate_api_key()
    api_key = ApiKey(
        user_id=user_id,
        label=payload.label,
        prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
    )
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return {
        "id": api_key.id,
        "key": raw_key,  # exibida apenas nesta resposta
        "prefix": api_key.prefix,
        "label": api_key.label,
        "created_at": api_key.created_at.isoformat(),
    }


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, session: Annotated[Session, Depends(get_session)]):
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail={"error": {"message": "Key não encontrada.", "type": "not_found"}})

    api_key.revoked_at = api_key.revoked_at or datetime.now(timezone.utc)
    session.add(api_key)
    session.commit()
    return {"id": api_key.id, "revoked_at": api_key.revoked_at.isoformat()}
