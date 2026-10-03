"""Testes da landing page/documentação em ``GET /``."""


class TestHomePage:
    def test_pagina_documentacao_publica(self, client):
        # Given: app disponível sem autenticação
        # When: acessar a raiz
        response = client.get("/")

        # Then: HTML pt-BR com os marcadores das rotas documentadas
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        body = response.text
        assert "/login" in body
        assert "/logout" in body
        assert "/v1/chat/completions" in body
        assert "/v1/responses" in body
        assert "/v1/messages" in body
        assert "https://chatgpt-openai-proxy.fastapicloud.dev" in body
        assert "seu-host" not in body
        assert "theme-toggle:active .track" in body
        assert "segurar o botão para confirmar" in body

    def test_pagina_login_tem_fade_out_dos_steps(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "is-leaving" in response.text
        assert "hideSteps" in response.text
        assert "theme-toggle:active .track" in response.text
