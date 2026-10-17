# RSS Feed Reader & Monitor: RSS, Atom, JSON Feed to JSON

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-1f6feb?logo=apify)](https://apify.com/manageable_gully/rss-feed-reader) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Run it in the cloud with no setup:** [RSS Feed Reader & Monitor: RSS, Atom, JSON Feed to JSON on the Apify Store](https://apify.com/manageable_gully/rss-feed-reader).  
> Pay only per result, export to JSON/CSV/Excel, schedule runs and call it from the API.
<!-- Note: the Apify Store page goes live once the Actor is published. -->
<!-- AFFILIATE_LINK_PLACEHOLDER: replace the Apify links above with the affiliate link when available -->

Read any number of **RSS, Atom and JSON feeds** and get clean, consistent JSON, CSV or Excel. Don't know the feed URL? Paste the website or blog address and the Actor finds the feed for you. Schedule it with **only-new-items** mode to monitor news, blogs, podcasts, releases, job boards or competitors, and pipe new items to Slack, Google Sheets, Zapier, Make or your own API.

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

## Pricing
Pay per event:
- **$0.0005 per feed item** returned ($0.50 per 1,000 items), after filters and deduplication.
- **$0.001 per full article text**, only if you turn it on and text is found.
- Errors, skipped items and unchanged feeds are free. Platform usage is minimal (256 MB, typically a few seconds per run).

## Limits
- Only reads what sites publish as feeds, plus the linked article page when full text is on. No logins, paywalls or JavaScript rendering.
- Feeds usually contain only the latest 10 to 100 entries. Older items are not available from the feed itself.
- Use the content in line with each publisher's terms and copyright.

*This Actor was built and is maintained with AI assistance. Report issues on the Issues tab; they are monitored daily.*

## Run from source
This repository is the full source of the [RSS Feed Reader & Monitor: RSS, Atom, JSON Feed to JSON](https://apify.com/manageable_gully/rss-feed-reader) Actor.

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
