# Kivantos WordPress site builder

Build and maintain the **live WordPress site** (pages, menus, media, settings) over the REST API using Application Passwords. This is not a headless frontend starter.

## Why this shape

kivantos.com already runs **WordPress + WooCommerce + custom theme `kivantos-custom-*`** with marketing pages on template `page-kivantos.php` (large HTML in `post_content`). The repo had no frontend app — so the bootstrap path pushes structure/content *into* WordPress.

## Setup

```bash
cp wordpress/.env.example wordpress/.env
# fill WORDPRESS_USERNAME + WORDPRESS_APPLICATION_PASSWORD
```

Env vars:

| Variable | Required | Purpose |
|----------|----------|---------|
| `WORDPRESS_URL` | no (default `https://kivantos.com`) | Site origin |
| `WORDPRESS_USERNAME` | for writes | WP user login |
| `WORDPRESS_APPLICATION_PASSWORD` | for writes | Application Password (spaces OK) |
| `WORDPRESS_API_BASE` | no | Override REST root |
| `WORDPRESS_USER_AGENT` | no | Default `KivantosWPClient/0.1` |

Create an Application Password while logged into wp-admin via the custom login slug **`/astor/`** (default `/wp-admin/` and `/wp-login.php` are remapped to `/not_found/`). API root advertisement still mentions `wp-admin/authorize-application.php`, but that URL is blocked by the hide-login plugin — use `/astor/` instead.

## Commands

From repo root:

```bash
# Public connectivity + optional auth check
python3 -m wordpress.bootstrap smoke

# JSON snapshot of live pages/posts/media/products (+ menus/settings if authed)
python3 -m wordpress.bootstrap inventory

# Diff site_spec.json vs live + local content files
python3 -m wordpress.bootstrap plan

# Preview writes without mutating (safe without secrets)
python3 -m wordpress.bootstrap apply --dry-run

# Upsert pages / settings / media / menus (needs credentials + content HTML)
python3 -m wordpress.bootstrap apply
```

## Workflow

1. Edit IA in `site_spec.json` (pages, menus, settings, media).
2. Add/update HTML under `content/<slug>.html`.
3. `plan` → `apply --dry-run` → `apply`.
4. Leave WooCommerce system pages (`shop`, `cart`, `checkout`, `my-account`) alone.

## Layout

```
wordpress/
  client.py          # REST transport + upsert helpers
  bootstrap.py       # inventory / plan / apply
  site_spec.json     # declarative IA
  content/           # page HTML payloads
  media/             # optional upload sources
  .env.example
```
