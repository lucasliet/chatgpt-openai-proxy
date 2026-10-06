"""Testes do backoffice web: /admin-login (emissão do cookie) e guard de /backoffice."""

import time

from conftest import create_api_key, create_user_with_credentials


def _login(client):
    """POST /admin-login com a chave correta, sem seguir o redirect."""
    return client.post("/admin-login", data={"key": "sk-admin-test"}, follow_redirects=False)


class TestAdminLogin:
    def test_pagina_de_login_renderiza(self, client):
        # Given
        # When
        response = client.get("/admin-login")

        # Then
        assert response.status_code == 200
        assert "Acesso de administrador" in response.text
        assert 'type="password"' in response.text

    def test_chave_errada_retorna_401_sem_cookie(self, client):
        # Given
        # When
        response = client.post("/admin-login", data={"key": "sk-errada"}, follow_redirects=False)

        # Then
        assert response.status_code == 401
        assert "inválida" in response.text
        assert "admin_session" not in response.headers.get("set-cookie", "")

    def test_chave_correta_redireciona_e_seta_cookie(self, client):
        # Given
        # When
        response = _login(client)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/backoffice"
        assert "admin_session" in response.headers["set-cookie"]
        assert "httponly" in response.headers["set-cookie"].lower()

    def test_ja_autenticado_admin_login_redireciona_ao_backoffice(self, client):
        # Given
        _login(client)

        # When
        response = client.get("/admin-login", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/backoffice"


class TestBackofficeGuard:
    def test_sem_cookie_redireciona_para_login(self, client):
        # Given
        # When
        response = client.get("/backoffice", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/admin-login"

    def test_acoes_de_escrita_tambem_exigem_cookie(self, client):
        # Given
        # When
        response = client.post(
            "/backoffice/users", data={"name": "mallory"}, follow_redirects=False
        )

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/admin-login"

    def test_cookie_adulterado_redireciona_para_login(self, client):
        # Given
        _login(client)
        client.cookies.set("admin_session", f"{int(time.time())}.assinatura-forjada")

        # When
        response = client.get("/backoffice", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/admin-login"

    def test_cookie_expirado_redireciona_para_login(self, client):
        # Given
        import hashlib
        import hmac

        from app.config import get_settings

        issued = str(int(time.time()) - 13 * 3600)  # 13h atrás, além das 12h válidas
        sig = hmac.new(
            get_settings().cookie_secret.encode(), f"admin:{issued}".encode(), hashlib.sha256
        ).hexdigest()
        client.cookies.set("admin_session", f"{issued}.{sig}")

        # When
        response = client.get("/backoffice", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/admin-login"


class TestBackofficeAcoes:
    def test_dashboard_lista_usuario_e_key(self, client):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        create_api_key(client, user_id, label="notebook")
        _login(client)

        # When
        response = client.get("/backoffice")

        # Then
        assert response.status_code == 200
        assert "alice" in response.text
        assert "autenticado" in response.text
        assert "notebook" in response.text
        assert "sk-" in response.text  # prefix mascarado da key

    def test_acoes_destrutivas_exigem_hold_to_confirm(self, client):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        create_api_key(client, user_id, label="notebook")
        _login(client)

        # When
        response = client.get("/backoffice")

        # Then
        assert response.text.count('type="button" data-hold-confirm') == 2
        assert "setupHoldConfirm" in response.text
        assert "confirm(" not in response.text

    def test_criar_usuario_pelo_form(self, client):
        # Given
        _login(client)

        # When
        response = client.post("/backoffice/users", data={"name": "bob"}, follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert "ok=" in response.headers["location"]
        assert "bob" in client.get("/backoffice").text

    def test_criar_usuario_duplicado_mostra_erro(self, client):
        # Given
        create_user_with_credentials(client, "alice", account_id="acc-alice")
        _login(client)

        # When
        response = client.post("/backoffice/users", data={"name": "alice"}, follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert "err=" in response.headers["location"]

    def test_gerar_key_exibe_apenas_na_resposta(self, client):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        _login(client)

        # When
        response = client.post(f"/backoffice/users/{user_id}/keys", data={"label": "cli"})

        # Then
        assert response.status_code == 200
        # A chave completa aparece nesta resposta (e o redirect seguinte não a repete).
        import re

        found = re.search(r'id="apiKeyValue">(sk-[A-Za-z0-9_-]+)<', response.text)
        assert found, response.text[:500]
        assert 'id="copyKeyBtn"' in response.text
        followup = client.get("/backoffice")
        assert found.group(1) not in followup.text

    def test_revogar_key_pelo_form(self, client, admin_headers):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        raw_key = create_api_key(client, user_id)
        keys = client.get(f"/admin/users/{user_id}/keys", headers=admin_headers).json()["keys"]
        _login(client)

        # When
        response = client.post(f"/backoffice/keys/{keys[0]['id']}/revoke", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert (
            client.get("/v1/models", headers={"Authorization": f"Bearer {raw_key}"}).status_code
            == 401
        )

    def test_excluir_usuario_pelo_form(self, client, admin_headers):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        create_api_key(client, user_id)
        _login(client)

        # When
        response = client.post(f"/backoffice/users/{user_id}/delete", follow_redirects=False)

        # Then
        assert response.status_code == 303
        listed = client.get("/admin/users", headers=admin_headers).json()["users"]
        assert user_id not in [u["id"] for u in listed]

    def test_logout_invalida_a_sessao(self, client):
        # Given
        _login(client)

        # When
        response = client.post("/backoffice/logout", follow_redirects=False)

        # Then
        assert response.status_code == 303
        assert response.headers["location"] == "/admin-login"
        followup = client.get("/backoffice", follow_redirects=False)
        assert followup.status_code == 303
        assert followup.headers["location"] == "/admin-login"
