from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Header, HTTPException, status


def bearer_auth(expected_token: str) -> Callable[..., None]:
    def authenticate(authorization: str | None = Header(default=None)) -> None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="令牌缺失或无效",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return authenticate
