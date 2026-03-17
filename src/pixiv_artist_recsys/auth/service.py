from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import PixivOAuthConfig, PixivOAuthToken, PixivTokenRecord, iso_utc_now
from .transport import HttpTransport, UrllibHttpTransport


class PixivOAuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PixivOAuthService:
    def __init__(self, config: PixivOAuthConfig | None = None, transport: HttpTransport | None = None) -> None:
        self.config = config or PixivOAuthConfig()
        self.transport = transport or UrllibHttpTransport()

    def refresh_access_token(
        self,
        *,
        refresh_token: str,
        proxy: str | None = None,
        timeout_s: float = 30.0,
        client_time: str | None = None,
    ) -> PixivOAuthToken:
        refresh_token = (refresh_token or '').strip()
        if not refresh_token:
            raise ValueError('refresh_token is required')
        if not self.config.client_id.strip() or not self.config.client_secret.strip():
            raise ValueError('client_id/client_secret are required')

        client_time = client_time or self._now_client_time()
        headers = self.config.build_headers(client_time=client_time)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

        response = self.transport.send(
            method='POST',
            url=self.config.token_url,
            headers=headers,
            data={
                'client_id': self.config.client_id,
                'client_secret': self.config.client_secret,
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'get_secure_url': '1',
                'include_policy': '1',
            },
            timeout_s=timeout_s,
            proxy=proxy,
        )
        if response.status_code != 200:
            raise PixivOAuthError('OAuth refresh failed', status_code=response.status_code)
        return self._parse_token_response(response.json())

    def refresh_into_record(self, *, token_key: str, refresh_token: str, existing: PixivTokenRecord | None = None) -> PixivTokenRecord:
        token = self.refresh_access_token(refresh_token=refresh_token)
        now = int(datetime.now(timezone.utc).timestamp())
        base = existing or PixivTokenRecord.from_refresh_token(token_key=token_key, refresh_token=refresh_token)
        return replace(
            base,
            access_token=token.access_token,
            token_type=token.token_type,
            expires_at_epoch=now + int(token.expires_in),
            refresh_token_rotated=token.refresh_token or '',
            user_id=token.user_id,
            last_refreshed_at=iso_utc_now(),
            last_error='',
        )

    @staticmethod
    def _now_client_time() -> str:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    @staticmethod
    def _unwrap_response(data: Any) -> Mapping[str, Any]:
        if isinstance(data, dict) and isinstance(data.get('response'), dict):
            return data['response']
        if isinstance(data, dict):
            return data
        raise PixivOAuthError('Invalid OAuth response shape')

    def _parse_token_response(self, data: Any) -> PixivOAuthToken:
        payload = self._unwrap_response(data)
        access_token = payload.get('access_token')
        token_type = payload.get('token_type')
        expires_in = payload.get('expires_in')
        refresh_token = payload.get('refresh_token')
        scope = payload.get('scope')
        user_id = None
        user = payload.get('user')
        if isinstance(user, dict) and user.get('id') is not None:
            try:
                user_id = int(user.get('id'))
            except Exception:
                user_id = None
        if isinstance(expires_in, str) and expires_in.isdigit():
            expires_in = int(expires_in)
        if not isinstance(access_token, str) or not access_token:
            raise PixivOAuthError('OAuth response missing access_token')
        if not isinstance(token_type, str) or not token_type:
            raise PixivOAuthError('OAuth response missing token_type')
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise PixivOAuthError('OAuth response missing expires_in')
        return PixivOAuthToken(
            access_token=access_token,
            token_type=token_type,
            expires_in=expires_in,
            refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
            scope=scope if isinstance(scope, str) and scope else None,
            user_id=user_id,
        )
