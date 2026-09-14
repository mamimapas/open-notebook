"""Install reviewed overrides into the pinned upstream image during build."""
from pathlib import Path
import shutil
import surreal_commands.core.worker as worker
import podcast_creator.retry as retry

source = Path(__file__).parent
shutil.copyfile(source / 'podcast_creator_retry.py', Path(retry.__file__))
target = Path(worker.__file__)
shutil.copyfile(source / 'durable_worker.py', target.with_name('sapiens_durable_worker.py'))
binding = '\nfrom .sapiens_durable_worker import listen_for_commands  # sapiens durable queue\n'
content = target.read_text(encoding='utf-8')
if binding not in content:
    target.write_text(content + binding, encoding='utf-8')
