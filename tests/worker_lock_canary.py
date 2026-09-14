"""Linux subprocess test of the exact consumer lock, without consuming jobs."""
import subprocess
import sys
import tempfile
from pathlib import Path
from surreal_commands.core.sapiens_durable_worker import exclusive_worker

with tempfile.TemporaryDirectory() as directory:
    path = str(Path(directory) / 'lock')
    code = ('from surreal_commands.core.sapiens_durable_worker import exclusive_worker; '
            'import sys; exec("with exclusive_worker(sys.argv[1]):\\n print(\'ACQUIRED\')")')
    with exclusive_worker(path):
        blocked = subprocess.run([sys.executable, '-c', code, path], capture_output=True, text=True)
        assert blocked.returncode != 0 and 'BlockingIOError' in blocked.stderr, blocked.stderr
    released = subprocess.run([sys.executable, '-c', code, path], capture_output=True, text=True)
    assert released.returncode == 0 and 'ACQUIRED' in released.stdout, released.stderr
print('PASS: concurrent consumer excluded; lock released after owner exits')
