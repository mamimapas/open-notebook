import json
import pytest
from patches.transcript_parser import labelled_dialogue_json, wrap_parser_factory, normalize_dialogue_envelope


def test_exact_dialogue_envelope_is_lossless():
    turns = [{'speaker': 'Daniel', 'dialogue': '¿Qué sabemos?'},
             {'speaker': 'Elena', 'dialogue': 'Solo lo confirmado.'}]
    assert json.loads(normalize_dialogue_envelope(json.dumps({'dialogue': turns}), ['Daniel', 'Elena'])) == {'transcript': turns}


def test_adapter_revalidates_envelope_and_keeps_return_type():
    from langchain_core.exceptions import OutputParserException
    class Parser:
        def invoke(self, value):
            parsed = json.loads(value)
            if 'transcript' not in parsed:
                raise OutputParserException('transcript required')
            return tuple(parsed['transcript'])
    turns = [{'speaker': 'Daniel', 'dialogue': 'Pregunta.'},
             {'speaker': 'Elena', 'dialogue': 'Respuesta.'}]
    parser = wrap_parser_factory(lambda names: Parser())(['Daniel', 'Elena'])
    assert parser.invoke(json.dumps({'dialogue': turns})) == tuple(turns)


@pytest.mark.parametrize('as_message', [False, True])
@pytest.mark.parametrize('as_array', [False, True])
def test_adapter_accepts_complete_transport_dialogue_without_model_retry(as_message, as_array):
    from langchain_core.exceptions import OutputParserException
    from langchain_core.messages import AIMessage

    class Parser:
        def invoke(self, value):
            if isinstance(value, AIMessage):
                value = value.content
            parsed = json.loads(value)
            if not isinstance(parsed, dict) or 'transcript' not in parsed:
                raise OutputParserException('transcript required')
            return tuple(parsed['transcript'])

    turns = [{'speaker': 'Daniel', 'dialogue': '¿Qué sabemos?'},
             {'speaker': 'Elena', 'dialogue': 'Solo lo confirmado.'}]
    payload = turns if as_array else {'dialogue': turns}
    raw = json.dumps(payload)
    parser = wrap_parser_factory(lambda names: Parser())(['Daniel', 'Elena'])
    assert parser.invoke(AIMessage(content=raw) if as_message else raw) == tuple(turns)


def test_duplicate_json_keys_are_not_silently_discarded():
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        normalize_dialogue_envelope('{"dialogue": [], "dialogue": []}', ['Daniel', 'Elena'])


@pytest.mark.parametrize('value', [
    {'dialogue': [], 'extra': 'must not disappear'},
    {'dialogue': []},
    {'dialogue': [{'speaker': 'Daniel', 'dialogue': 'Incomplete'}]},
    {'dialogue': [{'speaker': 'Intruso', 'dialogue': 'Completo.'}]},
])
def test_ambiguous_envelopes_stay_blocked(value):
    with pytest.raises(ValueError):
        normalize_dialogue_envelope(json.dumps(value), ['Daniel', 'Elena'])


@pytest.mark.parametrize('labels', [('{name}:', '{name}:'), ('**{name}:**', '**{name}**:')])
def test_complete_labelled_dialogue_preserved_without_model_call(labels):
    text = labels[0].format(name='Daniel') + ' ¿Qué sabemos?\n\n' + labels[1].format(name='Elena') + ' Solo lo confirmado por las fuentes.'
    value = json.loads(labelled_dialogue_json(text, ['Daniel', 'Elena']))
    assert value == {'transcript': [{'speaker': 'Daniel', 'dialogue': '¿Qué sabemos?'},
                                    {'speaker': 'Elena', 'dialogue': 'Solo lo confirmado por las fuentes.'}]}


@pytest.mark.parametrize('text', [
    'Introducción inventada.\nDaniel: Pregunta.\nElena: Respuesta.',
    'Daniel: Pregunta.\nIntruso: Respuesta.',
    'Daniel: Pregunta.\nElena: Respuesta incompleta',
    'Daniel: Pregunta.\nElena: Respuesta...',
    'Daniel: Solo una voz.',
    '```json\n{"transcript": []}\n```',
])
def test_ambiguous_or_incomplete_text_stays_blocked(text):
    with pytest.raises(ValueError):
        labelled_dialogue_json(text, ['Daniel', 'Elena'])


def test_adapter_uses_original_validator_after_lossless_conversion():
    from langchain_core.exceptions import OutputParserException
    class Parser:
        def invoke(self, value):
            try:
                return json.loads(value)
            except ValueError:
                raise OutputParserException('not json')
    parser = wrap_parser_factory(lambda names: Parser())(['Daniel', 'Elena'])
    assert parser.invoke('Daniel: Pregunta.\nElena: Respuesta.')['transcript'][1]['speaker'] == 'Elena'
    assert parser.invoke('{"transcript": []}') == {'transcript': []}
