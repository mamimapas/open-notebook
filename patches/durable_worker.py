"""Durable polling replacement for the existing surreal-commands worker listener.

No LIVE notification is required for correctness. Claims use conditional database
updates; legacy running records are never automatically replayed or deleted.
"""
import asyncio
import logging
import uuid
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger(__name__)


async def pending(db_factory):
    cursor = None
    while True:
        async with db_factory() as db:
            rows = await db.query(
                "SELECT * FROM command WHERE status = 'new' "
                + ("AND id > $cursor " if cursor is not None else "")
                + "ORDER BY id ASC LIMIT 100", {'cursor': cursor} if cursor else None)
        if not rows:
            return
        for row in rows:
            yield row
        cursor = rows[-1]['id']


def audio_path(result, base=Path('/app/data/podcasts')):
    if not isinstance(result, dict):
        return None
    value = result.get('audio_file_path') or result.get('audio_file') or result.get('audio_path')
    if not isinstance(value, str):
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_relative_to(base.resolve()):
        return None
    return path


def artifact_exists(result):
    path = audio_path(result)
    return bool(path and path.is_file() and path.stat().st_size > 0)


def parser_failure_without_artifact(row):
    """One known pre-audio failure may be retried after a parser deployment."""
    return (
        row.get('status') == 'failed'
        and not row.get('result')
        and str(row.get('error_message') or '').startswith(
            'Failed to parse ValidatedTranscript from completion'
        )
    )


async def process_one(db_factory, service, *, timeout_seconds=3600,
                      verify_artifact=artifact_exists):
    commands = pending(db_factory)
    async for cmd in commands:
        if not isinstance(cmd, dict) or cmd.get('status') != 'new':
            continue
        id = cmd['id']
        if cmd.get('name') == 'generate_podcast':
            async with db_factory() as db:
                duplicates = await db.query(
                    "SELECT id, status, result, error_message FROM command "
                    "WHERE app = $app AND name = $name AND args = $args "
                    "AND (context ?? {}) = $context AND duplicate_of = NONE ORDER BY id ASC",
                    {'app': cmd['app'], 'name': cmd['name'], 'args': cmd['args'],
                     'context': cmd.get('context') or {}},
                )
            others = [r for r in duplicates or [] if str(r['id']) != str(id)]
            terminal = next((r for r in others if r['status'] == 'completed'), None)
            if terminal is None:
                terminal = next((r for r in others if r['status'] == 'failed'
                                 and not parser_failure_without_artifact(r)), None)
            if terminal:
                if terminal['status'] == 'completed' and not verify_artifact(terminal.get('result')):
                    # Preserve both identities for explicit artifact reconciliation.
                    continue
                async with db_factory() as db:
                    await db.query(
                        "UPDATE $id SET status = $status, result = $result, "
                        "error_message = $error, duplicate_of = $original "
                        "WHERE status = 'new' RETURN AFTER",
                        {'id': id, 'status': terminal['status'],
                         'result': terminal.get('result'),
                         'error': terminal.get('error_message') or '',
                         'original': terminal['id']},
                    )
                return 'reconciled'
            if any(r['status'] == 'running' for r in others):
                continue
            if any(r['status'] == 'new' and str(r['id']) < str(id) for r in others):
                continue

        owner = uuid.uuid4().hex
        async with db_factory() as db:
            claimed = await db.query(
                "UPDATE $id SET status = 'running', worker_owner = $owner, "
                "worker_started_at = time::now() WHERE status = 'new' RETURN AFTER",
                {'id': id, 'owner': owner},
            )
        if not claimed:
            continue

        async def fail(code):
            async with db_factory() as db:
                await db.query(
                    "UPDATE $id SET status = $status, error_message = $error "
                    "WHERE status = 'running' AND worker_owner = $owner RETURN AFTER",
                    {'id': id, 'owner': owner, 'status': 'failed', 'error': code},
                )

        original_update = getattr(service, 'update_command_result', None)

        async def guarded_update(command_id, status, result=None, error_message=''):
            async with db_factory() as db:
                updated = await db.query(
                    "UPDATE $id SET status = $status, result = $result, error_message = $error "
                    "WHERE status = 'running' AND worker_owner = $owner RETURN AFTER",
                    {'id': command_id, 'owner': owner, 'status': status,
                     'result': result, 'error': error_message})
            if not updated:
                raise RuntimeError('WORKER_OWNERSHIP_LOST')

        if original_update is not None:
            service.update_command_result = guarded_update
        execution = None
        timed_out = False
        try:
            execution = asyncio.create_task(
                service.execute_command(id, f"{cmd['app']}.{cmd['name']}",
                                        cmd['args'], cmd.get('context'))
            )
            done, _ = await asyncio.wait({execution}, timeout=timeout_seconds)
            if not done:
                timed_out = True
                execution.cancel()
                await fail('WORKER_TIMEOUT_OUTCOME_UNKNOWN')
                return 'unknown'
            await execution
        except asyncio.CancelledError:
            if execution is not None:
                execution.cancel()
            await fail('WORKER_INTERRUPTED_OUTCOME_UNKNOWN')
            raise
        except Exception as exc:
            if timed_out:
                log.error('WORKER_TIMEOUT_OUTCOME_UNKNOWN: terminal write failed (%s)', type(exc).__name__)
                return 'unknown'
            await fail('WORKER_EXCEPTION:' + type(exc).__name__)
            return 'failed'
        finally:
            if original_update is not None and (execution is None or execution.done()):
                service.update_command_result = original_update
        async with db_factory() as db:
            closed = await db.query('SELECT * FROM $id', {'id': id})
        status = closed[0].get('status') if closed else None
        return {'completed': 'executed', 'failed': 'failed', 'canceled': 'canceled'}.get(status, 'unknown')
    return 'idle'


@contextmanager
def exclusive_worker(path='/app/data/sapiens-worker.lock'):
    """Kernel lock on the shared data volume; released on process/container death."""
    import fcntl
    with open(path, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def listen_for_commands(max_tasks):
    with exclusive_worker():
        await consume()


async def consume():
    """Reuse the upstream CLI/process; heavy work is intentionally serial."""
    from surreal_commands.repository import db_connection
    from surreal_commands.core.service import command_service

    while True:
        try:
            outcome = await process_one(db_connection, command_service)
            if outcome == 'unknown':
                log.error('WORKER_OUTCOME_UNKNOWN: reconcile before restarting consumer')
                # Do not start more work while a timed-out thread might still run.
                await asyncio.Future()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Query/claim failure must not execute a command. Fresh connection next tick.
            log.error('Durable worker database failure: %s', type(exc).__name__)
            outcome = 'idle'
        if outcome == 'idle':
            await asyncio.sleep(15)
