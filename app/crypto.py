"""Cifragem em repouso dos tokens OAuth (Fernet = AES-128-CBC + HMAC-SHA256).

Resolução da chave (``get_keyring``):

1. ``TOKEN_ENCRYPTION_KEY`` — uma ou mais chaves Fernet separadas por vírgula
   (rotação: a **primeira** cifra, todas decifram);
2. sem a env e sem ``DATABASE_URL``: keyfile ``CHATGPT_PROXY_HOME/token.key``
   (criado com 0600 no primeiro boot) — mesmo modelo do credentials.json do
   projeto anterior, funciona em local e Docker (basta montar o volume);
3. com ``DATABASE_URL`` definida e sem a env: **falha no boot** — instâncias
   efêmeras/multi-instância não podem gerar uma chave própria, senão cada uma
   tornaria ilegíveis os tokens gravados pelas outras.

``EncryptedText`` é o TypeDecorator usado nas colunas sensíveis do modelo:
cifra/decifra transparentemente, então nenhum call-site muda. Strings vazias
não são cifradas (são a sentinela de "usuário não autenticado").
"""

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import Settings, get_settings, proxy_home

# Todo token Fernet começa com esse prefixo (versão 0x80 + timestamp) — usado
# para distinguir ciphertext de texto puro legado na migração.
FERNET_PREFIX = "gAAAAA"


@dataclass
class Keyring:
    """Chave primária (cifra) + conjunto completo (decifra, para rotação)."""

    primary: Fernet
    all: MultiFernet


_keyring: Keyring | None = None


def get_keyring() -> Keyring:
    """Retorna (resolvendo e cacheando se necessário) o keyring ativo."""
    global _keyring
    if _keyring is None:
        _keyring = _load_keyring(get_settings())
    return _keyring


def reset_keyring() -> None:
    """Descarta o keyring cacheado (usado em testes para trocar a env)."""
    global _keyring
    _keyring = None


def _load_keyring(settings: Settings) -> Keyring:
    raw = settings.token_encryption_key
    if raw:
        keys = [Fernet(part.strip().encode()) for part in raw.split(",") if part.strip()]
        if not keys:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY está definida mas não contém nenhuma chave.")
        return Keyring(primary=keys[0], all=MultiFernet(keys))
    if settings.database_url:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY não definida. Com DATABASE_URL (banco gerenciado) "
            "a env é obrigatória: sem ela, cada instância geraria uma chave própria "
            "e os tokens gravados por uma ficariam ilegíveis nas outras. Gere uma "
            'com: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return _keyring_from_keyfile(proxy_home(settings) / "token.key")


def _keyring_from_keyfile(path: Path) -> Keyring:
    if path.exists():
        key = Fernet(path.read_bytes().strip())
        return Keyring(primary=key, all=MultiFernet([key]))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = Fernet.generate_key()
    # O_EXCL: dois processos no primeiro boot não sobrescrevem a chave um do outro.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(raw)
    key = Fernet(raw)
    return Keyring(primary=key, all=MultiFernet([key]))


def encrypt_str(value: str) -> str:
    """Cifra uma string com a chave primária."""
    return get_keyring().primary.encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    """Decifra uma string com qualquer chave do keyring (InvalidToken se nenhuma servir)."""
    return get_keyring().all.decrypt(value.encode()).decode()


def upgraded_ciphertext(value: str) -> str | None:
    """Retorna o valor re-cifrado com a chave primária, ou None se já está atual.

    Texto puro legado (sem prefixo Fernet) é cifrado; ciphertext de chave
    antiga do keyring é rotacionado para a primária; ciphertext ilegível por
    todas as chaves (env errada) é mantido — o erro claro acontece na leitura.
    """
    if not value:
        return None
    keyring = get_keyring()
    if not value.startswith(FERNET_PREFIX):
        return keyring.primary.encrypt(value.encode()).decode()
    try:
        keyring.primary.decrypt(value.encode())
        return None
    except InvalidToken:
        pass
    try:
        plaintext = keyring.all.decrypt(value.encode())
    except InvalidToken:
        return None
    return keyring.primary.encrypt(plaintext).decode()


class EncryptedText(TypeDecorator[str]):
    """Coluna de texto cifrada em repouso, transparente para os call-sites."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return value
        return encrypt_str(value)

    def process_result_value(self, value, dialect):
        if not value:
            return value
        try:
            return decrypt_str(value)
        except InvalidToken:
            raise RuntimeError(
                "Não foi possível decifrar um token do banco: a TOKEN_ENCRYPTION_KEY "
                "atual não corresponde à usada na gravação."
            ) from None
