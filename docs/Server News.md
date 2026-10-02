# Server setup News

Interactive setup optionally asks for a News title and content, defaulting to
`Embleo Server` and `Welcome to Tales of Luminaria.`. Declining leaves the News
file unchanged. The APK patcher and asset-server configuration are separate.

At the end of successful setup, `scripts/generate/generate_server_news.py`
prepends a `server-setup` entry to `offline_responses/api/news/list.json`.
Existing announcements are preserved. Repeated setup replaces that entry
rather than accumulating notices. Its date is setup completion time; the
existing template's publication-window duration and field types are preserved.
Title and content are operator-provided text, with content line breaks rendered
as `<br>`. No asset URL or Git metadata is automatically included.

Automated installations can set these environment variables without prompts:

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMBLEO_NEWS_ENABLED` | `1` | Use `0`, `false`, or `no` to leave News unchanged |
| `EMBLEO_NEWS_TITLE` | `Embleo Server` | Notice title |
| `EMBLEO_NEWS_CONTENT` | `Welcome to Tales of Luminaria.` | Notice content; accepts line breaks |

You can also edit the News file locally. Running setup again replaces only
the generated notice when enabled.
