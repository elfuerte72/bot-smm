from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.webapp.auth import get_current_user

# Annotated-вариант для типобезопасной инъекции в роуты:
#     async def endpoint(user: CurrentUser) -> ...
CurrentUser = Annotated[dict[str, object], Depends(get_current_user)]

__all__ = ["get_current_user", "CurrentUser"]
