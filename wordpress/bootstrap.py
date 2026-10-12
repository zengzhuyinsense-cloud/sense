#!/usr/bin/env python3
"""
Kivantos site bootstrap via WordPress REST API.

Commands:
  inventory   Public (and auth if available) snapshot of live site structure
  plan        Diff site_spec.json against live pages (public + local content files)
  apply       Upsert pages / menus / settings / media from the spec (needs credentials)
  smoke       Quick public connectivity check; auth check when credentials present

Examples:
  python3 -m wordpress.bootstrap inventory
  python3 -m wordpress.bootstrap plan
  python3 -m wordpress.bootstrap apply --dry-run
  python3 -m wordpress.bootstrap apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from .client import WordPressClient, WordPressConfig, WordPressError

ROOT = Path(__file__).resolve().parent
SPEC_PATH = ROOT / "site_spec.json"


def load_spec(path: Path = SPEC_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_content(page: dict) -> Optional[str]:
    rel = page.get("content_file")
    if not rel:
        return None
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def cmd_smoke(client: WordPressClient) -> int:
    idx = client.index()
    print(f"OK public API: {idx.get('name')} @ {idx.get('url')}")
    auth = idx.get("authentication") or {}
    print(f"Auth advertised: {', '.join(auth.keys()) or '(none)'}")
    namespaces = idx.get("namespaces") or []
    print(f"Namespaces ({len(namespaces)}): {', '.join(namespaces[:12])}...")
    pages = client.list_pages(
        fields="id,slug,title,status,template",
        per_page=100,
    )
    print(f"Published pages: {len(pages)}")
    for p in pages[:8]:
        title = (p.get("title") or {}).get("rendered", "")
        print(f"  - {p.get('slug')}: {title} [{p.get('template') or 'default'}]")
    if client.config.has_credentials:
        me = client.me()
        print(f"OK auth as: {me.get('name')} (id={me.get('id')}, slug={me.get('slug')})")
        try:
            settings = client.get_settings()
            print(
                f"Settings: title={settings.get('title')!r} "
                f"show_on_front={settings.get('show_on_front')!r} "
                f"page_on_front={settings.get('page_on_front')!r}"
            )
        except WordPressError as exc:
            print(f"Settings read failed: {exc}")
        try:
            menus = client.list_menus()
            print(f"Menus: {len(menus)}")
            for m in menus:
                print(f"  - {m.get('slug')} (id={m.get('id')}) name={m.get('name')}")
        except WordPressError as exc:
            print(f"Menus read failed: {exc}")
    else:
        print(
            "No credentials in env — skipped auth smoke. "
            "Set WORDPRESS_USERNAME + WORDPRESS_APPLICATION_PASSWORD to continue."
        )
    return 0


def cmd_inventory(client: WordPressClient) -> int:
    idx = client.index()
    pages = client.list_pages(
        fields="id,slug,title,status,parent,template,link,menu_order",
        per_page=100,
    )
    posts = client.list_posts(per_page=20, _fields="id,slug,title,status,link")
    media = client.list_media(
        per_page=20, _fields="id,slug,source_url,mime_type,title"
    )
    products: list = []
    try:
        products = client.get("/wc/store/v1/products", params={"per_page": 20}) or []
    except WordPressError:
        products = []

    out: dict[str, Any] = {
        "site": {"name": idx.get("name"), "url": idx.get("url")},
        "authentication": idx.get("authentication"),
        "namespace_count": len(idx.get("namespaces") or []),
        "route_count": len(idx.get("routes") or {}),
        "pages": [
            {
                "id": p.get("id"),
                "slug": p.get("slug"),
                "title": (p.get("title") or {}).get("rendered"),
                "template": p.get("template"),
                "status": p.get("status"),
                "link": p.get("link"),
            }
            for p in pages
        ],
        "posts": [
            {
                "id": p.get("id"),
                "slug": p.get("slug"),
                "title": (p.get("title") or {}).get("rendered"),
                "status": p.get("status"),
            }
            for p in posts
        ],
        "media_sample": [
            {
                "id": m.get("id"),
                "slug": m.get("slug"),
                "mime_type": m.get("mime_type"),
                "source_url": m.get("source_url"),
            }
            for m in media
        ],
        "products": [
            {"id": p.get("id"), "slug": p.get("slug"), "name": p.get("name")}
            for p in products
            if isinstance(p, dict)
        ],
        "auth_ready": client.config.has_credentials,
    }

    if client.config.has_credentials:
        try:
            out["settings"] = client.get_settings()
        except WordPressError as exc:
            out["settings_error"] = str(exc)
        try:
            out["menus"] = client.list_menus()
            out["menu_items"] = client.list_menu_items()
        except WordPressError as exc:
            out["menus_error"] = str(exc)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_plan(client: WordPressClient, spec: dict) -> int:
    live_pages = {
        p.get("slug"): p
        for p in client.list_pages(
            fields="id,slug,title,status,template,link",
            per_page=100,
        )
    }
    print("Page plan (spec → live):")
    for page in spec.get("pages") or []:
        slug = page["slug"]
        live = live_pages.get(slug)
        content_path = ROOT / page["content_file"] if page.get("content_file") else None
        content_state = (
            "present"
            if content_path and content_path.is_file()
            else "missing-local-html"
            if content_path
            else "no-content-file"
        )
        if live:
            live_title = (live.get("title") or {}).get("rendered")
            template = live.get("template") or ""
            action = "update" if content_state == "present" else "keep-remote"
            print(
                f"  [{action}] {slug} id={live.get('id')} "
                f"template={template!r} content={content_state} "
                f"title_live={live_title!r}"
            )
        else:
            print(f"  [create] {slug} content={content_state} title={page.get('title')!r}")

    orphan = set(live_pages) - {p["slug"] for p in spec.get("pages") or []}
    # Woo system pages are expected orphans
    woo = {"shop", "cart", "checkout", "my-account"}
    interesting = sorted(slug for slug in orphan if slug not in woo)
    if interesting:
        print("Live pages not in spec (left alone):")
        for slug in interesting:
            print(f"  - {slug} id={live_pages[slug].get('id')}")
    if orphan & woo:
        print(f"WooCommerce system pages (ignored): {', '.join(sorted(orphan & woo))}")

    print("\nMenu plan:")
    for menu in spec.get("menus") or []:
        print(f"  menu {menu.get('slug')}: {len(menu.get('items') or [])} items")
        if not client.config.has_credentials:
            print("    (apply needs credentials to read/write menus)")

    print("\nSettings plan:")
    for key, value in (spec.get("settings") or {}).items():
        print(f"  {key}: {value!r}")

    media_specs = spec.get("media") or []
    if media_specs:
        print("\nMedia plan:")
        for item in media_specs:
            path = ROOT / item["file"]
            state = "file-ready" if path.is_file() else "file-missing"
            print(f"  [{state}] {item.get('slug')} ← {item.get('file')}")

    if not client.config.has_credentials:
        print(
            "\nBlocker: no Application Password in env. "
            "Plan is read-only public diff; apply will not run until credentials exist."
        )
    return 0


def cmd_apply(client: WordPressClient, spec: dict, *, dry_run: bool) -> int:
    if not client.config.has_credentials and not dry_run:
        print(
            "Refusing apply: set WORDPRESS_USERNAME and WORDPRESS_APPLICATION_PASSWORD "
            "(or pass --dry-run).",
            file=sys.stderr,
        )
        return 2

    me = None
    if client.config.has_credentials:
        me = client.me()
        print(f"Authenticated as {me.get('name')} (id={me.get('id')})")
    elif dry_run:
        print("Dry-run without credentials — showing intended writes only.")

    slug_to_id: dict[str, int] = {}

    # Pages
    print("\n== Pages ==")
    for page in spec.get("pages") or []:
        content = resolve_content(page)
        if content is None and page.get("content_file"):
            print(
                f"  skip content for {page['slug']}: missing {page['content_file']} "
                "(will still upsert title/template/status)"
            )
        result = client.upsert_page(
            slug=page["slug"],
            title=page["title"],
            content=content,
            status=page.get("status", "publish"),
            template=page.get("template"),
            dry_run=dry_run or not client.config.has_credentials,
        )
        if dry_run or not client.config.has_credentials:
            print(f"  plan {result}")
        else:
            slug_to_id[page["slug"]] = int(result["id"])
            print(
                f"  upserted {page['slug']} → id={result['id']} link={result.get('link')}"
            )

    # Refresh slug map from live if needed
    if client.config.has_credentials and not dry_run:
        for p in client.list_pages(
            fields="id,slug", per_page=100, status="publish,draft,private"
        ):
            slug_to_id[p["slug"]] = int(p["id"])

    # Settings (front page)
    print("\n== Settings ==")
    settings_spec = dict(spec.get("settings") or {})
    front_slug = settings_spec.pop("page_on_front_slug", None)
    patch: dict[str, Any] = {
        k: v for k, v in settings_spec.items() if k in {"title", "description", "show_on_front"}
    }
    if front_slug and front_slug in slug_to_id:
        patch["page_on_front"] = slug_to_id[front_slug]
    if dry_run or not client.config.has_credentials:
        print(f"  plan settings {patch}")
    elif patch:
        updated = client.update_settings(patch)
        print(
            f"  updated title={updated.get('title')!r} "
            f"show_on_front={updated.get('show_on_front')!r} "
            f"page_on_front={updated.get('page_on_front')!r}"
        )
    else:
        print("  nothing to patch")

    # Media
    print("\n== Media ==")
    for item in spec.get("media") or []:
        path = ROOT / item["file"]
        if not path.is_file():
            print(f"  skip {item.get('slug')}: missing file {item['file']}")
            continue
        if dry_run or not client.config.has_credentials:
            print(f"  plan upload {item.get('slug')} ← {path.name}")
            continue
        uploaded = client.upload_media(
            path,
            title=item.get("title"),
            alt_text=item.get("alt_text"),
            slug=item.get("slug"),
        )
        print(f"  media {item.get('slug')} → id={uploaded.get('id')} {uploaded.get('source_url')}")

    # Menus
    print("\n== Menus ==")
    for menu_spec in spec.get("menus") or []:
        if dry_run or not client.config.has_credentials:
            print(
                f"  plan menu {menu_spec.get('slug')} "
                f"({len(menu_spec.get('items') or [])} items)"
            )
            continue
        menu = client.ensure_menu(menu_spec["name"], slug=menu_spec.get("slug"))
        menu_id = int(menu["id"])
        print(f"  menu {menu.get('slug')} id={menu_id}")
        for order, item in enumerate(menu_spec.get("items") or [], start=1):
            page_slug = item.get("page_slug")
            object_id = slug_to_id.get(page_slug) if page_slug else None
            if page_slug and object_id is None:
                print(f"    skip item {item.get('title')}: page slug {page_slug} not found")
                continue
            saved = client.upsert_menu_item(
                menu_id=menu_id,
                title=item["title"],
                object_id=object_id,
                url=item.get("url"),
                menu_order=order,
            )
            print(f"    item {item.get('title')} → id={saved.get('id')}")

    print("\nDone.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kivantos WordPress site bootstrap")
    parser.add_argument(
        "command",
        choices=["smoke", "inventory", "plan", "apply"],
        help="bootstrap action",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="for apply: print planned writes without mutating",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=SPEC_PATH,
        help="path to site_spec.json",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = WordPressClient(WordPressConfig.from_env())
    try:
        if args.command == "smoke":
            return cmd_smoke(client)
        if args.command == "inventory":
            return cmd_inventory(client)
        spec = load_spec(args.spec)
        if args.command == "plan":
            return cmd_plan(client, spec)
        if args.command == "apply":
            return cmd_apply(client, spec, dry_run=args.dry_run)
    except WordPressError as exc:
        print(f"WordPress error: {exc}", file=sys.stderr)
        if exc.payload:
            print(json.dumps(exc.payload, indent=2)[:2000], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
