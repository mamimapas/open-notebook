import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('parser_recovery', Path(__file__).with_name('requeue_verified_parser_failures.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_requeue_only_known_parser_failure_once_without_audio():
    row = {'status': 'failed', 'args': {'episode_name': 'expected'},
           'error_message': 'Invalid json output: malformed'}
    assert module.eligible(row, 'expected')
    for change in ({'status': 'running'}, {'status': 'completed'}, {'duplicate_of': 'other'},
                   {'schema_recovery_attempts': [{}]}, {'result': {'audio_file_path': 'audio.mp3'}},
                   {'error_message': 'HTTP timeout: unknown outcome'}):
        assert not module.eligible({**row, **change}, 'expected')
    assert not module.eligible(row, 'different identity')
