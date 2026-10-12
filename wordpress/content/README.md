# Page HTML content

Put one HTML file per page slug, matching `content_file` in `../site_spec.json`.

Examples:

- `home.html` → page slug `home`
- `mint.html` → page slug `mint`

`python3 -m wordpress.bootstrap apply` upserts these into WordPress `post_content` with template `page-kivantos.php`.

Pull existing rendered content (view context only; raw editable markup needs auth):

```bash
curl -sS -A "KivantosWPClient/0.1" \
  "https://kivantos.com/wp-json/wp/v2/pages?slug=home" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['content']['rendered'][:500])"
```

After credentials exist, export editable content:

```bash
python3 - <<'PY'
from wordpress.client import WordPressClient
c = WordPressClient()
page = c.find_page_by_slug("home", include_drafts=True)
raw = c.get_page(page["id"], context="edit")
open("wordpress/content/home.html","w").write(raw["content"]["raw"])
print("wrote", len(raw["content"]["raw"]), "chars")
PY
```
