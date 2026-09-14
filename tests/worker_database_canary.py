"""Opt-in SQL canary; only writes its own randomly identified test record."""
import asyncio
import json
import uuid

from surreal_commands.repository import db_connection
from surrealdb import RecordID


async def main():
    record = RecordID('sapiens_worker_canary', uuid.uuid4().hex)
    async with db_connection() as db:
        try:
            created = await db.query('CREATE ONLY $id SET status = \'new\'', {'id': record})
            assert created, 'create failed'
            params = {'id': record, 'owner': 'canary-owner'}
            sql = ("UPDATE $id SET status = 'running', worker_owner = $owner, "
                   "worker_started_at = time::now() WHERE status = 'new' RETURN AFTER")
            first = await db.query(sql, params)
            second = await db.query(sql, params)
            assert len(first) == 1 and first[0]['worker_owner'] == 'canary-owner'
            assert not second, 'conditional claim did not exclude second owner'
            guarded = ("UPDATE $id SET status = 'completed' WHERE status = 'running' "
                       "AND worker_owner = $owner RETURN AFTER")
            assert not await db.query(guarded, {'id': record, 'owner': 'foreign'})
            await db.query("UPDATE $id SET status = 'canceled'", {'id': record})
            assert not await db.query(guarded, params), 'cancel overwritten'
            duplicate_rejected = False
            try:
                duplicate = await db.query("CREATE ONLY $id SET status = 'new'", {'id': record})
                duplicate_rejected = not isinstance(duplicate, (dict, list)) or not duplicate
            except Exception:
                duplicate_rejected = True
            assert duplicate_rejected, 'CREATE ONLY overwrote existing lock'
            normalized = await db.query('RETURN [(NONE ?? {}) = {}, (NULL ?? {}) = {}, ({} ?? {}) = {}]')
            assert normalized == [True, True, True], normalized
            examples = await db.query("SELECT result FROM command WHERE status = 'completed' "
                                      "AND name = 'generate_podcast' LIMIT 1")
            result = examples[0].get('result', {}) if examples else {}
            print(json.dumps({'status': 'PASS', 'claim': True, 'owner_guard': True,
                              'cancel_guard': True, 'unique_create': True,
                              'podcast_result_keys': list(result) if isinstance(result, dict) else []}))
        finally:
            await db.query('DELETE $id', {'id': record})
            assert not await db.query('SELECT * FROM $id', {'id': record})


asyncio.run(main())
