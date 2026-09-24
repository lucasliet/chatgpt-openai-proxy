"""Administração de usuários, API keys e credenciais — prefixo /admin.

Todas as rotas exigem o header ``X-Admin-Key`` (env ``ADMIN_API_KEY``). Se a
env não for definida, uma chave aleatória é gerada no boot e impressa nos
logs (visível no dashboard de logs do FastAPI Cloud).

Endpoints:

- ``GET  /admin/users`` — lista usuários com suas keys.
- ``POST /admin/users`` — cria usuário (body: ``{"name": ...}``).
- ``DELETE /admin/users/{user_id}`` — remove usuário e suas keys.
- ``GET  /admin/users/{user_id}/keys`` — lista keys do usuário.
- ``POST /admin/users/{user_id}/keys`` — cria key (body opcional
  ``{"label": ...}``); a chave completa é retornada **uma única vez**.
- ``POST /admin/keys/{key_id}/revoke`` — revoga uma key.
- ``GET  /admin/credentials`` — estado das credenciais ChatGPT (mascarado).
- ``DELETE /admin/credentials`` — remove as credenciais salvas no banco.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..credentials import delete_credentials, load_credentials
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
                "keys": [
                    {
                        "id": key.id,
                        "prefix": key.prefix,
                        "label": key.label,
                        "created_at": key.created_at.isoformat(),
                        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
                        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                    }
                    for key in keys_by_user.get(user.id, [])
                ],
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
    return {
        "user_id": user_id,
        "keys": [
            {
                "id": key.id,
                "prefix": key.prefix,
                "label": key.label,
                "created_at": key.created_at.isoformat(),
                "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            }
            for key in keys
        ],
    }


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


@router.get("/credentials")
def credentials_status(session: Annotated[Session, Depends(get_session)]):
    from ..config import get_settings

    settings = get_settings()
    loaded = load_credentials(session, settings)
    if loaded is None:
        return {"configured": False}

    credentials, source = loaded
    import time

    return {
        "configured": True,
        "source": source,
        "account_id": _mask(credentials.account_id),
        "expires_at": credentials.expires_at,
        "expired": credentials.expires_at <= int(time.time() * 1000),
    }


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
def credentials_delete(session: Annotated[Session, Depends(get_session)]):
    delete_credentials(session)
    return None
