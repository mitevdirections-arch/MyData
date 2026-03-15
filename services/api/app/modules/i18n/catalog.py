from __future__ import annotations

from typing import Any

CATALOG_VERSION = "v1"

LOCALE_REGISTRY: list[dict[str, Any]] = [
    {"code": "en", "name": "English", "completeness": 100},
    {"code": "bg", "name": "Bulgarian", "completeness": 100},
    {"code": "de", "name": "German", "completeness": 20},
    {"code": "ro", "name": "Romanian", "completeness": 20},
    {"code": "tr", "name": "Turkish", "completeness": 20},
]

CATALOGS: dict[str, dict[str, str]] = {
    "en": {
        "common.ok": "OK",
        "common.error": "Error",
        "auth.unauthorized": "Unauthorized",
        "profile.updated": "Profile updated",
        "profile.workspace_updated": "Workspace profile updated",
        "support.request_created": "Support request created",
        "guard.locked": "Bot credential locked",
        "licenses.core_required": "Core license required",
    },
    "bg": {
        "common.ok": "Добре",
        "common.error": "Грешка",
        "auth.unauthorized": "Неразрешен достъп",
        "profile.updated": "Профилът е обновен",
        "profile.workspace_updated": "Фирменият профил е обновен",
        "support.request_created": "Заявката за съпорт е създадена",
        "guard.locked": "Бот удостоверението е заключено",
        "licenses.core_required": "Изисква се Core лиценз",
    },
}