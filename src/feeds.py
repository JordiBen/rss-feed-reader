"""Feed fetching, discovery, parsing (RSS 0.9x/1.0/2.0, Atom, JSON Feed), filtering and feed generation."""
from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import hashlib
import html as htmllib
import json
import re
import urllib.robotparser
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape

import feedparser
from feedparser.datetimes import _parse_date as _fp_parse_date
import httpx
from bs4 import BeautifulSoup

from .netguard import assert_public_url

USER_AGENT = 'Mozilla/5.0 (compatible; RSSFeedReader/1.0; +https://apify.com)'
ROBOTS_AGENT = 'RSSFeedReader'
MAX_BYTES = 10 * 1024 * 1024
FEED_CT = ('rss', 'atom', 'xml', 'feed+json', 'json')
COMMON_FEED_PATHS = ('/feed', '/rss', '/rss.xml', '/feed.xml', '/atom.xml', '/index.xml', '/feed.json', '/feeds/posts/default')


def normalize_url(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        raise ValueError('empty URL')
    if '://' not in raw:
        raw = 'https://' + raw
    p = urlsplit(raw)
    if p.scheme not in ('http', 'https') or not p.hostname or not re.match(r'^[a-z0-9.-]+$', p.hostname, re.I):
        raise ValueError(f'invalid URL: {raw!r}')
    return p._replace(fragment='', path=p.path or '/').geturl()


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, allow_private: bool = False):
        self.client, self.allow_private = client, allow_private
        self.cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def allowed(self, url: str) -> bool:
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        async with self.locks.setdefault(origin, asyncio.Lock()):
            if origin not in self.cache:
                rp = None
                try:
                    await assert_public_url(origin, allow_private=self.allow_private)
                    r = await self.client.get(origin + '/robots.txt', follow_redirects=True)
                    if r.status_code < 400:
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(r.text.splitlines())
                except (httpx.HTTPError, ValueError, OSError):
                    rp = None
                self.cache[origin] = rp
        rp = self.cache[origin]
        return rp is None or rp.can_fetch(ROBOTS_AGENT, url)


async def fetch(client: httpx.AsyncClient, url: str, *, allow_private: bool = False,
                headers: dict | None = None) -> tuple[bytes, str, int, dict]:
    """GET with SSRF check on every redirect hop. Returns (body, final_url, status, headers)."""
    current = url
    for _ in range(10):
        await assert_public_url(current, allow_private=allow_private)
        async with client.stream('GET', current, follow_redirects=False, headers=headers or {}) as r:
            if r.is_redirect and 'location' in r.headers:
                current = urljoin(current, r.headers['location'])
                continue
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise ValueError('response larger than 10 MB')
            return bytes(buf), current, r.status_code, dict(r.headers)
    raise ValueError('too many redirects')


def looks_like_feed(body: bytes, ctype: str = '') -> bool:
    head = body[:2000].lstrip().lower()
    if head.startswith(b'{'):
        return b'jsonfeed.org' in body[:4000]
    if any(t in (ctype or '').lower() for t in ('rss', 'atom')):
        return True
    return bool(re.search(rb'<(rss|feed|rdf:rdf)[\s>]', head))


def discover_feeds(html: str, base_url: str) -> list[str]:
    """<link rel=alternate type=rss/atom/json> in a page, plus <a> links that look like feeds."""
    soup = BeautifulSoup(html, 'lxml')
    out: list[str] = []
    for link in soup.find_all('link', href=True):
        rel = ' '.join(link.get('rel') or []).lower()
        typ = (link.get('type') or '').lower()
        if 'alternate' in rel and any(t in typ for t in ('rss', 'atom', 'feed+json')):
            u = urljoin(base_url, link['href'])
            if u not in out and not re.search(r'/comments/feed/?$', u):
                out.append(u)
    if not out:
        for a in soup.find_all('a', href=True):
            h = a['href']
            if re.search(r'(\.rss|\.atom|/rss/?|/feed/?|rss\.xml|atom\.xml|feed\.xml)$', h, re.I):
                u = urljoin(base_url, h)
                if u not in out:
                    out.append(u)
    return out[:5]


def _iso(t) -> str | None:
    if not t:
        return None
    try:
        return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc).isoformat(timespec='seconds')
    except (TypeError, ValueError, OverflowError):
        return None


def parse_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        t = _fp_parse_date(s)
        return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc) if t else None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _iso_s(s: str | None) -> str | None:
    d = parse_date(s)
    return d.astimezone(dt.timezone.utc).isoformat(timespec='seconds') if d else None


def html_to_text(s: str | None) -> str | None:
    if not s:
        return None
    if '<' not in s and '&' not in s:
        return s.strip() or None
    txt = BeautifulSoup(s, 'lxml').get_text(' ', strip=True)
    return re.sub(r'\s+', ' ', htmllib.unescape(txt)).strip() or None


def item_id(e: dict) -> str:
    key = e.get('guid') or e.get('link') or f"{e.get('title')}|{e.get('published')}"
    return hashlib.sha1(str(key).encode()).hexdigest()[:20]


def _json_feed(body: bytes, url: str) -> tuple[dict, list[dict]]:
    d = json.loads(body.decode('utf-8', errors='replace'))
    feed = {'feedTitle': d.get('title'), 'feedLink': d.get('home_page_url'), 'feedDescription': d.get('description'),
            'feedLanguage': d.get('language'), 'feedFormat': 'json' + (d.get('version', '').rstrip('/').rsplit('/', 1)[-1] or '')}
    items = []
    for it in d.get('items') or []:
        authors = it.get('authors') or ([it['author']] if it.get('author') else [])
        content = it.get('content_html') or it.get('content_text')
        items.append({
            'guid': it.get('id'), 'title': it.get('title'), 'link': urljoin(url, it.get('url') or '') or None,
            'published': _iso_s(it.get('date_published')), 'updated': _iso_s(it.get('date_modified')),
            'author': ', '.join(a.get('name', '') for a in authors if isinstance(a, dict)) or None,
            'summary': html_to_text(it.get('summary') or content)[:2000] if (it.get('summary') or content) else None,
            'contentHtml': it.get('content_html'),
            'categories': it.get('tags') or [], 'image': it.get('image') or it.get('banner_image'),
            'enclosures': [{'url': a.get('url'), 'type': a.get('mime_type'), 'length': a.get('size_in_bytes')}
                           for a in it.get('attachments') or []],
        })
    return feed, items


def parse_feed(body: bytes, url: str) -> tuple[dict, list[dict]]:
    """Parse any supported feed into (feed metadata, normalized items). Raises ValueError if not a feed."""
    if body[:2000].lstrip().startswith(b'{'):
        return _json_feed(body, url)
    p = feedparser.parse(body)  # no base URL: keeps GUIDs verbatim; links resolved below
    if not p.entries and (p.bozo or not p.version):
        raise ValueError('not a valid RSS/Atom feed' + (f' ({type(p.bozo_exception).__name__})' if p.bozo else ''))
    f = p.feed
    feed = {'feedTitle': f.get('title'), 'feedLink': urljoin(url, f['link']) if f.get('link') else None, 'feedDescription': html_to_text(f.get('subtitle')),
            'feedLanguage': f.get('language'), 'feedFormat': p.version or 'unknown'}
    items = []
    for e in p.entries:
        content = (e.get('content') or [{}])[0].get('value')
        summary = e.get('summary')
        enclosures = [{'url': urljoin(url, l.get('href') or ''), 'type': l.get('type'), 'length': int(l['length']) if str(l.get('length', '')).isdigit() else None}
                      for l in e.get('links', []) if l.get('rel') == 'enclosure']
        image = None
        for m in (e.get('media_thumbnail') or []) + (e.get('media_content') or []):
            if m.get('url') and (m.get('medium') in (None, 'image') or 'image' in (m.get('type') or '')):
                image = m['url']
                break
        if not image:
            image = next((x['url'] for x in enclosures if (x.get('type') or '').startswith('image')), None)
        items.append({
            'guid': e.get('id'), 'title': html_to_text(e.get('title')), 'link': urljoin(url, e['link']) if e.get('link') else None,
            'published': _iso(dict.get(e, 'published_parsed')) or _iso(dict.get(e, 'updated_parsed')),
            'updated': _iso(dict.get(e, 'updated_parsed')),
            'author': e.get('author'),
            'summary': (html_to_text(summary) or '')[:2000] or None,
            'contentHtml': content if content and content != summary else None,
            'categories': [t.get('term') for t in e.get('tags', []) if t.get('term')],
            'image': image, 'enclosures': enclosures,
            'commentsUrl': urljoin(url, e['comments']) if e.get('comments') else None,
        })
    return feed, items


def parse_since(value: str | None, now: dt.datetime | None = None) -> dt.datetime | None:
    """'2026-10-01', ISO timestamps, or relative '7 days' / '12 hours' / '30 minutes'."""
    if not value or not str(value).strip():
        return None
    v = str(value).strip().lower()
    m = re.fullmatch(r'(\d+)\s*(minute|min|hour|h|day|d|week|w)s?(\s+ago)?', v)
    now = now or dt.datetime.now(dt.timezone.utc)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        secs = {'minute': 60, 'min': 60, 'hour': 3600, 'h': 3600, 'day': 86400, 'd': 86400, 'week': 604800, 'w': 604800}[unit]
        return now - dt.timedelta(seconds=n * secs)
    d = parse_date(value)
    if not d:
        raise ValueError(f'cannot parse date {value!r} (use e.g. 2026-10-01 or "7 days")')
    return d


def keyword_match(item: dict, include: list[str], exclude: list[str]) -> bool:
    hay = ' '.join(str(item.get(k) or '') for k in ('title', 'summary', 'contentHtml', 'author')).lower()
    hay += ' ' + ' '.join(item.get('categories') or []).lower()
    if include and not any(k.lower() in hay for k in include):
        return False
    return not any(k.lower() in hay for k in exclude)


def build_feed(items: list[dict], fmt: str, title: str, link: str = 'https://apify.com') -> tuple[str, str]:
    """Generate a merged feed (rss | atom | json). Returns (text, content type)."""
    now = dt.datetime.now(dt.timezone.utc)
    if fmt == 'json':
        doc = {'version': 'https://jsonfeed.org/version/1.1', 'title': title, 'home_page_url': link, 'items': [
            {k: v for k, v in {'id': i.get('guid') or i.get('link') or i['itemId'], 'url': i.get('link'), 'title': i.get('title'),
                               'summary': i.get('summary'), 'content_html': i.get('contentHtml') or None,
                               'content_text': None if i.get('contentHtml') else (i.get('fullText') or i.get('summary') or ''),
                               'date_published': i.get('published'), 'authors': [{'name': i['author']}] if i.get('author') else None,
                               'tags': i.get('categories') or None, '_source': {'feed': i.get('feedTitle'), 'feedUrl': i.get('feedUrl')}}.items()
             if v not in (None, [])} for i in items]}
        return json.dumps(doc, ensure_ascii=False, indent=1), 'application/feed+json; charset=utf-8'
    e = lambda s: escape(str(s or ''))  # noqa: E731
    if fmt == 'atom':
        parts = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
                 f'<title>{e(title)}</title>', f'<link href="{e(link)}"/>', f'<id>{e(link)}</id>',
                 f'<updated>{now.isoformat(timespec="seconds")}</updated>']
        for i in items:
            parts += ['<entry>', f'<title>{e(i.get("title"))}</title>', f'<link href="{e(i.get("link"))}"/>',
                      f'<id>{e(i.get("guid") or i.get("link") or i["itemId"])}</id>',
                      f'<updated>{e(i.get("updated") or i.get("published") or now.isoformat(timespec="seconds"))}</updated>']
            if i.get('published'):
                parts.append(f'<published>{e(i["published"])}</published>')
            if i.get('author'):
                parts.append(f'<author><name>{e(i["author"])}</name></author>')
            if i.get('summary'):
                parts.append(f'<summary>{e(i["summary"])}</summary>')
            parts += [f'<category term="{e(c)}"/>' for c in i.get('categories') or []]
            parts.append('</entry>')
        parts.append('</feed>')
        return '\n'.join(parts), 'application/atom+xml; charset=utf-8'
    from email.utils import format_datetime
    parts = ['<?xml version="1.0" encoding="utf-8"?>', '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">', '<channel>',
             f'<title>{e(title)}</title>', f'<link>{e(link)}</link>', f'<description>{e(title)}</description>',
             f'<lastBuildDate>{format_datetime(now)}</lastBuildDate>']
    for i in items:
        parts += ['<item>', f'<title>{e(i.get("title"))}</title>']
        if i.get('link'):
            parts.append(f'<link>{e(i["link"])}</link>')
        parts.append(f'<guid isPermaLink="false">{e(i.get("guid") or i.get("link") or i["itemId"])}</guid>')
        d = parse_date(i.get('published'))
        if d:
            parts.append(f'<pubDate>{format_datetime(d)}</pubDate>')
        if i.get('author'):
            parts.append(f'<dc:creator>{e(i["author"])}</dc:creator>')
        if i.get('summary'):
            parts.append(f'<description>{e(i["summary"])}</description>')
        parts += [f'<category>{e(c)}</category>' for c in i.get('categories') or []]
        for enc in i.get('enclosures') or []:
            if enc.get('url'):
                parts.append(f'<enclosure url="{e(enc["url"])}" type="{e(enc.get("type") or "application/octet-stream")}" length="{e(enc.get("length") or 0)}"/>')
        parts.append('</item>')
    parts += ['</channel>', '</rss>']
    return '\n'.join(parts), 'application/rss+xml; charset=utf-8'
