import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from patches.durable_worker import process_one
from patches.durable_worker import audio_path


def test_audio_relative_path_resolves_in_podcast_storage_only(tmp_path):
    assert audio_path({'audio_file_path': 'episodes/id/audio/file.mp3'}, tmp_path) == tmp_path / 'episodes/id/audio/file.mp3'
    assert audio_path({'audio_file_path': '../outside.mp3'}, tmp_path) is None


class Database:
    def __init__(self, rows, *, claim=True):
        self.rows = rows
        self.claim = claim
        self.queries = []

    @asynccontextmanager
    async def connect(self):
        yield self

    async def query(self, sql, params=None):
        self.queries.append((sql, params))
        if sql.startswith('SELECT'):
            if params and 'id' in params:
                return [r.copy() for r in self.rows if r['id'] == params['id']]
            if params and 'args' in params:
                return [r.copy() for r in self.rows if r['args'] == params['args']
                        and r['app'] == params['app'] and r['name'] == params['name']
                        and (r.get('context') or {}) == params['context'] and not r.get('duplicate_of')]
            return sorted([r.copy() for r in self.rows if r['status'] == 'new'
                           and (not params or r['id'] > params['cursor'])], key=lambda r: r['id'])[:100]
        row = next(r for r in self.rows if r['id'] == params['id'])
        if "status = 'running'" in sql and "status = 'new'" in sql:
            if not self.claim or row['status'] != 'new':
                return []
            row['status'] = 'running'
            row['worker_owner'] = params['owner']
            return [row.copy()]
        if params.get('owner') and row.get('worker_owner') != params['owner']:
            return []
        if params.get('owner') and row['status'] != 'running':
            return []
        row['status'] = params['status']
        row['result'] = params.get('result')
        row['error_message'] = params.get('error', '')
        return [row.copy()]


def command(id='command:a', status='new'):
    return dict(id=id, app='open_notebook', name='generate_podcast',
                args={'content': 'Explicación científica', 'episode_name': 'Papers 13'}, status=status)


def run(db, execute, **kw):
    return asyncio.run(process_one(db.connect, SimpleNamespace(execute_command=execute), **kw))


def test_existing_queue_processed_without_live_notification():
    db = Database([command()])
    calls = []
    async def execute(*args):
        calls.append(args)
        db.rows[0]['status'] = 'completed'
    assert run(db, execute) == 'executed'
    assert len(calls) == 1
    assert db.rows[0]['status'] == 'completed'


def test_claim_lost_never_executes():
    db = Database([command()], claim=False)
    async def execute(*args):
        pytest.fail('second worker executed without claim')
    assert run(db, execute) == 'idle'


def test_duplicate_reuses_completed_result_without_generation():
    original = command('command:a', 'completed')
    original['result'] = {'audio_file': '/app/data/original.mp3'}
    db = Database([original, command('command:b')])
    async def execute(*args):
        pytest.fail('duplicate invoked model')
    assert run(db, execute, verify_artifact=lambda result: True) == 'reconciled'
    assert db.rows[1]['result'] == original['result']


def test_known_parser_failure_can_be_retried_after_parser_fix():
    original = command('command:a', 'failed')
    original['error_message'] = 'Failed to parse ValidatedTranscript from completion []'
    db = Database([original, command('command:b')])
    calls = []
    async def execute(id, *args):
        calls.append(id)
        next(r for r in db.rows if r['id'] == id)['status'] = 'completed'
    assert run(db, execute) == 'executed'
    assert calls == ['command:b']
    assert db.rows[0]['status'] == 'failed'


def test_unknown_failed_outcome_is_not_automatically_retried():
    original = command('command:a', 'failed')
    original['error_message'] = 'WORKER_INTERRUPTED_OUTCOME_UNKNOWN'
    db = Database([original, command('command:b')])
    async def execute(*args):
        pytest.fail('uncertain outcome replayed')
    assert run(db, execute) == 'reconciled'
    assert db.rows[1]['status'] == 'failed'


def test_queued_duplicates_only_canonical_executes():
    db = Database([command('command:b'), command('command:a')])
    calls = []
    async def execute(id, *args):
        calls.append(id)
        next(r for r in db.rows if r['id'] == id)['status'] = 'completed'
    assert run(db, execute) == 'executed'
    assert calls == ['command:a']


def test_running_duplicate_not_replayed_or_failed():
    db = Database([command('command:a', 'running'), command('command:b')])
    async def execute(*args):
        pytest.fail('running original replayed')
    assert run(db, execute) == 'idle'
    assert db.rows[1]['status'] == 'new'


def test_parser_error_terminal_and_preserves_payload():
    db = Database([command()])
    async def execute(*args):
        raise ValueError('malformed input with source text that must not be logged')
    assert run(db, execute) == 'failed'
    assert db.rows[0]['status'] == 'failed'
    assert db.rows[0]['error_message'] == 'WORKER_EXCEPTION:ValueError'
    assert db.rows[0]['args']['content'] == 'Explicación científica'


def test_timeout_is_terminal_unknown_outcome():
    db = Database([command()])
    async def execute(*args):
        await asyncio.sleep(10)
    assert run(db, execute, timeout_seconds=0.001) == 'unknown'
    assert db.rows[0]['error_message'] == 'WORKER_TIMEOUT_OUTCOME_UNKNOWN'


def test_cancellation_persists_terminal_before_propagating():
    db = Database([command()])
    async def execute(*args):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run(db, execute)
    assert db.rows[0]['status'] == 'failed'
    assert db.rows[0]['error_message'] == 'WORKER_INTERRUPTED_OUTCOME_UNKNOWN'


def test_blocked_first_page_does_not_starve_next_page():
    rows = [command('command:000', 'running')]
    rows += [command(f'command:{i:03}') for i in range(1, 102)]
    rows[-1]['args'] = {'content': 'Different episode'}
    db = Database(rows)
    async def execute(id, *args):
        next(r for r in rows if r['id'] == id)['status'] = 'completed'
    assert run(db, execute) == 'executed'
    assert rows[-1]['status'] == 'completed'


def test_missing_original_audio_does_not_accredit_duplicate():
    db = Database([command('command:a', 'completed'), command('command:b')])
    async def execute(*args):
        pytest.fail('missing artifact must not generate another episode')
    assert run(db, execute) == 'idle'
    assert db.rows[1]['status'] == 'new'


@pytest.mark.parametrize('context', [None, {}])
def test_missing_and_empty_context_are_same_identity(context):
    current = command('command:b')
    current['context'] = context
    db = Database([command('command:a', 'running'), current])
    async def execute(*args):
        pytest.fail('legacy duplicate was regenerated')
    assert run(db, execute) == 'idle'


def test_distinct_context_is_not_deduplicated():
    current = command('command:b')
    current['context'] = {'tenant': 'different'}
    db = Database([command('command:a', 'running'), current])
    async def execute(*args):
        current['status'] = 'completed'
    assert run(db, execute) == 'executed'


def test_service_absorbed_error_is_read_back_as_failed():
    db = Database([command()])
    async def execute(*args):
        db.rows[0]['status'] = 'failed'
    assert run(db, execute) == 'failed'


def test_explicitly_requeued_original_is_not_blocked_by_its_replica():
    original = command('command:a')
    replica = command('command:b', 'failed')
    replica['duplicate_of'] = original['id']
    db = Database([original, replica])
    async def execute(*args):
        original['status'] = 'completed'
    assert run(db, execute) == 'executed'
    assert replica['status'] == 'failed'


def test_cancel_during_execution_cannot_be_overwritten():
    db = Database([command()])
    async def original_update(*args):
        pytest.fail('unguarded upstream merge')
    service = SimpleNamespace(update_command_result=original_update)
    async def execute(id, *args):
        db.rows[0]['status'] = 'canceled'
        await service.update_command_result(id, 'completed', {'audio_file': 'x'})
    service.execute_command = execute
    assert asyncio.run(process_one(db.connect, service)) == 'failed'
    assert db.rows[0]['status'] == 'canceled'
    assert service.update_command_result is original_update


def test_timeout_persistence_failure_keeps_unknown_with_cancellation_suppressed():
    async def scenario():
        db = Database([command()])
        original_query = db.query
        async def query(sql, params=None):
            if params and params.get('error') == 'WORKER_TIMEOUT_OUTCOME_UNKNOWN':
                raise ConnectionError('temporary database failure')
            return await original_query(sql, params)
        db.query = query
        finish = asyncio.Event()
        finished = asyncio.Event()
        async def execute(*args):
            try:
                await finish.wait()
            except asyncio.CancelledError:
                await finish.wait()
            finally:
                finished.set()
        outcome = await process_one(db.connect, SimpleNamespace(execute_command=execute), timeout_seconds=0.001)
        assert outcome == 'unknown'
        assert db.rows[0]['status'] == 'running'
        assert not finished.is_set()
        finish.set()
        await finished.wait()
    asyncio.run(scenario())
