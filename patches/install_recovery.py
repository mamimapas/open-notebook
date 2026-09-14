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

import podcast_creator.nodes as nodes
nodes_path = Path(nodes.__file__)
shutil.copyfile(source / 'transcript_parser.py', nodes_path.with_name('sapiens_transcript_parser.py'))
parser_binding = ('\nfrom .sapiens_transcript_parser import wrap_parser_factory\n'
                  'create_validated_transcript_parser = wrap_parser_factory(create_validated_transcript_parser)\n')
nodes_content = nodes_path.read_text(encoding='utf-8')
if parser_binding not in nodes_content:
    nodes_path.write_text(nodes_content + parser_binding, encoding='utf-8')
prompt_path = Path('/app/prompts/podcast/transcript.jinja')
strict_suffix = ('\nTRANSPORT CONTRACT: Return exactly one valid JSON object with a transcript array. '
                 'Each entry has speaker and dialogue strings. No Markdown, speaker-labelled prose, '
                 'reasoning, preamble or text outside JSON. Use only the configured speaker names.\n')
prompt = prompt_path.read_text(encoding='utf-8')
if strict_suffix not in prompt:
    prompt_path.write_text(prompt + strict_suffix, encoding='utf-8')
