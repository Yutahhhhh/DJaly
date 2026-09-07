#!/usr/bin/env python3
"""Import existing local lyrics into Djaly over MCP, preserving registered lyrics."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import urllib.request

import mutagen
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

VOCAL_GENRES = {
    'hip hop', 'hip-hop', 'hiphop', 'rap', 'r&b', 'rnb', 'pop', 'j-pop', 'k-pop',
    'reggaeton', 'reggae', 'dancehall', 'soul', 'funk', 'rock', 'latin',
    'afrobeats', 'afrobeat', 'salsa', 'bachata', 'merengue', 'country',
    'disco', 'trap', 'latin pop', 'latin hip hop', 'latin trap',
}
VOCAL_SUBGENRE = re.compile(r'\b(afrobeats?|afropop|afro pop|afroswing|dance pop|dance-pop|electropop|synthpop|synth-pop|eurodance|disco|vocal house|gospel|soul|reggaeton|dancehall)\b', re.I)
INSTRUMENTAL = re.compile(r'\b(instrumental|inst\.?|karaoke)\b|インスト|カラオケ', re.I)


def local_lyrics(path):
    for candidate in (path.with_suffix('.lrc'), Path(str(path) + '.lrc')):
        if candidate.is_file():
            content = candidate.read_text(encoding='utf-8-sig')
            if content.strip():
                return content, 'local:lrc'
    audio = mutagen.File(path)
    if audio and audio.tags:
        for key, value in audio.tags.items():
            if str(key).upper().startswith('USLT'):
                content = value.text
            elif str(key).lower() in ('lyrics', 'unsyncedlyrics', '©lyr'):
                content = '\n'.join(value) if isinstance(value, list) else str(value)
            else:
                continue
            if content.strip():
                return content, 'local:metadata'
    return None


async def run(args):
    async with streamable_http_client(args.url) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                if result.is_error:
                    raise RuntimeError(result.content[0].text)
                return json.loads(result.content[0].text)
            # The current search tool includes full lyrics and orders only by created_at.
            # REST allows one consistent result without SSE size limits or tied-date pagination.
            def read_tracks():
                url = args.url.removesuffix('/mcp') + '/api/tracks?limit=100000'
                with urllib.request.urlopen(url, timeout=120) as response:
                    tracks = json.load(response)
                return tracks
            tracks = await asyncio.to_thread(read_tracks)
            if len(tracks) >= 100000 or len({t['id'] for t in tracks}) != len(tracks):
                raise RuntimeError('Track listing is incomplete or contains duplicate IDs')
            for track in tracks:
                track.pop('lyrics', None)
            counts = Counter()
            rows = []
            pending = []
            for track in tracks:
                genre = track['genre'].strip().lower()
                if genre not in VOCAL_GENRES and not VOCAL_SUBGENRE.search(track.get('subgenre') or ''):
                    continue
                counts['vocal_genre_tracks'] += 1
                row = {k: track[k] for k in ('id', 'title', 'artist', 'genre', 'filepath')}
                if INSTRUMENTAL.search(track['title']):
                    row['status'] = 'excluded_instrumental'
                elif track.get('has_lyrics'):
                    row['status'] = 'existing'
                elif not Path(track['filepath']).is_file():
                    row['status'] = 'missing_audio'
                else:
                    try:
                        found = local_lyrics(Path(track['filepath']))
                        if found:
                            content, source = found
                            row.update(status='available', source=source,
                                       content_sha256=hashlib.sha256(content.encode()).hexdigest())
                            pending.append(dict(track_id=track['id'], content=content, source=source))
                        else:
                            row['status'] = 'no_local_lyrics'
                    except Exception as exc:
                        row.update(status='read_error', error=str(exc))
                counts[row['status']] += 1
                rows.append(row)
            report = {'mode': 'apply' if args.apply else 'scan', 'counts': dict(counts),
                      'library_tracks': len(tracks), 'genres': dict(Counter(t['genre'] for t in tracks)), 'tracks': rows, 'registrations': []}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            if args.apply:
                for start in range(0, len(pending), 50):
                    batch = pending[start:start+50]
                    result = await call('register_track_lyrics_batch', {'items': batch})
                    report['registrations'].extend(result['results'])
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    for item, saved in zip(batch, result['results']):
                        if saved['status'] in ('created', 'updated'):
                            actual = await call('get_track_lyrics', {'track_id': item['track_id']})
                            if actual['content'] != item['content'] or actual['source'] != item['source']:
                                raise RuntimeError(f"Verification failed: {item['track_id']}")
                report['verified'] = True
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({'counts': report['counts'], 'registrations': dict(Counter(r['status'] for r in report['registrations'])), 'report': str(args.report)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:48123/mcp')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', required=True, type=Path)
    asyncio.run(run(parser.parse_args()))
