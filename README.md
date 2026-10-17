# RSS Feed Reader & News Monitor: Parse RSS, Atom and JSON Feeds to JSON

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-1f6feb?logo=apify)](https://apify.com/manageable_gully/rss-feed-reader) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Run it in the cloud with no setup:** [RSS Feed Reader & News Monitor: RSS, Atom, JSON Feed on the Apify Store](https://apify.com/manageable_gully/rss-feed-reader).  
> Pay only per result, export to JSON/CSV/Excel, schedule runs and call it from the API.
<!-- AFFILIATE_LINK_PLACEHOLDER: replace the Apify links above with the affiliate link when available -->

Read any number of **RSS, Atom and JSON feeds** and get clean, consistent JSON, CSV or Excel. Don't know the feed URL? Paste the website or blog address and the Actor finds the feed for you. Schedule it with **only-new-items** mode to monitor news, blogs, podcasts, releases, job boards or competitors, and pipe new items to Slack, Google Sheets, Zapier, Make or your own API.

## What you can use it for
- **News monitoring:** watch dozens of news sites and blogs and get only new articles that mention your brand or keywords.
- **Slack, Telegram or email alerts:** schedule hourly runs with **only new items** and send the results through a webhook or Zapier/Make.
- **AI newsletters and summaries:** collect the week's posts with full article text, then summarize them with an LLM.
- **Competitor and release tracking:** follow product blogs, changelogs and GitHub release feeds.
- **Podcast data:** episode titles, dates and audio enclosure URLs from podcast feeds.

## How to use it
1. Paste feed URLs or plain website URLs under **Feed URLs** (the feed is discovered automatically).
2. Turn on **Only new items** if you'll run it on a schedule.
3. Add keyword or date filters if you want.
4. Click **Start**, then create a schedule and an integration for alerts.

## Why this feed reader
- **Every format:** RSS 0.9x / 1.0 (RDF) / 2.0, Atom 1.0 and JSON Feed 1.0/1.1, normalized into one schema.
- **Feed discovery:** works with plain website URLs (`<link rel="alternate">` tags, then common paths like `/feed`, `/rss.xml`, `/atom.xml`, `/index.xml`).
- **Only new items:** remembers what each feed contained last time and returns only what's new. Unchanged feeds are skipped cheaply with ETag / Last-Modified conditional requests. Use separate *monitor names* for separate schedules.
- **Filters:** keywords to include or exclude (title, summary, content, author, categories) and a *published after* date, absolute (`2026-10-01`) or relative (`24 hours`, `7 days`).
- **Full article text (optional):** opens each item's link and extracts the main text as Markdown, ready for LLMs, summaries or RAG.
- **Merged output feed:** saves all returned items as one filtered RSS 2.0, Atom or JSON Feed file (`OUTPUT_FEED` in the key-value store). It works as a simple feed aggregator / feed generator.
- **Podcasts and media:** enclosures (audio/video URL, type, size) and thumbnail images included.
- **Cheap and polite:** plain HTTP, no browser, 256 MB memory. Respects robots.txt, never logs in, refuses private or internal addresses.

## Input example
```json
{
  "feedUrls": [{"url": "https://hnrss.org/frontpage"}, {"url": "https://blog.python.org"}, {"url": "https://github.blog/feed/"}],
  "maxItemsPerFeed": 20,
  "onlyNewItems": true,
  "includeKeywords": ["release", "security"],
  "publishedAfter": "7 days",
  "fetchFullText": false,
  "outputFeedFormat": "rss"
}
```

## Output (one item per feed entry)
```json
{
  "inputUrl": "https://blog.python.org/",
  "feedUrl": "https://blog.python.org/rss.xml",
  "feedTitle": "Python Insider", "feedFormat": "rss20", "feedLanguage": null,
  "title": "Python 3.16.0 alpha 1 is now available",
  "link": "https://blog.python.org/2026/10/python-3160-alpha-1-is-now-available/",
  "guid": "https://blog.python.org/2026/10/python-3160-alpha-1-is-now-available/", "itemId": "288a44c8c89ab69ffd52",
  "published": "2026-10-13T00:00:00+00:00", "updated": null,
  "author": "Savannah Ostrowski", "summary": "The first developer preview of Python 3.16 is ready for testing. ...",
  "categories": ["releases"], "image": null,
  "enclosures": [],
  "fullText": "# Python 3.16.0 alpha 1 is now available\n\n...",
  "fetchedAt": "2026-10-17T07:13:08+00:00"
}
```
Feeds that fail (not found, not a feed, blocked by robots.txt) produce a single row with `inputUrl` and `error`, and are not charged.

## Scheduled monitoring in 3 steps
1. Add your feeds and turn on **Only new items since the last run**.
2. Create a schedule (e.g. every hour) in Apify Console.
3. Add an integration (Slack, email, webhook, Google Sheets, Zapier, Make) that fires when the run succeeds.

## Limits
- Only reads what sites publish as feeds, plus the linked article page when full text is on. No logins, paywalls or JavaScript rendering.
- Feeds usually contain only the latest 10 to 100 entries. Older items are not available from the feed itself.
- Use the content in line with each publisher's terms and copyright.

## Pricing
Pay per event, no monthly rent:
- **$0.0005 per feed item** returned
- **$0.001 per full article text** (optional)

| Example | Cost |
|---|---|
| 1,000 feed items | $0.50 |
| 1,000 items with full article text | $1.50 |
| Hourly monitor of 20 feeds, about 200 new items a day, for 30 days | $3.04 |

Errors, skipped items and unchanged feeds are free.

You can set a **maximum cost per run** in the run options; the Actor stops cleanly when it is reached. New to Apify? The free plan includes $5 of platform credit every month, so you can try this Actor at no cost.

## API, integrations and AI agents (MCP)
Run it from your own code with the [Apify API](https://docs.apify.com/api/v2) and get the results in one call:
```bash
curl -X POST "https://api.apify.com/v2/acts/manageable_gully~rss-feed-reader/run-sync-get-dataset-items?token=<YOUR_APIFY_TOKEN>" \
  -H "Content-Type: application/json" -d @input.json
```
```python
from apify_client import ApifyClient
run = ApifyClient("<YOUR_APIFY_TOKEN>").actor("manageable_gully/rss-feed-reader").call(run_input={...})
```
- **No-code:** use the Apify app in **n8n, Make or Zapier** ("Run Actor", then "Get dataset items"), or send results to Google Sheets, Slack or a webhook.
- **AI agents (MCP):** add `https://mcp.apify.com?tools=manageable_gully/rss-feed-reader` to Claude, Cursor, VS Code or any MCP client and the agent can call this Actor as a tool.
- **Schedules:** run it hourly, daily or weekly from Apify Console.

## FAQ
**What if a website has no RSS feed?** The Actor first looks for feeds linked from the page and at common paths (`/feed`, `/rss.xml`, `/atom.xml`). If none exists, that URL gets an error row and is not charged. For pages without feeds, use [Web Page to Markdown](https://apify.com/manageable_gully/page-to-markdown) instead.

**Can I build my own combined RSS feed?** Yes. The merged, filtered feed is saved as RSS 2.0, Atom or JSON Feed (`OUTPUT_FEED` in the key-value store), so you can subscribe to it from any reader.

**Can AI agents use it?** Yes. It is available as a tool through the Apify MCP server (`https://mcp.apify.com?tools=manageable_gully/rss-feed-reader`) and the Apify API, and it returns structured JSON that agents can read directly.

## More tools from WebIntel Tools
- [Web Page to Markdown](https://apify.com/manageable_gully/page-to-markdown): clean Markdown and RAG chunks from any URL, for LLMs
- [Product Hunt Scraper](https://apify.com/manageable_gully/product-hunt-scraper): daily, weekly and monthly Product Hunt launches with websites
- [Google Jobs Scraper](https://apify.com/manageable_gully/google-jobs-scraper): Google for Jobs listings with salaries and apply links
- [PDF & Image OCR Extractor](https://apify.com/manageable_gully/pdf-ocr-extractor): PDFs and images to text, Markdown and tables (incl. Hebrew/Arabic)

See [all WebIntel Tools Actors](https://apify.com/manageable_gully).

*Made by WebIntel Tools. This Actor was built and is maintained with AI assistance. Report issues on the Issues tab; they are monitored daily.*

## Run from source
This repository is the full source of the [RSS Feed Reader & News Monitor: RSS, Atom, JSON Feed](https://apify.com/manageable_gully/rss-feed-reader) Actor.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest
# run locally with the Apify CLI (https://docs.apify.com/cli):
apify run --input '{...}'
```

Deploy your own copy with `apify push`. The easiest way to use it is the hosted version on the [Apify Store](https://apify.com/manageable_gully/rss-feed-reader).

<!-- AFFILIATE_LINK_PLACEHOLDER: "New to Apify? Sign up here" link goes here -->

## License
MIT, see [LICENSE](LICENSE).
