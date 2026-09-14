from podcast_creator.nodes import create_validated_transcript_parser
from langchain_core.exceptions import OutputParserException

parser = create_validated_transcript_parser(['Daniel', 'Elena'])
result = parser.invoke('Daniel: Pregunta.\nElena: Respuesta.')
assert len(result.transcript) == 2
assert result.transcript[1].speaker == 'Elena'
assert result.model_dump()['transcript'][0]['dialogue'] == 'Pregunta.'
wrapped = parser.invoke('{"dialogue": [{"speaker": "Daniel", "dialogue": "Pregunta."}, {"speaker": "Elena", "dialogue": "Respuesta."}]}')
assert wrapped.model_dump() == result.model_dump()
try:
    parser.invoke('Preamble\nDaniel: Pregunta.\nElena: Respuesta.')
except OutputParserException:
    print('PASS original Pydantic type and rejection of unlabelled content')
else:
    raise AssertionError('unlabelled accepted')
