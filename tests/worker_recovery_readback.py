"""Read-only, content-free queue/artifact evidence for the recovery deployment."""
import asyncio
import json
from pathlib import Path
from surreal_commands.repository import db_connection


async def main():
    async with db_connection() as db:
        rows = await db.query("SELECT id,status,args.episode_name AS episode,worker_owner,"
                              "result.audio_file_path AS audio,error_message FROM command "
                              "WHERE status IN ['new','running'] OR worker_owner != NONE")
    output = []
    for row in rows:
        audio = row.get('audio')
        path = Path(audio) if isinstance(audio, str) else None
        output.append({'id': str(row['id']), 'status': row.get('status'),
                       'episode': row.get('episode'), 'owner': row.get('worker_owner'),
                       'audio_exists': bool(path and path.is_file()),
                       'audio_bytes': path.stat().st_size if path and path.is_file() else 0,
                       'error': (row.get('error_message') or '')[:150]})
    print(json.dumps(output, ensure_ascii=False))


asyncio.run(main())
