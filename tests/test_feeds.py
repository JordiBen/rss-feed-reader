import asyncio
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from src.feeds import (RobotsCache, build_feed, discover_feeds, fetch, keyword_match, looks_like_feed, normalize_url,
                       parse_feed, parse_since)
from src.main import parse_input, select_items, state_key

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Acme Blog</title><link>https://acme.test/</link><description>News &amp; updates</description><language>en</language>
<item><title>Widgets 2.0 released</title><link>https://acme.test/widgets-2</link><guid>acme-1</guid>
<pubDate>Wed, 14 Oct 2026 08:00:00 GMT</pubDate><author>dana@acme.test (Dana)</author><category>Release</category>
<description>&lt;p&gt;The &lt;b&gt;new&lt;/b&gt; widgets are here.&lt;/p&gt;</description>
<content:encoded><![CDATA[<p>Full post body with <a href="https://x.test">link</a>.</p>]]></content:encoded>
<media:thumbnail url="https://acme.test/img.jpg"/></item>
<item><title>Episode 12: Gears</title><link>https://acme.test/ep12</link><guid>acme-2</guid>
<pubDate>Mon, 05 Oct 2026 08:00:00 GMT</pubDate><description>Podcast about gears</description>
<enclosure url="https://acme.test/ep12.mp3" type="audio/mpeg" length="12345"/></item>
<item><title>Old news</title><link>https://acme.test/old</link><pubDate>Mon, 01 Jan 2024 08:00:00 GMT</pubDate><description>Ancient sponsored post</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Atom Site</title><link href="https://atom.test/"/><id>urn:x</id><updated>2026-10-10T00:00:00Z</updated>
<entry><title>First entry</title><link href="https://atom.test/1"/><id>urn:1</id><updated>2026-10-10T00:00:00Z</updated>
<published>2026-10-09T12:00:00+02:00</published><author><name>Ari</name></author><summary>Hello atom</summary></entry></feed>"""

JSONF = json.dumps({"version": "https://jsonfeed.org/version/1.1", "title": "JSON Site", "home_page_url": "https://json.test/",
                    "items": [{"id": "j1", "url": "https://json.test/a", "title": "Json item", "content_html": "<p>Body text</p>",
                               "date_published": "2026-10-11T10:00:00Z", "authors": [{"name": "Kim"}], "tags": ["ai"]}]}).encode()

PAGE = b"""<html><head><title>Acme</title><link rel="alternate" type="application/rss+xml" href="/feed.xml">
<link rel="alternate" type="application/rss+xml" href="/comments/feed/"></head><body>hi</body></html>"""
BARE = b"<html><head><title>No link tags</title></head><body>nothing</body></html>"


def test_normalize():
    assert normalize_url('acme.test/feed#x') == 'https://acme.test/feed'
    with pytest.raises(ValueError):
        normalize_url('ftp://a.b')


def test_parse_rss():
    feed, items = parse_feed(RSS, 'https://acme.test/feed.xml')
    assert feed['feedTitle'] == 'Acme Blog' and feed['feedFormat'].startswith('rss')
    a = items[0]
    assert a['title'] == 'Widgets 2.0 released' and a['guid'] == 'acme-1'
    assert a['published'] == '2026-10-14T08:00:00+00:00'
    assert a['summary'] == 'The new widgets are here.'
    assert 'Full post body' in a['contentHtml'] and a['categories'] == ['Release']
    assert a['image'] == 'https://acme.test/img.jpg'
    assert items[1]['enclosures'] == [{'url': 'https://acme.test/ep12.mp3', 'type': 'audio/mpeg', 'length': 12345}]


def test_parse_atom_and_json():
    feed, items = parse_feed(ATOM, 'https://atom.test/atom.xml')
    assert feed['feedFormat'].startswith('atom') and items[0]['author'] == 'Ari'
    assert items[0]['published'] == '2026-10-09T10:00:00+00:00'
    feed, items = parse_feed(JSONF, 'https://json.test/feed.json')
    assert feed['feedTitle'] == 'JSON Site' and feed['feedFormat'] == 'json1.1'
    assert items[0]['summary'] == 'Body text' and items[0]['author'] == 'Kim' and items[0]['published'] == '2026-10-11T10:00:00+00:00'


def test_not_a_feed():
    with pytest.raises(ValueError):
        parse_feed(b'<html><body>hello</body></html>', 'https://x.test/')
    assert looks_like_feed(RSS) and looks_like_feed(ATOM) and looks_like_feed(JSONF)
    assert not looks_like_feed(PAGE, 'text/html') and not looks_like_feed(b'{"a":1}')


def test_discover():
    assert discover_feeds(PAGE.decode(), 'https://acme.test/blog/') == ['https://acme.test/feed.xml']
    assert discover_feeds('<a href="/rss.xml">RSS</a>', 'https://b.test/') == ['https://b.test/rss.xml']


def test_since_and_filters():
    now = dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)
    assert parse_since('7 days', now) == dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
    assert parse_since('2026-10-01', now).date() == dt.date(2026, 10, 1)
    with pytest.raises(ValueError):
        parse_since('sometime', now)
    _, items = parse_feed(RSS, 'https://acme.test/feed.xml')
    urls, invalid, cfg = parse_input({'feedUrls': [{'url': 'acme.test/feed.xml'}, 'bad host!'], 'publishedAfter': '30 days',
                                      'excludeKeywords': ['sponsored'], 'maxItemsPerFeed': 10}, now)
    assert urls == ['https://acme.test/feed.xml'] and len(invalid) == 1
    sel = select_items(items, cfg, set())
    assert [i['title'] for i in sel] == ['Widgets 2.0 released', 'Episode 12: Gears']
    cfg.update(include=['gears'], since=None)
    assert [i['title'] for i in select_items(items, cfg, set())] == ['Episode 12: Gears']
    assert keyword_match({'title': 'x', 'categories': ['Release']}, ['release'], [])


def test_only_new():
    _, items = parse_feed(RSS, 'https://acme.test/feed.xml')
    _, _, cfg = parse_input({'feedUrls': ['acme.test'], 'onlyNewItems': True})
    first = select_items(items, cfg, set())
    assert len(first) == 3
    seen = {first[0]['itemId'], first[1]['itemId']}
    assert [i['title'] for i in select_items(items, cfg, seen)] == ['Old news']
    assert state_key('default', 'https://a') != state_key('other', 'https://a')


def test_input_errors():
    with pytest.raises(ValueError):
        parse_input({})
    with pytest.raises(ValueError):
        parse_input({'feedUrls': ['a.test'], 'outputFeedFormat': 'csv'})
    _, _, cfg = parse_input({'feedUrls': ['a.test'], 'maxItemsPerFeed': 0})
    assert cfg['maxItems'] == 1000


@pytest.mark.parametrize('fmt', ['rss', 'atom', 'json'])
def test_build_feed_roundtrip(fmt):
    _, items = parse_feed(RSS, 'https://acme.test/feed.xml')
    for i in items:
        i['itemId'] = 'x'
    text, ctype = build_feed(items, fmt, 'Merged <test>')
    feed, back = parse_feed(text.encode(), 'https://out.test/')
    assert feed['feedTitle'] == 'Merged <test>' and len(back) == 3
    assert back[0]['title'] == 'Widgets 2.0 released' and back[0]['published'] == '2026-10-14T08:00:00+00:00'
    assert fmt in ctype or (fmt == 'json' and 'feed+json' in ctype)


class H(BaseHTTPRequestHandler):
    routes = {'/feed.xml': (RSS, 'application/rss+xml'), '/blog/': (PAGE, 'text/html'), '/bare/': (BARE, 'text/html'),
              '/robots.txt': (b'User-agent: *\nDisallow: /private/\n', 'text/plain')}

    def do_GET(self):  # noqa: N802
        if self.path == '/old-feed':
            self.send_response(301); self.send_header('Location', '/feed.xml'); self.end_headers(); return
        if self.path == '/feed.xml' and self.headers.get('If-None-Match') == '"v1"':
            self.send_response(304); self.end_headers(); return
        body, ct = self.routes.get(self.path, (b'nf', 'text/plain'))
        self.send_response(200 if self.path in self.routes else 404)
        self.send_header('Content-Type', ct); self.send_header('ETag', '"v1"'); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope='module')
def server():
    s = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{s.server_port}'
    s.shutdown()


def test_fetch_redirect_and_ssrf(server):
    async def go():
        async with httpx.AsyncClient() as c:
            body, final, status, hdrs = await fetch(c, server + '/old-feed', allow_private=True)
            assert status == 200 and final.endswith('/feed.xml') and looks_like_feed(body, hdrs['content-type'])
            _, _, st, _ = await fetch(c, server + '/feed.xml', allow_private=True, headers={'If-None-Match': '"v1"'})
            assert st == 304
            with pytest.raises(ValueError):
                await fetch(c, server + '/feed.xml')  # loopback refused by default
            r = RobotsCache(c, allow_private=True)
            assert await r.allowed(server + '/feed.xml') and not await r.allowed(server + '/private/x')
    asyncio.run(go())
