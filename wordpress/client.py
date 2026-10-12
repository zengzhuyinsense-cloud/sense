"""
WordPress REST transport for Kivantos site-building.

Auth: HTTP Basic with username + Application Password.
Public GETs work without credentials; writes and privileged reads need auth.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence, Union


DEFAULT_URL = "https://kivantos.com"
DEFAULT_USER_AGENT = "KivantosWPClient/0.1"


class WordPressError(RuntimeError):
    """Raised when the WordPress REST API returns an error response."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


@dataclass(frozen=True)
class WordPressConfig:
    site_url: str = DEFAULT_URL
    username: Optional[str] = None
    application_password: Optional[str] = None
    api_base: Optional[str] = None
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 60.0

    @property
    def rest_root(self) -> str:
        if self.api_base:
            return self.api_base.rstrip("/")
        return f"{self.site_url.rstrip('/')}/wp-json"

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.application_password)

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        load_dotenv_file: bool = True,
    ) -> "WordPressConfig":
        if load_dotenv_file:
            _load_dotenv(_default_env_path())
        e = env or os.environ
        return cls(
            site_url=(e.get("WORDPRESS_URL") or DEFAULT_URL).rstrip("/"),
            username=(e.get("WORDPRESS_USERNAME") or "").strip() or None,
            application_password=(
                e.get("WORDPRESS_APPLICATION_PASSWORD") or ""
            ).strip()
            or None,
            api_base=(e.get("WORDPRESS_API_BASE") or "").strip() or None,
            user_agent=(e.get("WORDPRESS_USER_AGENT") or DEFAULT_USER_AGENT).strip()
            or DEFAULT_USER_AGENT,
        )


def _default_env_path() -> Path:
    return Path(__file__).resolve().parent / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Does not override existing env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


class WordPressClient:
    def __init__(self, config: Optional[WordPressConfig] = None) -> None:
        self.config = config or WordPressConfig.from_env()

    # --- low-level ---------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        data: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        auth: Optional[bool] = None,
    ) -> Any:
        """
        Call a REST path relative to /wp-json (e.g. "/wp/v2/pages").

        auth=None → send credentials when configured
        auth=True → require credentials
        auth=False → never send credentials
        """
        use_auth = self.config.has_credentials if auth is None else auth
        if auth is True and not self.config.has_credentials:
            raise WordPressError(
                "WORDPRESS_USERNAME and WORDPRESS_APPLICATION_PASSWORD are required"
            )

        url = self._build_url(path, params)
        body = data
        req_headers: MutableMapping[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        if headers:
            req_headers.update(headers)
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        if use_auth:
            token = base64.b64encode(
                f"{self.config.username}:{self.config.application_password}".encode(
                    "utf-8"
                )
            ).decode("ascii")
            req_headers["Authorization"] = f"Basic {token}"

        req = urllib.request.Request(
            url, data=body, headers=req_headers, method=method.upper()
        )
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(
                req, timeout=self.config.timeout, context=ctx
            ) as resp:
                raw = resp.read()
                if not raw:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype or raw[:1] in (b"{", b"["):
                    return json.loads(raw.decode("utf-8"))
                return raw
        except urllib.error.HTTPError as exc:
            payload: Any = None
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = None
            code = None
            message = f"HTTP {exc.code} for {method.upper()} {url}"
            if isinstance(payload, dict):
                code = payload.get("code")
                if payload.get("message"):
                    message = f"{message}: {payload['message']}"
            raise WordPressError(
                message, status=exc.code, code=code, payload=payload
            ) from exc
        except urllib.error.URLError as exc:
            raise WordPressError(f"Network error calling {url}: {exc}") from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # --- site index / inventory --------------------------------------------

    def index(self) -> dict:
        data = self.get("/")
        if not isinstance(data, dict):
            raise WordPressError("Unexpected index payload")
        return data

    def list_pages(
        self,
        *,
        per_page: int = 100,
        status: str = "publish",
        context: str = "view",
        fields: Optional[str] = None,
        auth: Optional[bool] = None,
    ) -> list:
        params: dict[str, Any] = {
            "per_page": per_page,
            "status": status,
            "context": context,
        }
        if fields:
            params["_fields"] = fields
        # draft/private listing needs auth
        data = self.get("/wp/v2/pages", params=params, auth=auth)
        return data if isinstance(data, list) else []

    def list_posts(self, **params: Any) -> list:
        data = self.get("/wp/v2/posts", params=params)
        return data if isinstance(data, list) else []

    def list_media(self, **params: Any) -> list:
        data = self.get("/wp/v2/media", params=params)
        return data if isinstance(data, list) else []

    def get_settings(self) -> dict:
        data = self.get("/wp/v2/settings", auth=True)
        if not isinstance(data, dict):
            raise WordPressError("Unexpected settings payload")
        return data

    def update_settings(self, patch: Mapping[str, Any]) -> dict:
        data = self.post("/wp/v2/settings", json_body=dict(patch), auth=True)
        if not isinstance(data, dict):
            raise WordPressError("Unexpected settings update payload")
        return data

    def me(self) -> dict:
        data = self.get("/wp/v2/users/me", auth=True, params={"context": "edit"})
        if not isinstance(data, dict):
            raise WordPressError("Unexpected /users/me payload")
        return data

    # --- pages (build core) ------------------------------------------------

    def find_page_by_slug(
        self, slug: str, *, include_drafts: bool = False
    ) -> Optional[dict]:
        # Non-publish statuses require auth; never ask for them anonymously.
        can_see_drafts = include_drafts and self.config.has_credentials
        params: dict[str, Any] = {"slug": slug, "per_page": 10}
        if can_see_drafts:
            params["status"] = "publish,draft,private,pending,future"
            params["context"] = "edit"
        data = self.get(
            "/wp/v2/pages",
            params=params,
            auth=True if can_see_drafts else False,
        )
        if isinstance(data, list) and data:
            return data[0]
        return None

    def get_page(self, page_id: int, *, context: str = "view") -> dict:
        auth = context == "edit"
        data = self.get(f"/wp/v2/pages/{page_id}", params={"context": context}, auth=auth)
        if not isinstance(data, dict):
            raise WordPressError(f"Unexpected page payload for id={page_id}")
        return data

    def upsert_page(
        self,
        *,
        slug: str,
        title: str,
        content: Optional[str] = None,
        status: str = "publish",
        template: Optional[str] = None,
        parent: int = 0,
        menu_order: Optional[int] = None,
        featured_media: Optional[int] = None,
        excerpt: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """Create or update a page identified by slug. Returns the page (or plan)."""
        existing = self.find_page_by_slug(slug, include_drafts=True)
        body: dict[str, Any] = {
            "title": title,
            "slug": slug,
            "status": status,
            "parent": parent,
        }
        if content is not None:
            body["content"] = content
        if template is not None:
            body["template"] = template
        if menu_order is not None:
            body["menu_order"] = menu_order
        if featured_media is not None:
            body["featured_media"] = featured_media
        if excerpt is not None:
            body["excerpt"] = excerpt

        if dry_run:
            return {
                "action": "update" if existing else "create",
                "slug": slug,
                "id": existing.get("id") if existing else None,
                "body_keys": sorted(body.keys()),
            }

        if existing:
            page_id = int(existing["id"])
            data = self.post(f"/wp/v2/pages/{page_id}", json_body=body, auth=True)
        else:
            data = self.post("/wp/v2/pages", json_body=body, auth=True)
        if not isinstance(data, dict):
            raise WordPressError(f"Unexpected upsert payload for slug={slug}")
        return data

    # --- media -------------------------------------------------------------

    def find_media_by_slug(self, slug: str) -> Optional[dict]:
        data = self.get(
            "/wp/v2/media",
            params={"slug": slug, "per_page": 10, "_fields": "id,slug,source_url,mime_type,title"},
        )
        if isinstance(data, list) and data:
            return data[0]
        return None

    def upload_media(
        self,
        file_path: Union[str, Path],
        *,
        title: Optional[str] = None,
        alt_text: Optional[str] = None,
        slug: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        path = Path(file_path)
        if not path.is_file():
            raise WordPressError(f"Media file not found: {path}")
        if dry_run:
            return {"action": "upload", "file": str(path), "slug": slug or path.stem}

        if slug:
            existing = self.find_media_by_slug(slug)
            if existing:
                return existing

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        raw = path.read_bytes()
        boundary = f"----KivantosFormBoundary{uuid.uuid4().hex}"
        disposition_name = path.name
        parts: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )

        if title:
            add_field("title", title)
        if alt_text:
            add_field("alt_text", alt_text)
        if slug:
            add_field("slug", slug)

        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{disposition_name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(raw)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        data = self.request(
            "POST",
            "/wp/v2/media",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            auth=True,
        )
        if not isinstance(data, dict):
            raise WordPressError(f"Unexpected media upload payload for {path.name}")
        return data

    # --- menus -------------------------------------------------------------

    def list_menus(self) -> list:
        data = self.get("/wp/v2/menus", auth=True)
        return data if isinstance(data, list) else []

    def list_menu_items(self, *, menus: Optional[Sequence[int]] = None) -> list:
        params: dict[str, Any] = {"per_page": 100}
        if menus:
            params["menus"] = ",".join(str(m) for m in menus)
        data = self.get("/wp/v2/menu-items", params=params, auth=True)
        return data if isinstance(data, list) else []

    def ensure_menu(self, name: str, *, slug: Optional[str] = None, dry_run: bool = False) -> dict:
        menus = self.list_menus()
        want_slug = slug or _slugify(name)
        for menu in menus:
            if menu.get("slug") == want_slug or menu.get("name") == name:
                if dry_run:
                    return {"action": "keep", "id": menu.get("id"), "slug": menu.get("slug")}
                return menu
        if dry_run:
            return {"action": "create", "name": name, "slug": want_slug}
        data = self.post(
            "/wp/v2/menus",
            json_body={"name": name, "slug": want_slug},
            auth=True,
        )
        if not isinstance(data, dict):
            raise WordPressError(f"Unexpected menu create payload for {name}")
        return data

    def upsert_menu_item(
        self,
        *,
        menu_id: int,
        title: str,
        object_id: Optional[int] = None,
        object_type: str = "page",
        url: Optional[str] = None,
        parent: int = 0,
        menu_order: int = 0,
        dry_run: bool = False,
    ) -> dict:
        body: dict[str, Any] = {
            "title": title,
            "menus": menu_id,
            "parent": parent,
            "menu_order": menu_order,
            "status": "publish",
        }
        if object_id is not None:
            body["type"] = object_type
            body["object"] = object_type
            body["object_id"] = object_id
        elif url:
            body["type"] = "custom"
            body["url"] = url
        else:
            raise WordPressError("Menu item needs object_id or url")

        if dry_run:
            return {"action": "create_or_update", "body": body}

        # Best-effort match existing item by title + object_id within menu
        existing_items = self.list_menu_items(menus=[menu_id])
        match = None
        for item in existing_items:
            same_title = (item.get("title") or {}).get("rendered") == title or item.get(
                "title"
            ) == title
            same_obj = object_id is None or item.get("object_id") == object_id
            if same_title and same_obj:
                match = item
                break
        if match:
            data = self.post(
                f"/wp/v2/menu-items/{match['id']}", json_body=body, auth=True
            )
        else:
            data = self.post("/wp/v2/menu-items", json_body=body, auth=True)
        if not isinstance(data, dict):
            raise WordPressError(f"Unexpected menu-item payload for {title}")
        return data

    def _build_url(self, path: str, params: Optional[Mapping[str, Any]]) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            base = path
        else:
            cleaned = path if path.startswith("/") else f"/{path}"
            if cleaned == "/":
                base = self.config.rest_root + "/"
            else:
                base = f"{self.config.rest_root}{cleaned}"
        if not params:
            return base
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, doseq=True
        )
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{query}"


def _slugify(value: str) -> str:
    out = []
    prev_dash = False
    for ch in value.lower().strip():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-") or "menu"
