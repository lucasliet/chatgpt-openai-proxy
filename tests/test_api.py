"""Testes end-to-end dos endpoints HTTP (upstream Codex mockado com respx)."""

import json
from urllib.parse import parse_qs, urlsplit

import respx
from httpx import Response

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"

SSE_TEXTO = (
    'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"Olá"}\n\n'
    'data: {"type":"response.completed","response":{"id":"resp_abc","object":"response","model":"gpt-6-terra",'
    '"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Olá"}]}],'
    '"usage":{"input_tokens":10,"output_tokens":5}}}\n\n'
)

SSE_TEXTO_RESPONSE = {
    "id": "resp_abc",
    "object": "response",
    "model": "gpt-6-terra",
    "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Olá"}]}
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"


@respx.mock
class TestHealthEModels:
    def test_health_publico(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_models_exige_api_key(self, client):
        response = client.get("/v1/models")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "missing_api_key"

    def test_models_listagem_dinamica_do_backend(self, client, auth_headers):
        route = respx.get(CODEX_MODELS_URL).mock(
            return_value=Response(200, json={"models": ["gpt-6-terra", "gpt-6-luna"]})
        )
        response = client.get("/v1/models", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        ids = [m["id"] for m in data["data"]]
        assert ids == ["gpt-6-terra", "gpt-6-luna"]
        # A listagem usa a credencial DO USUÁRIO da API key.
        assert route.calls.last.request.headers["Authorization"] == "Bearer at-acc-alice"

    def test_models_falha_no_backend_cai_na_allowlist(self, client, auth_headers):
        respx.get(CODEX_MODELS_URL).mock(return_value=Response(404, text="not found"))
        response = client.get("/v1/models", headers=auth_headers)
        assert response.status_code == 200
        ids = [m["id"] for m in response.json()["data"]]
        assert "gpt-6-terra" in ids

    def test_models_lista_de_objetos(self, client, auth_headers):
        respx.get(CODEX_MODELS_URL).mock(
            return_value=Response(200, json={"data": [{"id": "gpt-x"}, {"id": "gpt-y"}]})
        )
        response = client.get("/v1/models", headers=auth_headers)
        ids = [m["id"] for m in response.json()["data"]]
        assert ids == ["gpt-x", "gpt-y"]


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
        route = respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-6-terra", "input": "diz oi", "store": False},
        )
        assert response.status_code == 200
        # Não-streaming agrega o objeto ``response`` do response.completed.
        assert response.json() == SSE_TEXTO_RESPONSE

        # A credencial usada é a DO USUÁRIO da API key (alice / acc-alice).
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer at-acc-alice"
        assert request.headers["ChatGPT-Account-Id"] == "acc-alice"
        # Backend só aceita stream=true, mesmo para cliente não-streaming.
        assert json.loads(request.content)["stream"] is True

    def test_passthrough_stream(self, client, auth_headers):
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-6-terra", "input": "diz oi", "stream": True},
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
            json={"model": "gpt-6-terra", "input": "x"},
        )
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "upstream_error"

    def test_input_string_e_normalizado_para_lista(self, client, auth_headers):
        route = respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/responses",
            headers=auth_headers,
            json={"model": "gpt-6-terra", "input": "diz oi"},
        )
        assert response.status_code == 200
        sent = json.loads(route.calls.last.request.content)
        assert sent["input"] == [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "diz oi"}],
            }
        ]


@respx.mock
class TestChatCompletionsEndpoint:
    def test_nao_streaming(self, client, auth_headers):
        route = respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json={
                "model": "gpt-6-terra",
                "messages": [
                    {"role": "system", "content": "Seja breve."},
                    {"role": "user", "content": "diz oi"},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Olá"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["total_tokens"] == 15

        # Payload enviado ao Codex: convertido com store=false + instructions,
        # sempre stream=true (backend rejeita não-streaming).
        sent = json.loads(route.calls.last.request.content)
        assert sent["store"] is False
        assert sent["instructions"] == "Seja breve."
        assert sent["stream"] is True

    def test_streaming(self, client, auth_headers):
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json={"model": "gpt-6-terra", "messages": [{"role": "user", "content": "oi"}], "stream": True},
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
        route = respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
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
        assert body["content"] == [{"type": "text", "text": "Olá"}]
        # max_tokens do cliente não é repassado (backend rejeita max_output_tokens).
        sent = json.loads(route.calls.last.request.content)
        assert "max_output_tokens" not in sent
        assert sent["stream"] is True
        assert body["stop_reason"] == "end_turn"
        assert body["usage"] == {"input_tokens": 10, "output_tokens": 5}

        # Upstream recebeu o default_model (claude-* não está na allowlist).
        sent = json.loads(route.calls.last.request.content)
        assert sent["model"] == "gpt-6-luna"
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

    def test_sem_credenciais_401(self, client, admin_headers):
        user = client.post("/admin/users", json={"name": "carol"}, headers=admin_headers)
        key = client.post(
            f"/admin/users/{user.json()['id']}/keys", json={}, headers=admin_headers
        ).json()["key"]
        response = client.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-6-terra", "max_tokens": 1, "messages": []},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "no_credentials"


@respx.mock
class TestLoginFlow:
    def _callback_url(self, auth_url: str, code: str = "code-123") -> str:
        params = parse_qs(urlsplit(auth_url).query)
        state = params["state"][0]
        return f"http://localhost:1455/auth/callback?code={code}&state={state}"

    def _mock_token_endpoint(self, client, account_id: str = "acc-login") -> None:
        settings = client.app.state.settings
        respx.post(settings.oauth_token_url).mock(
            return_value=Response(
                200,
                json={
                    "access_token": "at-login",
                    "refresh_token": "rt-login",
                    "expires_in": 3600,
                    "id_token": _id_token(account_id),
                },
            )
        )

    def test_login_completo_gera_api_key(self, client):
        start = client.post("/login/start")
        assert start.status_code == 200
        auth_url = start.json()["authUrl"]
        assert "code_challenge=" in auth_url

        self._mock_token_endpoint(client)
        complete = client.post(
            "/login/complete",
            json={"callbackUrl": self._callback_url(auth_url)},
        )
        assert complete.status_code == 200, complete.text
        data = complete.json()
        assert data["success"] is True
        assert data["accountId"] == "acc...ogin"
        api_key = data["apiKey"]
        assert api_key.startswith("sk-")

        # A key gerada no login funciona nas rotas protegidas e usa a
        # credencial OAuth da conta que acabou de logar.
        route = respx.post(CODEX_URL).mock(
            return_value=Response(200, content=SSE_TEXTO, headers={"Content-Type": "text/event-stream"})
        )
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-6-terra", "messages": [{"role": "user", "content": "oi"}]},
        )
        assert response.status_code == 200
        assert route.calls.last.request.headers["Authorization"] == "Bearer at-login"
        assert route.calls.last.request.headers["ChatGPT-Account-Id"] == "acc-login"

    def test_relogin_revoga_key_antiga_e_gera_nova(self, client, admin_headers):
        self._mock_token_endpoint(client)

        first_start = client.post("/login/start").json()["authUrl"]
        first = client.post(
            "/login/complete", json={"callbackUrl": self._callback_url(first_start)}
        ).json()
        old_key = first["apiKey"]

        second_start = client.post("/login/start").json()["authUrl"]
        second = client.post(
            "/login/complete", json={"callbackUrl": self._callback_url(second_start)}
        ).json()
        new_key = second["apiKey"]

        assert new_key != old_key
        # Key antiga revogada, nova ativa.
        assert (
            client.get("/v1/models", headers={"Authorization": f"Bearer {old_key}"}).status_code
            == 401
        )
        assert (
            client.get("/v1/models", headers={"Authorization": f"Bearer {new_key}"}).status_code
            == 200
        )
        # Re-login não duplica o usuário.
        users = client.get("/admin/users", headers=admin_headers).json()["users"]
        assert len(users) == 1
        assert users[0]["credential"]["authenticated"] is True

    def test_state_mismatch_rejeitado(self, client):
        start = client.post("/login/start")
        auth_url = start.json()["authUrl"]
        callback = self._callback_url(auth_url) + "x"  # corrompe o state
        response = client.post("/login/complete", json={"callbackUrl": callback})
        assert response.status_code == 400

    def test_callback_url_invalida(self, client):
        client.post("/login/start")
        response = client.post(
            "/login/complete", json={"callbackUrl": "http://localhost:1455/auth/callback"}
        )
        assert response.status_code == 400
        assert "code" in response.json()["error"]["message"]

    def test_pagina_login_renderiza(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "Iniciar login com ChatGPT" in response.text
        assert "gerar a API key" in response.text


def _id_token(account_id: str = "acc-login") -> str:
    import base64

    def encode(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return (
        f"{encode({'alg': 'none'})}."
        f"{encode({'chatgpt_account_id': account_id, 'email': 'eu@exemplo.com'})}."
    )
