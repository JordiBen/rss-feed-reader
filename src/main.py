"""Apify entrypoint: read RSS / Atom / JSON feeds (or discover them from website URLs) into clean JSON.
Optional: only new items since the last run, keyword/date filters, full article text, merged output feed."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
from urllib.parse import urlsplit

import httpx
import trafilatura
from apify import Actor

from .feeds import (COMMON_FEED_PATHS, USER_AGENT, RobotsCache, build_feed, discover_feeds, fetch, item_id,
                    keyword_match, looks_like_feed, normalize_url, parse_feed, parse_since)

ITEM_EVENT = 'feed-item'
FULLTEXT_EVENT = 'full-text-extracted'
STATE_STORE = 'rss-feed-reader-state'
MAX_SEEN = 5000


def parse_input(inp: dict, now: dt.datetime | None = None) -> tuple[list[str], list[dict], dict]:
    raw = [s.get('url') if isinstance(s, dict) else s for s in (inp.get('feedUrls') or inp.get('startUrls') or inp.get('urls') or [])]
    urls, invalid = [], []
    for u in raw:
        if not u or not str(u).strip():
            continue
        try:
            n = normalize_url(str(u))
            if n not in urls:
                urls.append(n)
        except ValueError as e:
            invalid.append({'inputUrl': u, 'error': str(e)})
    if not urls and not invalid:
        raise ValueError('Provide at least one feed or website URL in "feedUrls".')
    fmt = inp.get('outputFeedFormat') or 'none'
    if fmt not in ('none', 'rss', 'atom', 'json'):
        raise ValueError('outputFeedFormat must be none, rss, atom or json')
    clean = lambda xs: [str(x).strip() for x in (xs or []) if str(x).strip()]  # noqa: E731
    cfg = {
        'maxItems': int(min(max(inp.get('maxItemsPerFeed', 50), 0), 1000)) or 1000,
        'since': parse_since(inp.get('publishedAfter'), now),
        'include': clean(inp.get('includeKeywords')), 'exclude': clean(inp.get('excludeKeywords')),
        'onlyNew': bool(inp.get('onlyNewItems', False)),
        'stateKey': str(inp.get('stateKey') or 'default')[:100],
        'discover': bool(inp.get('discoverFeeds', True)),
        'fullText': bool(inp.get('fetchFullText', False)),
        'contentHtml': bool(inp.get('includeContentHtml', False)),
        'feedFormat': fmt, 'feedTitle': str(inp.get('outputFeedTitle') or 'Merged feed')[:200],
        'concurrency': int(min(max(inp.get('maxConcurrency', 5), 1), 20)),
        'timeout': float(min(max(inp.get('timeoutSecs', 30), 5), 120)),
    }
    return urls, invalid, cfg


def state_key(state_name: str, feed_url: str) -> str:
    return 'seen-' + hashlib.sha1(f'{state_name}|{feed_url}'.encode()).hexdigest()[:24]


def select_items(items: list[dict], cfg: dict, seen: set[str]) -> list[dict]:
    """Filter (date, keywords, already seen), newest first, cap per feed."""
    out = []
    for it in items:
        it['itemId'] = item_id(it)
        if cfg['onlyNew'] and it['itemId'] in seen:
            continue
        if cfg['since']:
            pub = it.get('published')
            if not pub or dt.datetime.fromisoformat(pub) < cfg['since']:
                continue
        if not keyword_match(it, cfg['include'], cfg['exclude']):
            continue
        out.append(it)
    out.sort(key=lambda i: i.get('published') or '', reverse=True)
    return out[:cfg['maxItems']]


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        try:
            urls, invalid, cfg = parse_input(inp)
        except ValueError as e:
            await Actor.fail(status_message=str(e))
            return
        allow_private = os.environ.get('ALLOW_PRIVATE_NETWORK_FOR_LOCAL_DEV') == '1' and not Actor.is_at_home()
        for bad in invalid:
            await Actor.push_data(bad)
        store = await Actor.open_key_value_store(name=STATE_STORE) if cfg['onlyNew'] else None
        sem, page_sem, stop = asyncio.Semaphore(cfg['concurrency']), asyncio.Semaphore(cfg['concurrency'] * 2), asyncio.Event()
        delivered: list[dict] = []
        stats = {'feeds': 0, 'items': 0, 'fullText': 0, 'errors': 0, 'notModified': 0}

        async with httpx.AsyncClient(timeout=cfg['timeout'], headers={'User-Agent': USER_AGENT,
                                     'Accept': 'application/rss+xml, application/atom+xml, application/feed+json, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5'}) as client:
            robots = RobotsCache(client, allow_private)

            async def get(url: str, headers: dict | None = None):
                if not await robots.allowed(url):
                    raise PermissionError(f'disallowed by robots.txt: {url}')
                return await fetch(client, url, allow_private=allow_private, headers=headers)

            async def resolve_feed(url: str, cond: dict) -> tuple[str, bytes | None, dict]:
                """Return (feed_url, body or None if 304, headers). Discovers feeds on HTML pages."""
                body, final, status, hdrs = await get(url, cond)
                if status == 304:
                    return final, None, hdrs
                if status >= 400:
                    raise ValueError(f'HTTP {status}')
                ctype = hdrs.get('content-type', '')
                if looks_like_feed(body, ctype):
                    return final, body, hdrs
                if not cfg['discover']:
                    raise ValueError(f'not a feed ({ctype or "unknown type"}); enable "Discover feeds" to look for one on the page')
                cands = discover_feeds(body.decode('utf-8', errors='replace'), final) if b'<' in body[:5000] else []
                p = urlsplit(final)
                cands += [f'{p.scheme}://{p.netloc}{path}' for path in COMMON_FEED_PATHS]
                for c in dict.fromkeys(cands):
                    try:
                        b2, f2, s2, h2 = await get(c)
                    except Exception:  # noqa: BLE001
                        continue
                    if s2 < 400 and looks_like_feed(b2, h2.get('content-type', '')):
                        return f2, b2, h2
                raise ValueError('no RSS/Atom/JSON feed found on this page')

            async def full_text(link: str) -> str | None:
                async with page_sem:
                    try:
                        body, final, status, hdrs = await get(link)
                        if status >= 400 or 'html' not in hdrs.get('content-type', 'text/html'):
                            return None
                        html = body.decode('utf-8', errors='replace')
                        txt = await asyncio.to_thread(trafilatura.extract, html, url=final, output_format='markdown',
                                                      include_comments=False, include_tables=True, favor_recall=True)
                        return txt.strip() if txt and len(txt.strip()) >= 100 else None
                    except Exception:  # noqa: BLE001
                        return None

            async def work(url: str) -> None:
                async with sem:
                    if stop.is_set():
                        return
                    rec = {}
                    key = state_key(cfg['stateKey'], url)
                    if store:
                        rec = await store.get_value(key) or {}
                    cond = {}
                    if store and rec.get('ids'):
                        if rec.get('etag'):
                            cond['If-None-Match'] = rec['etag']
                        if rec.get('lastModified'):
                            cond['If-Modified-Since'] = rec['lastModified']
                    try:
                        feed_url, body, hdrs = await resolve_feed(url, cond)
                        if body is None:
                            stats['notModified'] += 1
                            stats['feeds'] += 1
                            return
                        feed, items = await asyncio.to_thread(parse_feed, body, feed_url)
                    except Exception as e:  # noqa: BLE001
                        stats['errors'] += 1
                        await Actor.push_data({'inputUrl': url, 'error': f'{type(e).__name__}: {e}'[:300]})
                        return
                    stats['feeds'] += 1
                    seen = set(rec.get('ids') or [])
                    chosen = select_items(items, cfg, seen)
                    texts = await asyncio.gather(*(full_text(i['link']) if cfg['fullText'] and i.get('link') else asyncio.sleep(0)
                                                   for i in chosen))
                    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
                    new_ids = []
                    for it, txt in zip(chosen, texts):
                        if stop.is_set():
                            break
                        row = {'inputUrl': url, 'feedUrl': feed_url, **feed, **it, 'fetchedAt': fetched_at}
                        if not cfg['contentHtml']:
                            row.pop('contentHtml', None)
                        if cfg['fullText']:
                            row['fullText'] = txt
                        r = await Actor.push_data(row, charged_event_name=ITEM_EVENT)
                        if r.event_charge_limit_reached:
                            stop.set()
                            if r.charged_count == 0:
                                break
                        new_ids.append(it['itemId'])
                        delivered.append(row)
                        stats['items'] += 1
                        if txt:
                            c = await Actor.charge(FULLTEXT_EVENT)
                            stats['fullText'] += 1
                            if c.event_charge_limit_reached:
                                stop.set()
                    if store:
                        # Everything in the feed right now counts as seen (items cut by the per-feed cap or filters are
                        # not 'new' next time). If the run hit the max-charge limit, only remember what was delivered.
                        current = [item_id(i) for i in items]
                        if stop.is_set():
                            current = [i for i in current if i in seen or i in new_ids]
                        keep = list(dict.fromkeys(current + [i for i in seen if i not in current]))
                        await store.set_value(key, {'feedUrl': feed_url, 'ids': keep[:MAX_SEEN], 'etag': hdrs.get('etag'),
                                                    'lastModified': hdrs.get('last-modified'), 'updatedAt': fetched_at})
                    await Actor.set_status_message(f"Feeds {stats['feeds']}/{len(urls)}, items {stats['items']}")

            await asyncio.gather(*(work(u) for u in urls))

        if cfg['feedFormat'] != 'none' and delivered:
            delivered.sort(key=lambda i: i.get('published') or '', reverse=True)
            text, ctype = build_feed(delivered, cfg['feedFormat'], cfg['feedTitle'])
            await Actor.set_value('OUTPUT_FEED', text, content_type=ctype)
        msg = (f"Done: {stats['items']} items from {stats['feeds']} feed(s)" + (f", {stats['fullText']} full texts" if cfg['fullText'] else '')
               + (f", {stats['notModified']} unchanged" if stats['notModified'] else '') + (f", {stats['errors']} error(s)" if stats['errors'] else '')
               + (' (stopped: max charge reached)' if stop.is_set() else ''))
        await Actor.set_status_message(msg, is_terminal=True)
