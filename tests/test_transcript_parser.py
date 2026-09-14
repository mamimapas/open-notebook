import json
import pytest
from patches.transcript_parser import labelled_dialogue_json, wrap_parser_factory


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
