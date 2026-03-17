from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


DEFAULT_OAUTH_BASE_URL = "https://oauth.secure.pixiv.net"
DEFAULT_OAUTH_TOKEN_PATH = "/auth/token"
DEFAULT_USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"
DEFAULT_ACCEPT_LANGUAGE = "en_US"
DEFAULT_APP_OS = "android"
DEFAULT_APP_OS_VERSION = "11"
DEFAULT_APP_VERSION = "5.0.234"
DEFAULT_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
DEFAULT_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
DEFAULT_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"


@dataclass(frozen=True, slots=True)
class PixivOAuthConfig:
    client_id: str = DEFAULT_CLIENT_ID
    client_secret: str = DEFAULT_CLIENT_SECRET
    hash_secret: str | None = DEFAULT_HASH_SECRET
    base_url: str = DEFAULT_OAUTH_BASE_URL
    token_path: str = DEFAULT_OAUTH_TOKEN_PATH
    user_agent: str = DEFAULT_USER_AGENT
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE
    app_os: str = DEFAULT_APP_OS
    app_os_version: str = DEFAULT_APP_OS_VERSION
    app_version: str = DEFAULT_APP_VERSION

    def build_headers(self, *, client_time: str) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": self.accept_language,
            "App-OS": self.app_os,
            "App-OS-Version": self.app_os_version,
            "App-Version": self.app_version,
        }
        if self.hash_secret:
            headers["X-Client-Time"] = client_time
            headers["X-Client-Hash"] = hashlib.md5((client_time + self.hash_secret).encode("utf-8")).hexdigest()
        return headers

    @property
    def token_url(self) -> str:
        return self.base_url.rstrip("/") + self.token_path


@dataclass(frozen=True, slots=True)
class PixivOAuthToken:
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str | None
    scope: str | None
    user_id: int | None

    @property
    def bearer_token(self) -> str:
        return f"{self.token_type} {self.access_token}"


@dataclass(slots=True)
class PixivTokenRecord:
    token_key: str
    refresh_token_ref: str
    access_token: str = ""
    token_type: str = "Bearer"
    expires_at_epoch: int = 0
    refresh_token_rotated: str = ""
    user_id: int | None = None
    last_refreshed_at: str = ""
    last_error: str = ""

    @staticmethod
    def mask_refresh_token(refresh_token: str) -> str:
        token = (refresh_token or "").strip()
        if not token:
            return "masked:"
        if len(token) <= 8:
            return f"masked:{token[:2]}***{token[-2:]}"
        return f"masked:{token[:4]}***{token[-4:]}"

    @classmethod
    def from_refresh_token(cls, *, token_key: str, refresh_token: str) -> "PixivTokenRecord":
        return cls(token_key=token_key, refresh_token_ref=cls.mask_refresh_token(refresh_token))


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
