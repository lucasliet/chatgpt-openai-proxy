"""Configuração central da aplicação, 100% via variáveis de ambiente.

Compatível com deploy no FastAPI Cloud: nenhum valor sensível fica em
arquivo versionado; tudo pode ser injetado via dashboard/CLI (`fastapi cloud
env set`, com `--secret` para segredos).

Armazenamento: com `DATABASE_URL` definido (Postgres gerenciado, ex.: Neon)
o estado fica lá. Sem `DATABASE_URL`, tudo é persistido num arquivo SQLite em
`CHATGPT_PROXY_HOME` (default `~/.config/chatgpt-proxy`) — mesmo modelo do
projeto anterior (`credentials.json`), funciona igual em run local e Docker
(basta montar o diretório como volume).
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parâmetros de runtime lidos do ambiente (12-factor)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 3000
    host: str = "0.0.0.0"

    # Postgres gerenciado em produção (FastAPI Cloud/Neon). Quando None, o
    # banco é um arquivo SQLite em CHATGPT_PROXY_HOME (local/Docker).
    database_url: str | None = None

    # Diretório base do armazenamento local (mesmo papel do CHATGPT_PROXY_HOME
    # do projeto anterior).
    chatgpt_proxy_home: str | None = None

    # Segredo que assina o cookie de sessão do fluxo /login.
    cookie_secret: str = "chatgpt-proxy-dev-secret"

    # Chave de administração dos endpoints /admin/*. Se não definida, uma chave
    # aleatória é gerada no boot e impressa nos logs (uma única vez).
    admin_api_key: str | None = None

    codex_base_url: str = "https://chatgpt.com/backend-api/codex"

    # Engine upstream: "litellm" (default) ou "httpx" (port fiel do proxy
    # original, sem dependência do LiteLLM no caminho da requisição).
    upstream_engine: str = "litellm"

    # Modelo usado quando o cliente pede um modelo fora da allowlist
    # (ex.: clientes Anthropic que enviam "claude-sonnet-4-5"). Precisa ser
    # um modelo que o backend Codex do ChatGPT Plan suporte hoje.
    default_model: str = "gpt-5.5"

    oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_auth_url: str = "https://auth.openai.com/oauth/authorize"
    oauth_token_url: str = "https://auth.openai.com/oauth/token"
    oauth_scope: str = "offline_access openid profile email"
    # Porta do redirect localhost whitelisting pelo fluxo Codex. Só afeta o
    # valor do redirect_uri na URL de autorização e o modo "colar callback".
    oauth_callback_port: int = 1455


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância cacheada das configurações."""
    return Settings()


def proxy_home(settings: Settings) -> Path:
    """Diretório base do armazenamento local."""
    raw = settings.chatgpt_proxy_home or os.environ.get("CHATGPT_PROXY_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config" / "chatgpt-proxy"


def resolved_database_url(settings: Settings) -> str:
    """DATABASE_URL efetivo: a env ou SQLite no proxy home."""
    if settings.database_url:
        return settings.database_url
    return f"sqlite:///{proxy_home(settings) / 'proxy.db'}"


def oauth_redirect_uri(settings: Settings) -> str:
    """Redirect URI registrada no fluxo OAuth do Codex."""
    return f"http://localhost:{settings.oauth_callback_port}/auth/callback"
