"""Testes do fluxo de logout / exclusão de conta (prefixo /logout)."""

from conftest import create_api_key, create_user_with_credentials
from sqlmodel import Session, select

from app.database import get_engine
from app.models import ApiKey, User


class TestLogoutPage:
    def test_pagina_de_confirmacao(self, client):
        # Given
        # When
        response = client.get("/logout")

        # Then
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "/login" in response.text
        assert "btn danger hold" in response.text
        assert "hold-fill" in response.text
        assert "Segure para excluir" in response.text
        assert "confirm(" not in response.text


class TestLogout:
    def test_logout_com_sucesso_remove_conta_credenciais_e_keys(self, client, admin_headers):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        raw_key = create_api_key(client, user_id)
        headers = {"Authorization": f"Bearer {raw_key}"}

        # When
        response = client.post("/logout", headers=headers)

        # Then
        assert response.status_code == 200
        assert response.json()["success"] is True
        # A key deixa de funcionar na hora (a linha da key foi apagada).
        assert client.get("/v1/models", headers=headers).status_code == 401
        assert client.post("/logout", headers=headers).status_code == 401
        # O usuário some da listagem de admin.
        listed = client.get("/admin/users", headers=admin_headers).json()["users"]
        assert user_id not in [u["id"] for u in listed]
        # Não restam rows de ApiKey nem o próprio usuário no banco.
        with Session(get_engine()) as session:
            remaining_keys = session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()
            assert remaining_keys == []
            assert session.get(User, user_id) is None

    def test_sem_authorization_retorna_401(self, client):
        # Given
        # When
        response = client.post("/logout")

        # Then
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "missing_api_key"

    def test_key_invalida_retorna_401(self, client):
        # Given
        headers = {"Authorization": "Bearer sk-nao-existe"}

        # When
        response = client.post("/logout", headers=headers)

        # Then
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_api_key"
