"""Offline contract tests. These do not count as proof on public links."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
import base64
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from readers import common, github, instagram, pdf, reddit, web, x, youtube


def x_post(post_id, text, *, author="writer", parent_id=None):
    return {"id": str(post_id), "text": text, "author": {"name": "Writer", "screen_name": author},
            "created_timestamp": 1700000000 + int(post_id), "media": {}, "replies": 1,
            "replying_to": {"status": str(parent_id), "screen_name": author} if parent_id else None}


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='T9-reader-fixture-'))
        self.env = patch.dict(os.environ, {"CAPTURE_READER_STATE": str(self.directory / 'state')})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def result(self, url):
        value = common.envelope(url)
        value['canonical_url'] = common.canonicalize(url)
        return value

    def test_domain_boundaries_and_pdf_queries(self):
        self.assertEqual(common.source_for('https://x.com.evil.example/status/20'), 'web')
        self.assertEqual(common.source_for('https://example.org/guide.pdf?utm_source=share'), 'pdf')
        self.assertEqual(common.source_for('https://old.reddit.com/r/python/comments/abc'), 'reddit')

    def test_tracking_removal_keeps_semantic_article_query(self):
        self.assertEqual(common.canonicalize('https://example.org/a?q=hello&utm_source=x#top'), 'https://example.org/a?q=hello')
        self.assertEqual(common.canonicalize('https://youtu.be/fNk_zzaMoSs?si=x&t=20'), 'https://www.youtube.com/watch?v=fNk_zzaMoSs')
        self.assertEqual(common.canonicalize('https://twitter.com/writer/status/20?s=46&t=abc'), 'https://x.com/writer/status/20')

    def test_invalid_and_local_urls_are_unsupported(self):
        for url in ('file:///tmp/a', 'https://name:password@example.org', 'http://localhost:1234', 'https://[bad'):
            with self.assertRaises(common.ReaderError):
                common.canonicalize(url)

    def test_raw_save_never_overwrites(self):
        common.save_bytes(self.directory, 'raw.pdf', b'original')
        with self.assertRaises(FileExistsError):
            common.save_bytes(self.directory, 'raw.pdf', b'changed')
        self.assertEqual((self.directory / 'raw.pdf').read_bytes(), b'original')

    def test_reader_lock_prevents_two_workers(self):
        with common.reader_lock('x'):
            with self.assertRaises(common.ReaderError):
                with common.reader_lock('x'):
                    pass

    def test_x_middle_link_reads_parent_and_children_and_excludes_other_authors(self):
        posts = {str(i): x_post(i, f'Exact post {i}\nline two', parent_id=i-1 if i > 20 else None) for i in (20, 21, 22)}
        calls = []
        def api(route, result):
            calls.append(route)
            if route == 'thread/20':
                return {'status': {'type': 'thread', 'thread': [posts['22'], x_post(23, 'Other author', author='other'), posts['20'], posts['21']]}}
            return {'status': posts[route.split('/')[-1]]}
        result = self.result('https://x.com/writer/status/21')
        with patch.object(x, 'api', side_effect=api):
            x.read(result, self.directory)
        self.assertEqual(result['text'], '\n\n'.join(posts[str(i)]['text'] for i in (20, 21, 22)))
        self.assertEqual(result['canonical_url'], 'https://x.com/writer/status/20')
        self.assertEqual(result['metrics']['thread_post_ids'], ['20', '21', '22'])
        self.assertIn('status/22', calls)
        self.assertNotIn('status/23', calls)

    def test_x_unknown_thread_does_not_pass_single_post(self):
        result = self.result('https://x.com/writer/status/20')
        with patch.object(x, 'api', return_value={'status': x_post(20, 'Exact body')}):
            with self.assertRaisesRegex(common.ReaderError, 'coverage is unknown'):
                x.read(result, self.directory)
        self.assertEqual(result['text'], 'Exact body')
        self.assertNotEqual(result['status'], 'ok')

    def test_x_has_no_keyless_jina_fallback(self):
        result = self.result('https://x.com/writer/status/20')
        with patch.object(common, 'http_json', side_effect=OSError('primary down')), patch.object(common, 'http') as other:
            with self.assertRaisesRegex(common.ReaderError, 'fxtwitter: primary down'):
                x.api('status/20', result)
        other.assert_not_called()

    def test_vtt_preserves_repeated_phrases_in_new_cues(self):
        vtt = 'WEBVTT\n\n00:00.000 --> 00:01.000\nHello &amp; world\n\n00:01.000 --> 00:02.000\nHello &amp; world <c>again</c>\n\n00:02.000 --> 00:03.000\nnew words\n'
        self.assertEqual(youtube.transcript_text(vtt), 'Hello & world again new words')

    def test_youtube_prefers_human_subtitles_and_flags_auto(self):
        self.assertEqual(youtube.select_subtitle({'subtitles': {'fr': [{'ext': 'vtt', 'url': 'human'}]}, 'automatic_captions': {'en': [{'ext': 'vtt', 'url': 'auto'}]}}), ('fr', False, {'ext': 'vtt', 'url': 'human'}))
        result = self.result('https://youtu.be/fNk_zzaMoSs')
        info = {'title':'Video', 'description':'Exact description\n', 'automatic_captions': {'en': [{'ext':'vtt','url':'https://example.org/en.vtt'}]}}
        with patch.object(common, 'tool', return_value='yt-dlp'), patch.object(common, 'run', return_value=json.dumps(info)), patch.object(common, 'http', return_value=(b'WEBVTT\n\n00:00.000 --> 00:01.000\nExact caption\n', '', {})):
            youtube.read(result, self.directory)
        self.assertEqual(result['text'], 'Exact description\n')
        self.assertEqual(result['transcript'], 'Exact caption')
        self.assertTrue(result['metrics']['subtitles_auto'])
        self.assertTrue(list(self.directory.glob('*.vtt')))

    def test_youtube_missing_subtitles_is_error(self):
        with self.assertRaisesRegex(common.ReaderError, 'no readable subtitles'):
            youtube.select_subtitle({})

    def test_youtube_prefers_original_english_over_rate_limited_translation(self):
        info = {'automatic_captions': {
            'en': [{'ext': 'vtt', 'url': 'translated-track'}],
            'ar-orig': [{'ext': 'vtt', 'url': 'dubbed-track'}],
            'en-orig': [{'ext': 'vtt', 'url': 'original-track'}]}}
        self.assertEqual(youtube.select_subtitle(info), ('en-orig', True, {'ext': 'vtt', 'url': 'original-track'}))

    def test_github_preserves_readme_and_tree_depth(self):
        readme = '# Real README\n\n  code indentation\n\n'
        def api(endpoint):
            if endpoint == 'repos/octocat/Hello-World': return {'full_name':'octocat/Hello-World','owner':{'login':'octocat'},'stargazers_count':42,'language':'Python','license':{'spdx_id':'MIT'},'default_branch':'main'}
            if endpoint.endswith('/readme'): return {'encoding':'base64','content':base64.b64encode(readme.encode()).decode(),'path':'README.md'}
            if '/commits?' in endpoint: return [{'sha':'commit','commit':{'committer':{'date':'2026-01-01T12:00:00Z'}}}]
            if endpoint.endswith('/commit'): return {'tree':[{'path':'README.md','type':'blob','sha':'readme'},{'path':'src','type':'tree','sha':'src'}]}
            if endpoint.endswith('/src'): return {'tree':[{'path':'main.py','type':'blob','sha':'main'},{'path':'nested','type':'tree','sha':'nested'}]}
            raise AssertionError(endpoint)
        result = self.result('https://github.com/octocat/Hello-World')
        with patch.object(github, 'api', side_effect=api):
            github.read(result, self.directory)
        self.assertEqual(result['text'], readme)
        self.assertEqual([entry['path'] for entry in result['repo']['tree']], ['README.md','src','src/main.py','src/nested'])
        self.assertEqual(result['repo']['stars'], 42)
        self.assertFalse(list(self.directory.glob('*summary*')))

    def test_github_private_repository_stops_before_readme(self):
        result = self.result('https://github.com/owner/private')
        with patch.object(github, 'api', return_value={'private':True}) as api:
            with self.assertRaises(common.ReaderError) as error:
                github.read(result, self.directory)
        self.assertEqual(error.exception.status, 'needs-login')
        self.assertEqual(api.call_count, 1)

    def test_reddit_keeps_post_body_and_top_comments(self):
        result = self.result('https://www.reddit.com/r/python/comments/abc/post/')
        data = [{'data':{'children':[{'data':{'id':'abc','title':'Post','author':'person','selftext':'Exact post\n','permalink':'/r/python/comments/abc/post/'}}]}}, {'data':{'children':[{'kind':'t1','data':{'author':'b','body':'second','score':1}},{'kind':'more','data':{}},{'kind':'t1','data':{'author':'a','body':'first\n','score':5}}]}}]
        with patch.object(reddit, 'token', return_value='t0ken'), patch.object(common, 'http_json', return_value=data) as read:
            reddit.read(result, self.directory)
        self.assertTrue(read.call_args.args[0].startswith('https://oauth.reddit.com/comments/abc?'))
        self.assertEqual(read.call_args.kwargs['headers'], {'Authorization': 'Bearer t0ken'})
        self.assertEqual(result['text'], 'Exact post\n')
        self.assertEqual(result['comments'][0], {'author':'a','text':'first\n','score':5})

    def test_reddit_without_app_needs_login_with_the_setup_line(self):
        result = self.result('https://www.reddit.com/r/python/comments/abc/post/')
        with patch.object(reddit, 'secret', return_value=None), patch.object(common, 'http_json') as read:
            with self.assertRaises(common.ReaderError) as error:
                reddit.read(result, self.directory)
        self.assertEqual(error.exception.status, 'needs-login')
        self.assertIn('reddit.com/prefs/apps', str(error.exception))
        self.assertIn('browse', str(error.exception))
        read.assert_not_called()

    def test_reddit_token_uses_app_login_and_never_prints_the_secret(self):
        with patch.object(reddit, 'secret', side_effect=['id1', 'sec1']), patch.object(common, 'http_json', return_value={'access_token': 'tok'}) as post:
            self.assertEqual(reddit.token(), 'tok')
        self.assertEqual(post.call_args.args[0], 'https://www.reddit.com/api/v1/access_token')
        self.assertEqual(post.call_args.kwargs['data'], b'grant_type=client_credentials')
        with patch.object(reddit, 'secret', side_effect=['id1', 'sec1']), patch.object(common, 'http_json', side_effect=HTTPError('u', 401, 'No', {}, None)):
            with self.assertRaises(common.ReaderError) as error:
                reddit.token()
        self.assertEqual(error.exception.status, 'needs-login')
        self.assertNotIn('sec1', str(error.exception))

    def test_reddit_share_resolves_even_when_target_page_is_blocked(self):
        url = 'https://www.reddit.com/r/python/comments/abc/post/'
        result = self.result('https://www.reddit.com/r/python/s/sharecode')
        data = [{'data': {'children': [{'data': {'id': 'abc', 'title': 'Post', 'selftext': 'Exact body', 'permalink': '/r/python/comments/abc/post/'}}]}}, {'data': {'children': []}}]
        with patch.object(common, 'http', side_effect=HTTPError(url, 403, 'Blocked', {}, None)), patch.object(reddit, 'token', return_value='t'), patch.object(common, 'http_json', return_value=data):
            reddit.read(result, self.directory)
        self.assertEqual(result['canonical_url'], url)
        self.assertEqual(result['text'], 'Exact body')

    def test_web_restores_real_video_thumbnail_without_changing_body_words(self):
        target = 'https://www.youtube.com/watch?v=Jf8bItQUaUM'
        image = 'https://img.youtube.com/vi/Jf8bItQUaUM/maxresdefault.jpg'
        raw = f'<p>Exact words.</p><a href="{target}"><img src="{image}"></a>'
        broken = f'Exact words.\n\n[\n![](https://www.youtube.com/watch?v=vi)\n]({target})\n'
        content, count = web.repair_link_images(broken, raw, 'https://forum.obsidian.md/t/post/1')
        self.assertEqual(content, broken.replace('https://www.youtube.com/watch?v=vi', image))
        self.assertEqual(count, 1)

    def test_web_keeps_html_and_defuddle_markdown(self):
        result = self.result('https://example.org/article')
        raw = b'<html><article>Original body</article></html>'
        with patch.object(common, 'http', return_value=(raw,result['url'],{})), patch.object(common, 'tool', return_value='defuddle'), patch.object(common, 'run', return_value=json.dumps({'title':'Article','content':'# Exact article\n\nbody\n'})) as run:
            web.read(result, self.directory)
        self.assertEqual(result['text'], '# Exact article\n\nbody\n')
        self.assertEqual(Path(result['media'][0]['path']).read_bytes(), raw)
        self.assertEqual(result['media'][0]['kind'], 'html')
        self.assertEqual(run.call_args.kwargs['input_text'], raw.decode())

    def test_web_without_defuddle_keeps_visible_text_and_raw_html(self):
        result = self.result('https://example.org/article')
        raw = b'<html><head><title>Article</title><style>hidden</style></head><body><script>hidden</script><p>One <b>exact</b> paragraph &amp; words.</p><p>Second paragraph.</p></body></html>'
        with patch.object(common, 'http', return_value=(raw, result['url'], {})), patch.object(common, 'tool', side_effect=common.ReaderError('Missing free tool: defuddle.')):
            web.read(result, self.directory)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['reader'], 'html')
        self.assertEqual(result['title'], 'Article')
        self.assertEqual(result['text'], 'One exact paragraph & words.\n\nSecond paragraph.')
        self.assertEqual(Path(result['media'][0]['path']).read_bytes(), raw)

    def test_pdf_keeps_file_and_text(self):
        result = self.result('https://example.org/paper.pdf')
        with patch.object(common, 'http', return_value=(b'%PDF-1.4\nfixture',result['url'],{'Content-Type':'application/pdf'})), patch.object(common, 'tool', return_value='pdftotext'), patch.object(common, 'run', return_value='Exact PDF text\n\f'):
            pdf.read(result, self.directory)
        self.assertEqual(result['text'], 'Exact PDF text\n\f')
        self.assertEqual(result['media'][0]['kind'], 'pdf')
        self.assertTrue(Path(result['media'][0]['path']).exists())

    def test_instagram_public_block_and_ten_failure_stop(self):
        executable = self.directory / 'instaloader'
        executable.write_text('#!' + sys.executable + '\n')
        result = self.result('https://www.instagram.com/reel/ABC123/')
        with patch.object(common, 'tool', return_value=str(executable)), patch.object(common, 'pace'), patch.object(common, 'run', side_effect=common.ReaderError('401 login_required')):
            with self.assertRaises(common.ReaderError) as error:
                instagram.read(result, self.directory)
        self.assertEqual(error.exception.status, 'needs-login')
        self.assertEqual(instagram.failures(), 1)
        (common.state_root() / 'instagram.failures').write_text('10')
        with patch.object(common, 'run') as run:
            with self.assertRaisesRegex(common.ReaderError, '10 consecutive failures'):
                instagram.read(result, self.directory)
        run.assert_not_called()

    def test_cli_failure_still_prints_exactly_one_contract_object(self):
        cli = (Path(__file__).resolve().parent / '../../capture-read')
        output = subprocess.run([sys.executable, str(cli), 'file:///tmp/not-public'], capture_output=True, text=True)
        result = json.loads(output.stdout)
        self.assertEqual(len(output.stdout.splitlines()), 1)
        self.assertEqual(result['status'], 'unsupported')
        self.assertNotEqual(output.returncode, 0)
        self.assertEqual(set(result), set(common.envelope('https://example.org')))
        self.assertIsNotNone(result['error'])


class LocalSite:
    """A loopback server that plays a public site. Tests allow only 127.0.0.1 as public."""
    def __init__(self, routes):
        self.requests = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append(self.path)
                status, headers, body = routes.get(self.path, (404, {}, b"missing"))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value.replace("PORT", str(site.port)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


REAL_BLOCKED = common.blocked_address


def loopback_is_public(address):
    return False if address == ipaddress.ip_address("127.0.0.1") else REAL_BLOCKED(address)


def no_dns(*args, **kwargs):
    raise AssertionError("this check must not need DNS")


class PrivateNetworkTests(unittest.TestCase):
    """T750 F03: no request reaches a private, local, or reserved address."""
    LITERALS = (
        "127.0.0.1", "127.0.0.2", "127.255.255.254", "0.0.0.0", "0.1.2.3", "10.0.0.1", "172.16.0.1",
        "192.168.1.1", "169.254.169.254", "100.64.0.1", "192.0.0.1", "198.18.0.1", "224.0.0.1",
        "239.255.255.250", "240.0.0.1", "255.255.255.255", "[::1]", "[::]", "[::ffff:127.0.0.1]",
        "[::ffff:7f00:1]", "[::ffff:10.0.0.1]", "[::ffff:169.254.169.254]", "[fe80::1]", "[fc00::1]",
        "[fd12:3456::1]", "[ff02::1]", "[2002:7f00:1::]", "[64:ff9b::7f00:1]", "[64:ff9b::a00:1]",
        "[64:ff9b:1::1]", "[::127.0.0.1]", "2130706433", "0x7f000001", "017700000001", "0177.0.0.1",
        "0x7f.0.0.1", "127.1", "127.0.1", "0", "localhost", "localhost.", "LOCALHOST", "app.localhost",
        "1.2.3.4.5", "99999999999", "1572395042", "0x5d.0xb8.0xd8.0x22", "093.184.216.34",
    )

    def test_literal_and_alternate_forms_are_refused_without_dns(self):
        with patch.object(socket, "getaddrinfo", side_effect=no_dns):
            for host in self.LITERALS:
                for url in (f"http://{host}/", f"https://{host}:8443/a?b=1"):
                    with self.subTest(url=url):
                        with self.assertRaises(common.ReaderError) as error:
                            common.public_url(url)
                        self.assertEqual(error.exception.status, "unsupported")
                        with self.assertRaises(common.ReaderError):
                            common.canonicalize(url)

    def test_public_literals_pass(self):
        with patch.object(socket, "getaddrinfo", side_effect=no_dns):
            for url in ("https://93.184.216.34/", "http://[2606:4700:4700::1111]/", "http://8.8.8.8:8080/x"):
                self.assertEqual(common.public_url(url), url)

    def test_every_resolved_address_is_checked(self):
        def answer(*addresses):
            return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443))
                    for a in addresses]
        cases = {
            ("93.184.216.34",): True,
            ("93.184.216.34", "2606:4700:4700::1111"): True,
            ("93.184.216.34", "10.0.0.5"): False,
            ("2606:4700:4700::1111", "::1"): False,
            ("::ffff:127.0.0.1",): False,
            ("fe80::1%en0",): False,
            ("169.254.169.254",): False,
        }
        for addresses, allowed in cases.items():
            with self.subTest(addresses=addresses), patch.object(socket, "getaddrinfo", return_value=answer(*addresses)):
                if allowed:
                    self.assertEqual(common.public_url("https://name.example/"), "https://name.example/")
                else:
                    with self.assertRaises(common.ReaderError) as error:
                        common.public_url("https://name.example/")
                    self.assertEqual(error.exception.status, "unsupported")
        with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("no name")):
            with self.assertRaisesRegex(common.ReaderError, "did not resolve"):
                common.public_url("https://missing.example/")

    def test_redirect_to_private_address_is_refused(self):
        for target in ("http://127.0.0.2:PORT/secret", "http://localhost.:PORT/secret",
                       "http://[::ffff:127.0.0.1]:PORT/secret", "http://2130706433:PORT/secret",
                       "http://169.254.169.254/latest/meta-data/", "ftp://127.0.0.1/secret"):
            site = LocalSite({"/start": (302, {"Location": target}, b""), "/secret": (200, {}, b"local secret")})
            try:
                with self.subTest(target=target), patch.object(common, "blocked_address", loopback_is_public):
                    with self.assertRaises(Exception) as error:
                        common.http(f"http://127.0.0.1:{site.port}/start")
                    self.assertNotIn("local secret", str(error.exception))
                    self.assertEqual(site.requests, ["/start"], "the redirect target must not be read")
            finally:
                site.close()

    def test_connection_is_pinned_to_the_checked_address(self):
        site = LocalSite({"/ok": (200, {}, b"checked address")})
        real = socket.getaddrinfo
        lookups = []

        def rebinding(host, port, *args, **kwargs):
            if host == "rebind.example":
                lookups.append(host)
                address = "127.0.0.1" if len(lookups) == 1 else "10.9.9.9"
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]
            return real(host, port, *args, **kwargs)
        try:
            # A proxy setting must not route around the check either.
            with patch.object(common, "blocked_address", loopback_is_public), \
                    patch.object(socket, "getaddrinfo", side_effect=rebinding), \
                    patch.dict(os.environ, {"http_proxy": "http://10.9.9.9:9", "HTTP_PROXY": "http://10.9.9.9:9"}):
                body, _, _ = common.http(f"http://rebind.example:{site.port}/ok")
            self.assertEqual(body, b"checked address")
            self.assertEqual(lookups, ["rebind.example"], "the host must resolve once, then connect to that address")
        finally:
            site.close()

    def test_media_url_on_private_network_is_refused(self):
        page = b"<html><title>Article</title><p>Body words.</p></html>"
        site = LocalSite({"/article": (200, {"Content-Type": "text/html"}, page)})
        directory = Path(tempfile.mkdtemp(prefix="T750-media-"))
        try:
            for image in ("http://169.254.169.254/latest/meta-data/a.png", "http://10.0.0.1/a.png",
                          "http://[::ffff:127.0.0.1]:PORT/a.png".replace("PORT", str(site.port))):
                directory = Path(tempfile.mkdtemp(prefix="T750-media-"))
                result = common.envelope(f"http://127.0.0.1:{site.port}/article")
                result["canonical_url"] = result["url"]
                content = json.dumps({"title": "Article", "content": f"Body words.\n\n![x]({image})\n"})
                with self.subTest(image=image), patch.object(common, "blocked_address", loopback_is_public), \
                        patch.object(common, "tool", return_value="defuddle"), patch.object(common, "run", return_value=content):
                    with self.assertRaises(common.ReaderError) as error:
                        web.read(result, directory)
                    self.assertEqual(error.exception.status, "unsupported")
                    self.assertEqual([item["kind"] for item in result["media"]], ["html"])
            self.assertEqual(site.requests, ["/article"] * 3)
            with patch.object(socket, "create_connection", side_effect=AssertionError("no connection")):
                with self.assertRaises(common.ReaderError):
                    common.save_media(common.envelope("https://example.org"), directory,
                                      "http://169.254.169.254/latest/meta-data/", "image")
        finally:
            site.close()


class RedactionTests(unittest.TestCase):
    """T750 F06: no printed URL keeps its credentials."""
    SECRET = "https://reader:synthetic-pass@example.invalid/a?q=kept&token=synthetic-token&apiKey=synthetic-token#access_token=synthetic-token"

    def test_redact_url_hides_userinfo_and_credential_values(self):
        redacted = common.redact_url(self.SECRET)
        self.assertNotIn("synthetic", redacted)
        self.assertIn("[REDACTED]@example.invalid", redacted)
        self.assertIn("q=kept", redacted)
        self.assertEqual(common.redact_url(redacted), redacted)
        for url in ("https://example.org/a?q=hello", "https://www.youtube.com/watch?v=fNk_zzaMoSs"):
            self.assertEqual(common.redact_url(url), url)
        signed = "https://bucket.example/x.pdf?X-Amz-Credential=synthetic-token&X-Amz-Signature=synthetic-token&Signature=synthetic-token&Key-Pair-Id=synthetic-token&sig=synthetic-token&page=2"
        self.assertNotIn("synthetic", common.redact_url(signed))
        self.assertTrue(common.redact_url(signed).endswith("page=2"))
        self.assertNotIn("synthetic", common.redact_url("https://u:synthetic-pass@[bad/a?password=synthetic-token"))
        self.assertTrue(common.carries_secret(self.SECRET))
        self.assertFalse(common.carries_secret("https://example.org/a?token=[REDACTED]"))

    def test_rejected_credential_url_is_printed_redacted(self):
        cli = (Path(__file__).resolve().parent / '../../capture-read')
        for url in (self.SECRET, "http://127.0.0.2/a?api_key=synthetic-token",
                    "https://reader:synthetic-pass@[bad/a?password=synthetic-token"):
            with self.subTest(url=url):
                output = subprocess.run([sys.executable, str(cli), url], capture_output=True, text=True)
                self.assertNotEqual(output.returncode, 0)
                self.assertNotIn("synthetic", output.stdout + output.stderr)
                result = json.loads(output.stdout)
                self.assertEqual(result["status"], "unsupported")
                self.assertIn("[REDACTED]", result["url"])
                self.assertEqual(result["url"], result["canonical_url"])

    def test_reader_result_fields_are_redacted_before_print(self):
        result = common.envelope("https://example.org/doc.pdf")
        result["canonical_url"] = "https://example.org/doc.pdf?X-Amz-Signature=synthetic-token"
        result["media"] = [{"url": "https://cdn.example/a.png?token=synthetic-token", "path": "/x", "kind": "image"}]
        result["error"] = "failed at https://u:synthetic-pass@example.org/?sig=synthetic-token"
        self.assertNotIn("synthetic", json.dumps(common.redact_result(result)))


if __name__ == '__main__':
    unittest.main()
