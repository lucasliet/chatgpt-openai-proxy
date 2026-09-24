"""Testes end-to-end dos endpoints HTTP (upstream Codex mockado com respx)."""

import json
from urllib.parse import parse_qs, urlsplit

import respx
from httpx import Response

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"

SSE_TEXTO = (
    'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"Olá"}\n\n'
    'data: {"type":"response.completed","response":{"id":"resp_abc","object":"response","model":"gpt-5.1-codex",'
    '"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Olá"}]}],'
    '"usage":{"input_tokens":10,"output_tokens":5}}}\n\n'
)

RESPONSES_JSON = {
    "id": "resp_abc",
    "object": "response",
    "model": "gpt-5.1-codex",
    "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Olá!"}]}
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


class TestHealthEModels:
    def test_health_publico(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_models_exige_api_key(self, client):
        response = client.get("/v1/models")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "missing_api_key"

    def test_models_com_api_key(self, client, auth_headers):
        response = client.get("/v1/models", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        ids = [m["id"] for m in data["data"]]
        assert "gpt-5.1-codex" in ids


class TestAdmin:
    def test_sem_header_admin_rejeita(self, client):
        assert client.get("/admin/users").status_code == 401
        assert client.get("/admin/users", headers={"X-Admin-Key": "errada"}).status_code == 401

    def test_ciclo_usuario_e_key(self, client, admin_headers):
        created = client.post("/admin/users", json={"name": "bob"}, headers=admin_headers)
        assert created.status_code == 201
        user_id = created.json()["id"]

        duplicado = client.post("/admin/users", json={"name": "bob"}, headers=admin_headers)
        assert duplicado.status_code == 409

        key = client.post(f"/admin/users/{user_id}/keys", json={"label": "cli"}, headers=admin_headers)
        assert key.status_code == 201
        full_key = key.json()["key"]
        assert full_key.startswith("sk-")
        assert key.json()["prefix"] == full_key[:12]

        # A key funciona como Bearer.
        assert client.get("/v1/models", headers={"Authorization": f"Bearer {full_key}"}).status_code == 200

        # Revogação invalida imediatamente.
        key_id = key.json()["id"]
        revoked = client.post(f"/admin/keys/{key_id}/revoke", headers=admin_headers)
        assert revoked.status_code == 200
        assert (
            client.get("/v1/models", headers={"Authorization": f"Bearer {full_key}"}).status_code
            == 401
        )

        # Delete remove usuário e keys.
        assert client.delete(f"/admin/users/{user_id}", headers=admin_headers).status_code == 204
        assert client.get(f"/admin/users/{user_id}/keys", headers=admin_headers).status_code == 404


@respx.mock
class TestResponsesEndpoint:
    def test_passthrough_json(self, client, auth_headers):
        route = respx.post(CODEX_URL).mock(return_value=Response(200, json=RESPONSES_JSON))
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-5.1-codex", "input": "diz oi", "store": False},
        )
        assert response.status_code == 200
        assert response.json() == RESPONSES_JSON

        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer access-token-env"
        assert request.headers["ChatGPT-Account-Id"] == "acc-env-123"

    def test_passthrough_stream(self, client, auth_headers):
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-5.1-codex", "input": "diz oi", "stream": True},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text
        assert '"response.output_text.delta"' in body
        assert '"response.completed"' in body

    def test_erro_upstream_relayado(self, client, auth_headers):
        respx.post(CODEX_URL).mock(return_value=Response(429, text="rate limit"))
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-5.1-codex", "input": "x"},
        )
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "upstream_error"


@respx.mock
class TestChatCompletionsEndpoint:
    def test_nao_streaming(self, client, auth_headers):
        route = respx.post(CODEX_URL).mock(return_value=Response(200, json=RESPONSES_JSON))
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json={
                "model": "gpt-5.1-codex",
                "messages": [
                    {"role": "system", "content": "Seja breve."},
                    {"role": "user", "content": "diz oi"},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Olá!"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["total_tokens"] == 15

        # Payload enviado ao Codex: convertido com store=false + instructions.
        sent = json.loads(route.calls.last.request.content)
        assert sent["store"] is False
        assert sent["instructions"] == "Seja breve."

    def test_streaming(self, client, auth_headers):
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json={"model": "gpt-5.1-codex", "messages": [{"role": "user", "content": "oi"}], "stream": True},
        )
        assert response.status_code == 200
        frames = [f for f in response.text.split("data: ") if f.strip()]
        assert frames[-1].startswith("[DONE]")

        chunks = [json.loads(f) for f in frames[:-1]]
        deltas = [c["choices"][0]["delta"] for c in chunks]
        assert deltas[0] == {"role": "assistant"}
        assert deltas[1] == {"content": "Olá"}
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[-1]["usage"]["completion_tokens"] == 5


@respx.mock
class TestAnthropicEndpoint:
    def test_nao_streaming(self, client, auth_headers):
        route = respx.post(CODEX_URL).mock(return_value=Response(200, json=RESPONSES_JSON))
        response = client.post(
            "/v1/messages",
            headers=auth_headers,
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 1024,
                "system": "Seja breve.",
                "messages": [{"role": "user", "content": "diz oi"}],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "message"
        assert body["role"] == "assistant"
        # Modelo solicitado é ecoado para compatibilidade com clientes Claude.
        assert body["model"] == "claude-sonnet-4-5"
        assert body["content"] == [{"type": "text", "text": "Olá!"}]
        assert body["stop_reason"] == "end_turn"
        assert body["usage"] == {"input_tokens": 10, "output_tokens": 5}

        # Upstream recebeu o default_model (claude-* não está na allowlist).
        sent = json.loads(route.calls.last.request.content)
        assert sent["model"] == "gpt-5.1-codex"
        assert sent["instructions"] == "Seja breve."

    def test_streaming(self, client, auth_headers):
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/messages",
            headers=auth_headers,
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "oi"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: message_start" in response.text
        assert "event: content_block_delta" in response.text
        assert '"text_delta"' in response.text
        assert "event: message_stop" in response.text

    def test_sem_credenciais_401(self, client_sem_env_creds, admin_headers):
        user = client_sem_env_creds.post("/admin/users", json={"name": "carol"}, headers=admin_headers)
        key = client_sem_env_creds.post(
            f"/admin/users/{user.json()['id']}/keys", json={}, headers=admin_headers
        ).json()["key"]
        response = client_sem_env_creds.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-5.1-codex", "max_tokens": 1, "messages": []},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "no_credentials"


@respx.mock
class TestLoginFlow:
    def _callback_url(self, auth_url: str, code: str = "code-123") -> str:
        params = parse_qs(urlsplit(auth_url).query)
        state = params["state"][0]
        return f"http://localhost:1455/auth/callback?code={code}&state={state}"

    def test_login_completo(self, client_sem_env_creds, admin_headers):
        settings = client_sem_env_creds.app.state.settings
        respx.post(settings.oauth_token_url).mock(
            return_value=Response(
                200,
                json={
                    "access_token": "at-login",
                    "refresh_token": "rt-login",
                    "expires_in": 3600,
                    "id_token": _id_token(),
                },
            )
        )

        start = client_sem_env_creds.post("/login/start")
        assert start.status_code == 200
        auth_url = start.json()["authUrl"]
        assert "code_challenge=" in auth_url

        complete = client_sem_env_creds.post(
            "/login/complete",
            json={"callbackUrl": self._callback_url(auth_url)},
        )
        assert complete.status_code == 200, complete.text
        assert complete.json()["success"] is True

        # Credenciais salvas funcionam nas rotas protegidas.
        user = client_sem_env_creds.post("/admin/users", json={"name": "dave"}, headers=admin_headers)
        key = client_sem_env_creds.post(
            f"/admin/users/{user.json()['id']}/keys", json={}, headers=admin_headers
        ).json()["key"]
        respx.post(CODEX_URL).mock(return_value=Response(200, json=RESPONSES_JSON))
        response = client_sem_env_creds.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-5.1-codex", "messages": [{"role": "user", "content": "oi"}]},
        )
        assert response.status_code == 200

    def test_state_mismatch_rejeitado(self, client_sem_env_creds):
        start = client_sem_env_creds.post("/login/start")
        auth_url = start.json()["authUrl"]
        callback = self._callback_url(auth_url) + "x"  # corrompe o state
        response = client_sem_env_creds.post("/login/complete", json={"callbackUrl": callback})
        assert response.status_code == 400

    def test_callback_url_invalida(self, client_sem_env_creds):
        client_sem_env_creds.post("/login/start")
        response = client_sem_env_creds.post(
            "/login/complete", json={"callbackUrl": "http://localhost:1455/auth/callback"}
        )
        assert response.status_code == 400
        assert "code" in response.json()["error"]["message"]

    def test_pagina_login_renderiza(self, client_sem_env_creds):
        response = client_sem_env_creds.get("/login")
        assert response.status_code == 200
        assert "Iniciar login com ChatGPT" in response.text


def _id_token() -> str:
    import base64

    def encode(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode({'chatgpt_account_id': 'acc-login'})}."
