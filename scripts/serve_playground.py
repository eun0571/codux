"""Run the local Codux playground with automatic, read-only session discovery."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
import webbrowser

from build_playground import ASSETS, ROOT, build

SOURCE_WINDOW_BYTES = 1024 * 1024
PREVIEW_BYTES = 256 * 1024
PREVIEW_RECORDS = 160
FIELD_CHARS = 8000
STATIC_FILES = {*ASSETS, 'release.js', '.nojekyll'}


def default_home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=True).encode('utf-8')


def display_record(record, text_limit=None):
    """Keep renderer inputs, excluding internal state and embedded image bytes."""
    if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
        return None
    category, payload = record.get('type'), record['payload']
    if category == 'session_meta':
        payload = {key: payload[key] for key in ('id', 'session_id', 'cwd', 'timestamp', 'cli_version') if key in payload}
    elif category == 'turn_context':
        payload = {key: payload[key] for key in ('turn_id',) if key in payload}
    elif category == 'compacted':
        payload = {}
    elif category == 'event_msg':
        if payload.get('type') not in {'item_completed', 'task_started', 'turn_started', 'task_complete',
                                       'turn_complete', 'user_message', 'agent_message', 'turn_aborted', 'error', 'warning'}:
            return None
        if payload.get('type') == 'item_completed' and payload.get('item', {}).get('type') == 'Reasoning':
            return None
    elif category == 'response_item':
        if payload.get('type') not in {'message', 'function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output'}:
            return None
        if payload.get('type') == 'message' and (payload.get('role') not in {'user', 'assistant'} or payload.get('channel') == 'analysis'):
            return None
    else:
        return None

    shortened = False
    def clean(value):
        nonlocal shortened
        if isinstance(value, dict):
            if str(value.get('type', '')).lower() in {'image', 'input_image', 'output_image', 'image_url', 'local_image'}:
                return {'type': 'text', 'text': '[Image attachment]'}
            return {key: clean(child) for key, child in value.items() if key not in {'encrypted_content', 'raw_content'}}
        if isinstance(value, list):
            return [clean(child) for child in value]
        if isinstance(value, str):
            if value.lstrip().startswith(('{', '[')) and '"image"' in value:
                try:
                    value = json.dumps(clean(json.loads(value)), ensure_ascii=False)
                except (ValueError, RecursionError):
                    pass
            if 'data:image/' in value:
                value = re.sub(r'data:image/[^;,\s]+;base64,[A-Za-z0-9+/=\r\n]+', '[Image attachment]', value)
            if text_limit and len(value) > text_limit:
                shortened = True
                value = value[:text_limit] + '\n[Text shortened for preview]'
        return value

    result = {'type': category, 'payload': clean(payload)}
    if 'timestamp' in record:
        result['timestamp'] = record['timestamp']
    if shortened:
        result['preview_shortened'] = True
    return result


class SessionLibrary:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.root = (self.home / 'sessions').resolve()
        self.paths = {}
        self.cache = {}
        self.lock = threading.Lock()

    def settings(self):
        try:
            path = self.home / 'codux-ui.json'
            if path.stat().st_size > 1024 * 1024:
                return None
            active = json.loads(path.read_text(encoding='utf-8')).get('active')
            if not isinstance(active, dict):
                return None
            keys = ('cards', 'reply', 'intermediate', 'show_tools', 'show_intermediate', 'working_animation')
            return {key: active[key] for key in keys if key in active}
        except (OSError, ValueError, AttributeError):
            return None

    def titles(self):
        titles = {}
        try:
            with (self.home / 'session_index.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        if isinstance(row.get('id'), str) and isinstance(row.get('thread_name'), str):
                            titles[row['id']] = row['thread_name'][:240]
                    except (ValueError, AttributeError):
                        continue
        except OSError:
            pass
        return titles

    def metadata(self, path, stat):
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self.cache.get(path)
        if cached and cached[0] == signature:
            return cached[1]
        info = {}
        with path.open('rb') as stream:
            prefix = stream.read(256 * 1024).decode('utf-8', errors='replace')
        for line in prefix.splitlines():
            try:
                row = json.loads(line)
                payload = row.get('payload', {})
                if not isinstance(payload, dict):
                    continue
                if row.get('type') == 'session_meta':
                    info.update(id=payload.get('id'), cwd=payload.get('cwd'))
                if info.get('title'):
                    continue
                body = None
                if row.get('type') == 'event_msg' and payload.get('type') == 'user_message':
                    body = payload.get('message')
                elif row.get('type') == 'event_msg' and payload.get('type') == 'item_completed':
                    item = payload.get('item', {})
                    if item.get('type') == 'UserMessage':
                        body = '\n'.join(part.get('text', '') for part in item.get('content', []) if isinstance(part, dict))
                elif row.get('type') == 'response_item' and payload.get('role') == 'user':
                    body = '\n'.join(part.get('text', '') for part in payload.get('content', []) if isinstance(part, dict))
                if isinstance(body, str) and body.strip() and not body.lstrip().startswith(('# AGENTS.md', '<environment_context>', '<INSTRUCTIONS>', '<send_user_message_question_reply>')):
                    info['title'] = ' '.join(body.split())[:160]
            except (ValueError, AttributeError, TypeError):
                continue
        self.cache[path] = (signature, info)
        return info

    def list(self):
        with self.lock:
            titles = self.titles()
            rows, paths = [], {}
            # Never recurse through junctions or symlinks outside the chosen sessions tree.
            for directory, dirs, names in os.walk(self.root, followlinks=False):
                base = Path(directory)
                dirs[:] = [name for name in dirs if not (base / name).is_symlink()
                           and not (base / name).is_junction()
                           and (base / name).resolve().is_relative_to(self.root)]
                for name in names:
                    if not name.startswith('rollout-') or not name.endswith('.jsonl'):
                        continue
                    candidate = base / name
                    try:
                        path = candidate.resolve(strict=True)
                        if candidate.is_symlink() or not path.is_relative_to(self.root) or not path.is_file():
                            continue
                        stat = path.stat()
                        info = self.metadata(path, stat)
                        relative = path.relative_to(self.root).as_posix()
                        identifier = hashlib.sha256(relative.encode('utf-8')).hexdigest()[:32]
                        paths[identifier] = path
                        cwd = info.get('cwd') if isinstance(info.get('cwd'), str) else ''
                        rows.append({'id': identifier, 'name': name,
                                     'title': titles.get(info.get('id')) or info.get('title') or 'Untitled conversation',
                                     'project': re.split(r'[/\\]', cwd.rstrip('/\\'))[-1], 'cwd': cwd,
                                     'modified': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                                     'size': stat.st_size})
                    except (OSError, ValueError, TypeError):
                        continue
            self.paths = paths
            current_paths = set(paths.values())
            self.cache = {path: value for path, value in self.cache.items() if path in current_paths}
            return {'root': str(self.root), 'sessions': sorted(rows, key=lambda row: row['modified'], reverse=True)}

    def read(self, identifier, before=None):
        with self.lock:
            path = self.paths.get(identifier)
        if path is None:
            raise FileNotFoundError('Session not found. Refresh the session list.')
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or resolved != path or path.is_symlink():
            raise FileNotFoundError('Session no longer belongs to this library.')
        chunks, size, skipped, shortened = [], 0, 0, 0
        with path.open('rb') as stream:
            total = os.fstat(stream.fileno()).st_size
            end = total if before is None else before
            if not 0 <= end <= total:
                raise ValueError('The excerpt cursor is no longer valid. Open the latest excerpt.')
            start = max(0, end - SOURCE_WINDOW_BYTES)
            stream.seek(start)
            raw = stream.read(end - start)
        scanned = len(raw)
        # Align the leading edge to a full JSONL record. A long record crossing
        # this bounded window is explicitly skipped rather than reading the file.
        if start:
            newline = raw.find(b'\n')
            if newline < 0:
                return {'source': '', 'window': {'before': start, 'end': end, 'total': total,
                        'has_older': True, 'scanned_bytes': scanned, 'skipped': 1, 'shortened': 0}}
            start += newline + 1
            raw = raw[newline + 1:]
        lines, offset = [], start
        for line in raw.splitlines(keepends=True):
            lines.append((offset, line))
            offset += len(line)
        cursor = end
        for offset, line in reversed(lines):
            try:
                record = display_record(json.loads(line), FIELD_CHARS)
            except (ValueError, TypeError, AttributeError, RecursionError):
                skipped += 1; cursor = offset
                continue
            if record is None:
                cursor = offset
                continue
            record['preview_offset'] = offset
            chunk = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
            if len(chunk) > PREVIEW_BYTES:
                skipped += 1; cursor = offset
                continue
            if len(chunks) >= PREVIEW_RECORDS or size + len(chunk) > PREVIEW_BYTES:
                break
            chunks.append(chunk); size += len(chunk); cursor = offset
            shortened += bool(record.get('preview_shortened'))
        # Progress even through a window containing only irrelevant records.
        if not lines:
            cursor = max(0, end - SOURCE_WINDOW_BYTES)
        return {'source': b''.join(reversed(chunks)).decode('utf-8'),
                'window': {'before': cursor, 'end': end, 'total': total, 'has_older': cursor > 0,
                           'scanned_bytes': scanned, 'skipped': skipped, 'shortened': shortened}}


class PlaygroundServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, assets, home, port=8765):
        self.assets = Path(assets).resolve()
        self.library = SessionLibrary(home)
        self.token = secrets.token_hex(32)
        super().__init__(('127.0.0.1', port), PlaygroundHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class PlaygroundHandler(BaseHTTPRequestHandler):
    server_version = 'CoduxPlayground'

    def log_message(self, *_):
        # Do not put conversation IDs, contents, or per-process tokens in access logs.
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A newer excerpt request can cancel the previous response.

    def error(self, status, message):
        self.reply(status, json_bytes({'error': message}))

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if self.headers.get('Host') != self.server.origin.removeprefix('http://'):
            self.error(403, 'Use the printed loopback URL.')
            return
        origin = self.headers.get('Origin')
        site = self.headers.get('Sec-Fetch-Site')
        navigation = path in ('/', '/index.html') and self.headers.get('Sec-Fetch-Mode') == 'navigate'
        if (origin and origin != self.server.origin) or (site not in (None, 'none', 'same-origin') and not navigation):
            self.error(403, 'Cross-origin access is not allowed.')
            return
        if path.startswith('/api/'):
            if not secrets.compare_digest(self.headers.get('X-Codux-Local', '').encode('utf-8'), self.server.token.encode('ascii')):
                self.error(403, 'Open the local playground page first.')
                return
            try:
                if path == '/api/sessions' and not parsed.query:
                    self.reply(200, json_bytes(self.server.library.list()))
                elif path == '/api/settings' and not parsed.query:
                    self.reply(200, json_bytes({'settings': self.server.library.settings()}))
                elif re.fullmatch(r'/api/session/[0-9a-f]{32}', path) and (not parsed.query or re.fullmatch(r'before=\d{1,16}', parsed.query)):
                    before = int(parsed.query.split('=')[1]) if parsed.query else None
                    self.reply(200, json_bytes(self.server.library.read(path.rsplit('/', 1)[1], before)))
                else:
                    self.error(404, 'Unknown local endpoint.')
            except (FileNotFoundError, PermissionError, OSError):
                self.error(404, 'Session unavailable. Refresh the session list.')
            except ValueError as error:
                self.error(400, str(error))
            return
        if path == '/local.js' and not parsed.query:
            bootstrap = {'token': self.server.token, 'settings': self.server.library.settings()}
            self.reply(200, b'window.PLAYGROUND_LOCAL = ' + json_bytes(bootstrap) + b';\n', 'text/javascript; charset=utf-8')
            return
        name = 'index.html' if path == '/' else path[1:]
        if name not in STATIC_FILES or parsed.query:
            self.error(404, 'Not found.')
            return
        try:
            asset = self.server.assets / name
            if asset.is_symlink() or asset.resolve().parent != self.server.assets:
                raise FileNotFoundError()
            content = asset.read_bytes()
            if name == 'index.html':
                content = content.replace(b"connect-src 'none'", b"connect-src 'self'")
                content = content.replace(b'<script defer src="palettes.js">', b'<script defer src="local.js"></script><script defer src="palettes.js">')
            content_type = 'text/javascript' if name.endswith('.js') else mimetypes.guess_type(name)[0] or 'application/octet-stream'
            self.reply(200, content, content_type + '; charset=utf-8')
        except OSError:
            self.error(404, 'Static asset missing. Rebuild the playground.')

    def do_POST(self):
        self.error(405, 'This viewer is read-only.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--codex-home', type=Path, default=default_home())
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    assets = ROOT / '.build/playground'
    build(assets)
    try:
        server = PlaygroundServer(assets, args.codex_home, args.port)
    except OSError as error:
        parser.exit(1, f'Could not start the local server: {error}\nChoose another --port if it is already in use.\n')
    print(f'Codux playground: {server.origin}/', flush=True)
    print(f'Sessions: {server.library.root}', flush=True)
    print('Read-only local viewer. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
