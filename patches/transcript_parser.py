"""Lossless adapter for fully labelled dialogue, not a generative JSON repair."""
import json
import re


def normalize_dialogue_envelope(text, names):
    """Wrap fully labelled transport dialogue without deleting or inventing content."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('TRANSCRIPT_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=unique_pairs)
    if isinstance(value, dict) and set(value) == {'dialogue'}:
        turns = value['dialogue']
    elif isinstance(value, list):
        turns = value
    else:
        raise ValueError('TRANSCRIPT_AMBIGUOUS_ENVELOPE')
    if not isinstance(turns, list) or not turns:
        raise ValueError('TRANSCRIPT_EMPTY')
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != {'speaker', 'dialogue'}:
            raise ValueError('TRANSCRIPT_AMBIGUOUS_TURN')
        if turn['speaker'] not in names or not isinstance(turn['dialogue'], str):
            raise ValueError('TRANSCRIPT_INVALID_TURN')
        dialogue = turn['dialogue'].strip()
        if dialogue.endswith(('...', '…')) or not dialogue.rstrip('"”»').endswith(('.', '?', '!', '。')):
            raise ValueError('TRANSCRIPT_INCOMPLETE_TURN')
    if {turn['speaker'] for turn in turns} != set(names):
        raise ValueError('TRANSCRIPT_MISSING_SPEAKER')
    return json.dumps({'transcript': turns}, ensure_ascii=False)


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
                from langchain_core.messages import BaseMessage
                try:
                    return parser.invoke(value, *args, **kwargs)
                except OutputParserException as original_error:
                    raw = value.content if isinstance(value, BaseMessage) else value
                    if not isinstance(raw, str):
                        raise original_error
                    try:
                        converted = labelled_dialogue_json(raw, names)
                    except ValueError:
                        try:
                            converted = normalize_dialogue_envelope(raw, names)
                        except (ValueError, TypeError):
                            raise original_error
                    return parser.invoke(converted, *args, **kwargs)
        return Adapter()
    return factory
