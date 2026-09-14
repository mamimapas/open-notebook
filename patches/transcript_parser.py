"""Lossless adapter for fully labelled dialogue, not a generative JSON repair."""
import json
import re


def labelled_dialogue_json(text, names):
    if not isinstance(text, str) or not names:
        raise ValueError('TRANSCRIPT_NOT_LABELLED')
    labels = '|'.join(re.escape(name) for name in names)
    pattern = re.compile(r'^\s*(?:\*\*)?(' + labels + r')(?:\*\*)?\s*:(?:\*\*)?\s*(.+)$')
    turns = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError('TRANSCRIPT_UNRECOGNIZED_LINE')
        dialogue = match.group(2).strip()
        if dialogue.endswith(('...', '…')) or dialogue.rstrip('"”»').endswith(('.', '?', '!', '。')) is False:
            raise ValueError('TRANSCRIPT_INCOMPLETE_TURN')
        turns.append({'speaker': match.group(1), 'dialogue': dialogue})
    if not turns or {turn['speaker'] for turn in turns} != set(names):
        raise ValueError('TRANSCRIPT_MISSING_SPEAKER')
    return json.dumps({'transcript': turns}, ensure_ascii=False)


def wrap_parser_factory(original_factory):
    def factory(names):
        parser = original_factory(names)
        class Adapter:
            def __getattr__(self, name):
                return getattr(parser, name)

            def invoke(self, value, *args, **kwargs):
                from langchain_core.exceptions import OutputParserException
                try:
                    return parser.invoke(value, *args, **kwargs)
                except OutputParserException as original_error:
                    try:
                        converted = labelled_dialogue_json(value, names)
                    except ValueError:
                        raise original_error
                    return parser.invoke(converted, *args, **kwargs)
        return Adapter()
    return factory
