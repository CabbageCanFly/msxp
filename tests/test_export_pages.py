"""Public-only Cloudflare Pages export: allowlisted files, routes, API origin and safe rebuilds."""
from datetime import datetime, timezone
import json
import re
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from exp_tracker import server

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import character_demo  # noqa: E402
import export_pages  # noqa: E402
import preview_pages  # noqa: E402

API = 'https://api.example.org'  # Illustrative; the real API hostname is supplied at build time.
EXPECTED = {'.msxp-pages-export', '404.html', '_headers', '_redirects', 'index.html', 'live-overlay.html', 'player.html',
            'static/fonts/OFL-Fredoka.txt', 'static/fonts/OFL-Nunito.txt', 'static/fonts/fredoka-latin.woff2',
            'static/fonts/nunito-latin.woff2', 'static/leaderboard.css', 'static/live-overlay.css', 'static/product.css',
            'static/product.js', 'static/steely.png'} | {f'static/mobs/{p.name}' for p in (export_pages.WEB / 'mobs').glob('*.*')}
ROUTES = ['/streams / 200', '/streams/ / 200', '/stream/:channel /player 200', '/stream/:channel/ /player 200',
          '/live/overlay/:channel /live-overlay 200', '/live/overlay/:channel/ /live-overlay 200']


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


def get(url, origin=None):
    try:
        with urlopen(Request(url, headers={'Origin': origin} if origin else {}), timeout=30) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:return error.code, error.read(), error.headers


@pytest.fixture
def out(tmp_path):
    path = tmp_path / 'pages'
    export_pages.export(path, API)
    return path


def test_export_contains_exactly_the_public_allowlist_and_is_repeatable(out):
    first = tree(out)
    assert set(first) == EXPECTED
    assert export_pages.export(out, API) == sorted(EXPECTED)  # A rerun replaces its own output.
    assert tree(out) == first
    # Sources are copied byte for byte; only the three pages gain the public attributes.
    web = export_pages.WEB
    assert first['static/product.js'] == (web / 'product.js').read_bytes()
    assert first['player.html'] == (web / 'player.html').read_bytes().replace(
        b'<html lang="en">', f'<html lang="en" data-site="public" data-api="{API}">'.encode(), 1)


def test_private_and_developer_files_are_never_exported(out):
    names = set(tree(out))
    for private in ('admin', 'shadow', 'streams', 'overlay.js', 'overlay.css', 'leaderboard.html', 'leaderboard.js', '.py', '.sqlite', '.json', '.env'):
        assert not any(private in name.replace('live-overlay', '') for name in names), private
    text = b'\n'.join(tree(out).values())
    assert b'8766' not in text and b'/admin' not in text and b'/dev/api' not in text


def test_pages_load_only_their_own_static_files_and_developer_links_stay_hidden(out):
    export_pages.references(out)  # Raises on any unresolved or external resource.
    for name in ('index.html', 'player.html', 'live-overlay.html'):
        html = (out / name).read_text(encoding='utf-8')
        assert html.count(f'data-site="public" data-api="{API}"') == 1
        loaded = [ref for tag, attrs in re.findall(r'<([a-z]+)\b([^>]*)>', html) if tag != 'a' for ref in re.findall(r'\b(?:href|src)="([^"]*)"', attrs)]
        assert loaded and all(ref.startswith('/static/') for ref in loaded), name
    assert '[data-site=public] .dev-link { display:none; }' in (out / 'static/product.css').read_text(encoding='utf-8')
    # A third-party script, stylesheet or font would fail the build.
    for page, bad in (('index.html', '<script src="https://cdn.example.org/x.js"></script>'), ('player.html', '<link rel="stylesheet" href="//cdn.example.org/x.css">')):
        original = (out / page).read_text(encoding='utf-8')
        (out / page).write_text(original.replace('</head>', bad + '</head>'), encoding='utf-8')
        with pytest.raises(ValueError, match='external'):export_pages.references(out)
        (out / page).write_text(original, encoding='utf-8')
    css = out / 'static/product.css'
    css.write_text(css.read_text(encoding='utf-8') + '\n.x{background:url(https://cdn.example.org/a.png)}', encoding='utf-8')
    with pytest.raises(ValueError, match='external'):export_pages.references(out)


def test_product_js_contacts_only_the_configured_api_origin():
    source = (export_pages.WEB / 'product.js').read_text(encoding='utf-8')
    # Exactly two network calls, both built on the configured origin; no other request channels.
    assert re.findall(r'fetch\(([^,]*),', source) == ["String(query)?`${endpoint}?${query}`:endpoint", '`${apiOrigin}/api/players/${encodeURIComponent(channel)}/history`']
    assert re.search(r"const endpoint=channel\?`\$\{apiOrigin\}/api/players/\$\{encodeURIComponent\(channel\)\}`:`\$\{apiOrigin\}/api/players`;", source)
    for channel in ('XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon', 'import(', 'importScripts', 'new Image'):
        assert channel not in source, channel
    # Loaded URLs besides the API: the overlay preview iframe and the mob sprites, both on the page's own origin.
    assert set(re.findall(r'\.src=([^;]*);', source)) == {'url', "sprite(slug,'move')", "sprite(slug,'hit')", "sprite(slug,'die')", "sprite(pick(BOSSES),'stand')"}
    assert 'return `${location.origin}/live/overlay/${encodeURIComponent(channel)}' in source and "sprite=(slug,action)=>`/static/mobs/${slug}-${action}.${slug==='slime'?'webp':'gif'}`" in source
    # Absolute URLs are only outbound links and the SVG namespace, never fetched.
    assert set(re.findall(r'https?://[^`\'"$/]+', source)) == {'https://www.twitch.tv', 'http://www.w3.org'}


def test_mob_sprites_match_the_names_product_js_uses():
    source = (export_pages.WEB / 'product.js').read_text(encoding='utf-8')
    walkers, bosses = (re.findall(r"'([a-z-]+)'", group) for group in re.search(r'const MOBS=\[([^\]]*)\],BOSSES=\[([^\]]*)\]', source).groups())
    wanted = {f'{slug}-{action}.{"webp" if slug == "slime" else "gif"}' for slug in walkers for action in ('move', 'hit', 'die')} | {f'{slug}-stand.gif' for slug in bosses}
    # A typo would 404 silently in the browser; a stray file would be published unused.
    assert walkers and bosses and {p.name for p in (export_pages.WEB / 'mobs').iterdir()} == wanted


def test_cloudflare_rewrites_keep_public_routes_and_nothing_else(out):
    assert (out / '_redirects').read_text(encoding='utf-8').splitlines() == ROUTES
    headers = (out / '_headers').read_text(encoding='utf-8')
    # default-src 'self' keeps scripts, styles, fonts, images and frames on the Pages origin; only the API is added.
    assert f"default-src 'self'; connect-src 'self' {API};" in headers and "frame-ancestors 'self'" in headers


@pytest.fixture
def preview(out):
    httpd = preview_pages.PreviewServer(('127.0.0.1', 0), preview_pages.handler(out.resolve()))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{httpd.server_port}'
    httpd.shutdown();httpd.server_close()


def test_preview_serves_nested_routes_with_intact_urls_and_404s_developer_paths(preview):
    for path, marker in (('/', b'data-view="board"'), ('/streams', b'data-view="board"'), ('/streams/', b'data-view="board"'),
                         ('/stream/some_channel?character=3', b'data-view="player"'), ('/stream/some_channel/', b'data-view="player"'),
                         ('/live/overlay/some_channel?layout=rates&theme=day', b'data-view="overlay"'), ('/live/overlay/some_channel/', b'data-view="overlay"')):
        status, body, headers = get(preview + path)
        assert status == 200 and marker in body, path
        assert f"connect-src 'self' {API}" in headers['Content-Security-Policy']
    for path in ('/dev/streams', '/demo/leaderboard', '/dashboard/some_channel', '/admin', '/api/players', '/overlay/some_channel',
                 '/stream/a/b', '/stream/', '/live/overlay/', '/static/admin.js', '/static/shadow.js', '/../README.md'):
        status, body, _ = get(preview + path)
        assert status == 404 and b'Page not found' in body, path
    assert get(preview + '/static/fonts/nunito-latin.woff2')[2]['Cache-Control'] == 'public, max-age=86400'


def test_local_preview_uses_os_assigned_ports_and_its_own_api(tmp_path, monkeypatch):
    database = tmp_path / 'demo.sqlite3'
    character_demo.create(now=datetime.now(timezone.utc), path=database, characters=1)
    preview, api = preview_pages.with_api(database, tmp_path / 'pages-local')
    for httpd in (preview, api):threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        site, origin = f'http://127.0.0.1:{preview.server_port}', f'http://127.0.0.1:{api.server_port}'
        assert preview.server_port != api.server_port and not preview.allow_reuse_address
        status, body, _ = get(site + '/stream/synthetic_demo')
        assert status == 200 and f'data-api="{origin}"'.encode() in body
        for path in ('/api/players', '/api/players/synthetic_demo', '/api/players/synthetic_demo/history'):
            status, body, headers = get(origin + path, site)
            # 503 warming_up is a normal first answer; CORS headers are present either way.
            assert status in (200, 503) and headers['Access-Control-Allow-Origin'] == site, path
            assert status == 200 or json.loads(body)['error'] == 'warming_up'
        assert get(origin + '/api/players', 'https://elsewhere.example.org')[2]['Access-Control-Allow-Origin'] is None
        assert get(origin + '/stream/synthetic_demo')[0] == 200  # The API server is public-only, never the admin server.
        assert get(origin + '/dev/streams')[0] == 404
    finally:
        for httpd in (preview, api):httpd.shutdown();httpd.server_close()


@pytest.mark.parametrize('origin', ['http://api.example.org', 'https://api.example.org/', 'https://api.example.org/api', 'https://*.example.org',
                                    'javascript:alert(1)', 'https://API.example.org', '', 'https://api.example.org" onload="x'])
def test_malformed_api_origins_fail_clearly(tmp_path, origin):
    with pytest.raises(ValueError, match='API origin'):export_pages.export(tmp_path / 'pages', origin)
    assert not (tmp_path / 'pages').exists()
    assert export_pages.main(['--api-origin', origin, '--out', str(tmp_path / 'pages')]) == 1


def test_a_missing_api_origin_fails_instead_of_guessing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('MSXP_API_ORIGIN', raising=False)
    assert export_pages.main(['--out', str(tmp_path / 'pages')]) == 1
    assert 'set --api-origin or MSXP_API_ORIGIN' in capsys.readouterr().err and not (tmp_path / 'pages').exists()
    with pytest.raises(TypeError):export_pages.export(tmp_path / 'pages')


def test_local_and_environment_origins_and_matching_server_rule(tmp_path, monkeypatch, capsys):
    assert export_pages.ORIGIN.pattern == server.ORIGIN.pattern
    export_pages.export(tmp_path / 'local', 'http://localhost:5000')
    assert b'data-api="http://localhost:5000"' in (tmp_path / 'local' / 'index.html').read_bytes()
    monkeypatch.setenv('MSXP_API_ORIGIN', 'https://api.example.org')
    assert export_pages.main(['--out', str(tmp_path / 'env')]) == 0
    assert b'data-api="https://api.example.org"' in (tmp_path / 'env' / 'player.html').read_bytes()
    assert 'API https://api.example.org' in capsys.readouterr().out
    assert export_pages.main(['--out', str(tmp_path / 'flag'), '--api-origin', 'https://other.example.org']) == 0  # The flag wins.
    assert b'data-api="https://other.example.org"' in (tmp_path / 'flag' / 'player.html').read_bytes()


def test_refuses_to_replace_a_directory_it_did_not_create(tmp_path):
    keep = tmp_path / 'pages' / 'notes.txt'
    keep.parent.mkdir();keep.write_text('mine')
    with pytest.raises(ValueError, match='Refusing'):export_pages.export(tmp_path / 'pages', API)
    assert keep.read_text() == 'mine'
    (tmp_path / 'file').write_text('x')
    with pytest.raises(ValueError, match='Refusing'):export_pages.export(tmp_path / 'file', API)


def test_backend_pages_stay_same_origin(tmp_path):
    # The server adds only data-site, so product.js keeps relative /api requests there.
    handler = server.Handler.__new__(server.Handler)
    handler.server = type('S', (), {'public_only': True})()
    assert b'data-api' not in handler.page('player.html') and b'data-site="public"' in handler.page('player.html')
