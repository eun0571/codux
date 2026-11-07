"""Exercise automatic discovery and the loopback server using synthetic sessions."""
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from serve_playground import PlaygroundServer, SessionLibrary, STATIC_FILES, display_record, SOURCE_WINDOW_BYTES, PREVIEW_BYTES, PREVIEW_RECORDS


class LocalPlaygroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codux-playground-test-')
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.sessions = self.home / 'sessions' / '2026' / '11' / '06'
        self.sessions.mkdir(parents=True)
        self.rollout = self.sessions / 'rollout-test.jsonl'
        self.rollout.write_text('\n'.join(map(json.dumps, [
            {'type': 'session_meta', 'payload': {'id': 'conversation', 'cwd': 'C:/code/example'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Original prompt'}},
            {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'Actual answer'}},
        ])), encoding='utf-8')
        (self.home / 'session_index.jsonl').write_text(json.dumps({'id': 'conversation', 'thread_name': 'Saved title'}) + '\n{bad\n', encoding='utf-8')
        (self.home / 'codux-ui.json').write_text(json.dumps({'active': {'cards': [], 'show_tools': True, 'unrelated': 'must not escape'}}), encoding='utf-8')
        (self.home / 'auth.json').write_text('DO NOT SERVE', encoding='utf-8')
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        for name in STATIC_FILES:
            (self.assets / name).write_text('asset', encoding='utf-8')
        (self.assets / 'index.html').write_text("connect-src 'none' <script defer src=\"palettes.js\"></script>", encoding='utf-8')
        self.server = PlaygroundServer(self.assets, self.home, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, *, token=True, method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        request_headers = {'X-Codux-Local': self.server.token} if token else {}
        request_headers.update(headers or {})
        connection.request(method, path, headers=request_headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_discover_titles_read_and_reload_without_modifying_files(self):
        original = self.rollout.read_bytes()
        status, body, headers = self.request('/api/sessions')
        self.assertEqual(status, 200)
        rows = json.loads(body)['sessions']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Saved title')
        self.assertEqual(rows[0]['project'], 'example')
        route = '/api/session/' + rows[0]['id']
        status, body, _ = self.request(route)
        self.assertEqual(status, 200)
        page = json.loads(body)
        projected = [json.loads(line) for line in page['source'].splitlines()]
        for row in projected:
            row.pop('preview_offset')
        self.assertEqual(projected, [json.loads(line) for line in original.splitlines()])
        self.assertFalse(page['window']['has_older'])
        self.assertEqual(hashlib.sha256(self.rollout.read_bytes()).digest(), hashlib.sha256(original).digest())
        # A fresh request reads new bytes rather than an obsolete browser File object.
        updated = {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'Updated answer'}}
        self.rollout.write_bytes(original + b'\n' + json.dumps(updated).encode())
        last = json.loads(json.loads(self.request(route)[1])['source'].splitlines()[-1])
        last.pop('preview_offset')
        self.assertEqual(last, updated)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_missing_title_falls_back_to_prompt_and_removed_file_is_not_read(self):
        (self.home / 'session_index.jsonl').unlink()
        rows = json.loads(self.request('/api/sessions')[1])['sessions']
        self.assertEqual(rows[0]['title'], 'Original prompt')
        self.rollout.unlink()
        self.assertEqual(self.request('/api/session/' + rows[0]['id'])[0], 404)
        self.assertEqual(json.loads(self.request('/api/sessions')[1])['sessions'], [])

    def test_reject_unrelated_paths_methods_and_cross_origin_requests(self):
        self.assertEqual(self.request('/api/sessions', token=False)[0], 403)
        self.assertEqual(self.request('/api/sessions', headers={'X-Codux-Local': 'wrong'})[0], 403)
        self.assertEqual(self.request('/api/sessions', headers={'Host': 'attacker.invalid'})[0], 403)
        self.assertEqual(self.request('/api/sessions', headers={'Origin': 'https://attacker.invalid'})[0], 403)
        self.assertEqual(self.request('/local.js', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        for route in ['/auth.json', '/../home/auth.json', '/api/session/../../auth.json', '/api/sessions?path=auth.json', '/sessions/rollout-test.jsonl']:
            self.assertEqual(self.request(route)[0], 404, route)
        self.assertEqual(self.request('/api/settings', method='POST')[0], 405)

    def test_local_bootstrap_and_settings_are_separate_from_static_site(self):
        status, body, _ = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b"connect-src 'self'", body)
        self.assertIn(b'local.js', body)
        self.assertNotIn(b'local.js', (self.assets / 'index.html').read_bytes())
        status, body, _ = self.request('/local.js')
        self.assertEqual(status, 200)
        self.assertIn(self.server.token.encode(), body)
        settings = json.loads(self.request('/api/settings')[1])['settings']
        self.assertNotIn('unrelated', settings)
        self.assertEqual(settings['show_tools'], True)
        self.assertNotIn('auth', body.decode())

    def test_only_discovered_rollouts_inside_root_can_be_read(self):
        unrelated = self.sessions / 'notes.jsonl'
        unrelated.write_text('{}', encoding='utf-8')
        self.assertEqual(len(self.server.library.list()['sessions']), 1)
        self.server.library.paths['outside'] = self.home / 'auth.json'
        with self.assertRaises(FileNotFoundError):
            self.server.library.read('outside')
        self.assertEqual(SessionLibrary(self.root / 'missing-home').list()['sessions'], [])

    def test_display_projection_keeps_text_and_replaces_images(self):
        record = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'Please inspect this image'}, {'type': 'input_image', 'image_url': 'data:image/png;base64,aGVsbG8='}]}}
        result = display_record(record)
        self.assertEqual(result['payload']['content'][0]['text'], 'Please inspect this image')
        self.assertEqual(result['payload']['content'][1]['text'], '[Image attachment]')
        self.assertNotIn('base64', json.dumps(result))
        self.assertIsNone(display_record({'type': 'response_item', 'payload': {'type': 'reasoning', 'encrypted_content': 'internal'}}))
        self.assertEqual(display_record({'type': 'compacted', 'payload': {'replacement_history': ['internal']}})['payload'], {})

    def test_bounded_pages_cover_multibyte_records_once(self):
        messages = [f'Message {i}: ' + '\u00e9' * 750 for i in range(1200)]
        self.rollout.write_text('\n'.join(json.dumps({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': message}}, ensure_ascii=False) for message in messages), encoding='utf-8')
        identifier = self.server.library.list()['sessions'][0]['id']
        before, collected, pages = None, [], 0
        while True:
            page = self.server.library.read(identifier, before)
            window = page['window']
            self.assertLessEqual(window['scanned_bytes'], SOURCE_WINDOW_BYTES)
            self.assertLessEqual(len(page['source'].encode('utf-8')), PREVIEW_BYTES)
            rows = [json.loads(line) for line in page['source'].splitlines()]
            self.assertLessEqual(len(rows), PREVIEW_RECORDS)
            self.assertEqual([r['preview_offset'] for r in rows], sorted(r['preview_offset'] for r in rows))
            collected = [r['payload']['message'] for r in rows] + collected
            pages += 1
            if not window['has_older']:
                break
            if before is not None:
                self.assertLess(window['before'], before)
            before = window['before']
            self.assertLess(pages, 30, 'Pagination must make progress')
        self.assertGreater(pages, 1)
        self.assertEqual(collected, messages)

    def test_large_message_is_explicitly_shortened_and_invalid_cursor_rejected(self):
        self.rollout.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'x' * 20000}}), encoding='utf-8')
        identifier = self.server.library.list()['sessions'][0]['id']
        page = self.server.library.read(identifier)
        self.assertEqual(page['window']['shortened'], 1)
        self.assertIn('[Text shortened for preview]', page['source'])
        self.assertEqual(self.request('/api/session/' + identifier + '?before=999999999')[0], 400)


if __name__ == '__main__':
    unittest.main()
