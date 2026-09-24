"""Configuração central da aplicação, 100% via variáveis de ambiente.

Compatível com deploy no FastAPI Cloud: nenhum valor sensível fica em
arquivo versionado; tudo pode ser injetado via dashboard/CLI (`fastapi cloud
env set`, com `--secret` para segredos).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parâmetros de runtime lidos do ambiente (12-factor)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 3000
    host: str = "0.0.0.0"

    # Em produção no FastAPI Cloud use Postgres gerenciado (ex.: Neon) via
    # DATABASE_URL. SQLite é o default apenas para desenvolvimento local.
    database_url: str = "sqlite:///./data/proxy.db"

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
    # (ex.: clientes Anthropic que enviam "claude-sonnet-4-5").
    default_model: str = "gpt-5.1-codex"

    oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_auth_url: str = "https://auth.openai.com/oauth/authorize"
    oauth_token_url: str = "https://auth.openai.com/oauth/token"
    oauth_scope: str = "offline_access openid profile email"
    # Porta do redirect localhost whitelisting pelo fluxo Codex. Só afeta o
    # valor do redirect_uri na URL de autorização e o modo "colar callback".
    oauth_callback_port: int = 1455

    # Credenciais ChatGPT via env (headless/Docker). Têm precedência sobre as
    # credenciais salvas no banco e são read-only (refresh não persiste).
    # Só valem quando todas existem e CHATGPT_EXPIRES_AT é numérico (ms epoch).
    chatgpt_access_token: str | None = None
    chatgpt_refresh_token: str | None = None
    chatgpt_account_id: str | None = None
    chatgpt_expires_at: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância cacheada das configurações."""
    return Settings()


def oauth_redirect_uri(settings: Settings) -> str:
    """Redirect URI registrada no fluxo OAuth do Codex."""
    return f"http://localhost:{settings.oauth_callback_port}/auth/callback"
