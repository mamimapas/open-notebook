"""Explicit one-shot recovery of the three inspected parser failures; never a scheduler."""
import asyncio
import argparse
import hashlib
import json
from datetime import datetime, timezone

TARGETS = {
    'at8e2d2rcwk94epq97km': 'Noticias Reales 13/09/2026 (1/2)',
    'hgz5zntxn8x8m8058g3y': 'Noticias IA 13/09/2026 (1/2)',
    'yk8bhysma83pky7qv7n4': 'Noticias Reales 12/09/2026 (1/2)',
}


def eligible(row, expected):
    return (row.get('status') == 'failed' and not row.get('duplicate_of')
            and not row.get('schema_recovery_attempts')
            and row.get('args', {}).get('episode_name') == expected
            and not row.get('result')
            and str(row.get('error_message') or '').startswith(('Invalid json output:', 'Failed to parse ValidatedTranscript')))


async def main():
    from surrealdb import RecordID
    from surreal_commands.repository import db_connection
    output = []
    async with db_connection() as db:
        for key, expected in TARGETS.items():
            record = RecordID('command', key)
            rows = await db.query('SELECT * FROM $id', {'id': record})
            if len(rows) != 1 or not eligible(rows[0], expected):
                raise RuntimeError('RECOVERY_PRECONDITION_FAILED:' + key)
            row = rows[0]
            receipt = {'at': datetime.now(timezone.utc).isoformat(), 'previous_status': 'failed',
                       'reason': 'verified_parser_contract_fix',
                       'previous_error_sha256': hashlib.sha256(row['error_message'].encode()).hexdigest(),
                       'args_sha256': hashlib.sha256(json.dumps(row['args'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
            updated = await db.query(
                "UPDATE $id SET status = 'new', schema_recovery_attempts = [$receipt], "
                "error_message = '', worker_owner = NONE WHERE status = 'failed' "
                "AND error_message = $error AND args = $args AND schema_recovery_attempts = NONE RETURN AFTER",
                {'id': record, 'receipt': receipt, 'error': row['error_message'], 'args': row['args']})
            if len(updated) != 1:
                raise RuntimeError('RECOVERY_CLAIM_LOST:' + key)
            output.append({'id': str(record), 'status': 'REQUEUED_ORIGINAL', **receipt})
    print(json.dumps(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Requeue only the inspected failures once')
    args = parser.parse_args()
    if args.apply:
        asyncio.run(main())
    else:
        print(json.dumps({'status': 'PLAN_ONLY', 'targets': TARGETS}))
