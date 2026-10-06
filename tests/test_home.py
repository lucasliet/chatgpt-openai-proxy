"""Testes da landing page/documentação em ``GET /``."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.home import _render_home_html


class TestFavicon:
    def test_rota_serve_svg_com_cache_longo(self, client):
        # Given: app disponível sem autenticação
        # When: pedir o favicon
        response = client.get("/favicon.svg")

        # Then: SVG da marca, com cache de 24h
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "max-age=86400" in response.headers["cache-control"]
        assert "<svg" in response.text
        assert "#d9e2ec" in response.text

    def test_favicon_ico_serve_o_mesmo_svg(self, client):
        # Given: browsers que pedem /favicon.ico direto
        # When: acessar o caminho legado
        response = client.get("/favicon.ico")

        # Then: mesmo SVG, sem 404
        assert response.status_code == 200
        assert "<svg" in response.text

    def test_paginas_publicas_linkam_o_favicon(self, client):
        # Given: páginas HTML públicas
        # When: renderizar home, login e login do dashboard
        # Then: todas apontam para o favicon SVG
        for path in ("/", "/login", "/dashboard/login"):
            page = client.get(path).text
            assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in page

    def test_link_do_favicon_preserva_root_path(self, client):
        # Given: app montado sob um prefixo
        client.app.root_path = "/proxy"

        # When: renderizar a home
        page = client.get("http://localhost:3000/").text

        # Then: o href do favicon inclui o prefixo
        assert 'href="/proxy/favicon.svg"' in page


class TestOgCover:
    def test_rota_serve_png_com_cache_longo(self, client):
        # Given: app disponível sem autenticação
        # When: pedir a cover do OpenGraph
        response = client.get("/og-cover.png")

        # Then: PNG 1200x640 da marca, com cache de 24h
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert "max-age=86400" in response.headers["cache-control"]
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_home_linka_a_cover_na_url_canonica(self, client):
        # Given: app disponível sem autenticação
        # When: renderizar a home
        body = client.get("/").text

        # Then: og:image e twitter:image apontam para a rota da cover
        assert '<meta property="og:image" content="http://testserver/og-cover.png">' in body
        assert '<meta name="twitter:image" content="http://testserver/og-cover.png">' in body


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
        assert "http://testserver/v1/chat/completions" in body
        assert "seu-host" not in body
        assert "theme-toggle:active .track" in body
        assert "segurar o botão para confirmar" in body

    def test_pagina_tem_meta_tags_opengraph_e_twitter(self, client):
        # Given: app disponível sem autenticação
        # When: acessar a raiz
        body = client.get("/").text

        # Then: meta tags sociais presentes, com og:url na URL canônica e cover
        assert '<meta property="og:type" content="website">' in body
        assert '<meta property="og:site_name" content="chatgpt-openai-proxy">' in body
        assert '<meta property="og:title" content="ChatGPT Proxy — Docs">' in body
        assert '<meta property="og:url" content="http://testserver/">' in body
        assert '<meta name="twitter:card" content="summary">' in body
        assert '<meta name="twitter:title" content="ChatGPT Proxy — Docs">' in body
        assert '<meta property="og:image" content="http://testserver/og-cover.png">' in body
        assert '<meta property="og:image:width" content="1200">' in body
        assert '<meta property="og:image:height" content="640">' in body
        assert '<meta name="twitter:image" content="http://testserver/og-cover.png">' in body

    def test_pagina_login_tem_fade_out_dos_steps(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "is-leaving" in response.text
        assert "hideSteps" in response.text
        assert "theme-toggle:active .track" in response.text

    def test_pagina_login_tem_botao_copiar_key(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert 'id="apiKeyValue"' in response.text
        assert 'id="copyKeyBtn"' in response.text
        assert "copyApiKey" in response.text
        assert "fallbackCopyText" in response.text

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://localhost:3000",
            "http://127.0.0.1:8000",
            "https://chatgpt-openai-proxy.fastapicloud.dev",
            "https://proxy.example.org",
        ],
    )
    def test_should_use_request_address_in_every_example(self, client, base_url):
        body = client.get(f"{base_url}/").text
        assert f"Base URL: <code>{base_url}</code>" in body
        for path in [
            "v1/chat/completions",
            "v1/responses",
            "v1/messages",
            "v1/models",
            "health",
            "logout",
        ]:
            assert f"{base_url}/{path}" in body
        assert "__PROXY_BASE_URL__" not in body
        if "fastapicloud.dev" not in base_url:
            assert "chatgpt-openai-proxy.fastapicloud.dev" not in body

    def test_should_preserve_proxy_root_path(self, client):
        client.app.root_path = "/proxy"
        body = client.get("http://localhost:3000/").text
        assert "http://localhost:3000/proxy/v1/chat/completions" in body

    def test_should_escape_base_url_in_html(self):
        body = _render_home_html('http://host/<script>"&')
        assert "http://host/&lt;script&gt;&quot;&amp;" in body
        assert 'http://host/<script>"&' not in body

    def test_should_keep_privacy_claims_in_their_respective_sections(self, client):
        page = client.get("/").text
        stored = page.split("O que o proxy guarda no banco:", 1)[1].split(
            "O que o proxy não guarda:", 1
        )[0]
        not_stored = page.split("O que o proxy não guarda:", 1)[1].split("Retenção:", 1)[0]
        assert "Não guardamos" not in stored
        assert "Registros individuais de chamadas" in not_stored
        assert "Conteúdo das conversas" in not_stored
        assert "para que o upstream também não retenha" not in page
        assert "tokens e keys são inúteis" not in page
        assert "exclui sua conta" in page
        assert "clientes compatíveis" in page

    @pytest.mark.parametrize("mount_name", [None, "proxy"])
    @pytest.mark.parametrize("root_path", ["", "/gateway"])
    def test_should_include_full_mounted_prefix_in_examples(self, client, mount_name, root_path):
        outer = FastAPI(root_path=root_path)
        outer.mount("/proxy", client.app, name=mount_name)
        base_url = f"https://preview.example:8443{root_path}/proxy"
        with TestClient(outer, base_url="https://preview.example:8443") as mounted:
            response = mounted.get(f"{root_path}/proxy/")
        assert response.status_code == 200
        assert f"Base URL: <code>{base_url}</code>" in response.text
        for path in [
            "v1/chat/completions",
            "v1/responses",
            "v1/messages",
            "v1/models",
            "health",
            "logout",
        ]:
            assert f"{base_url}/{path}" in response.text
