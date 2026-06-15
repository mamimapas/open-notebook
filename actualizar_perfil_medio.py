# -*- coding: utf-8 -*-
"""
actualizar_perfil_medio.py — Reajusta los perfiles sapiens_medio / sapiens_medio_en.
Objetivo (peticion Miguel 2026-06-15): que el MEDIO sea ~la MITAD del denso, no una decima parte.
Antes: 4 segmentos + briefing "no estires" -> ~11 min (denso del mismo articulo: ~66 min).
Ahora: 6 segmentos + briefing "clase condensada, profundidad didactica pero selectiva, ~mitad de
una clase magistral completa" -> objetivo ~30-35 min para ese mismo articulo.
Mantiene speaker_config y modelos por defecto (v4-flash). Borra y recrea (no hay PUT en la API).
"""
import json, subprocess

ON = "http://localhost:5055"
V4FLASH = "model:cv0n80tzyto4hke1z570"  # deepseek-v4-flash (default transformation, mas barato que v4-pro)


def curl(method, path, body=None):
    cmd = ["curl", "-s", "--max-time", "20", "-X", method, f"{ON}{path}",
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_raw": r.stdout[:200]}


BRIEFING_MEDIO_ES = (
"Convierte el material en una CLASE CONDENSADA en audio, conversacion entre Elena (la profesora que domina "
"el tema y lo explica con claridad de docente) y Daniel (el alumno que pregunta justo las dudas de quien escucha "
"por primera vez). Objetivo: que quien estudia conduciendo -sin ver nada- entienda BIEN las ideas centrales y pueda "
"explicarlas con sus palabras. "
"REGLA DE DURACION (clave): este formato es la version MEDIA, apunta a APROXIMADAMENTE LA MITAD de lo que duraria "
"una clase magistral completa sobre el mismo material. Ni un resumen rapido ni una clase exhaustiva: un termino medio "
"con cuerpo. No lo despachen en cuatro frases, pero tampoco agoten cada detalle secundario. "
"SELECCION CON PROFUNDIDAD: identifiquen los conceptos PRINCIPALES y las conclusiones del material y desarrollenlos "
"DE VERDAD -con su intuicion, su porque y un ejemplo o analogia del mundo real-, igual que en una buena clase. Los "
"detalles secundarios, excepciones y matices menores se mencionan de pasada o se agrupan, no se explican uno a uno. "
"La profundidad se reserva para lo que importa. "
"NO DAR POR SABIDO LO ESENCIAL: si un termino tecnico es clave para entender la idea principal, PAREN y definanlo "
"(nombre completo + acronimo + micro-explicacion la primera vez). Si es un tecnicismo accesorio, basta una pincelada. "
"CLARIDAD: traduzcan cualquier formula o simbolo a logica verbal; usen analogias cotidianas (cocina, trafico, agua, "
"oficina) para las ideas dificiles; elijan un hilo conductor y vuelvan a el. "
"ESTILO AUDIO-FIRST: texto hablado natural y fluido, sin listas, vinetas, titulos ni simbolos. Elena y Daniel se "
"interrumpen y repreguntan con naturalidad, con conectores hablados ('imagina que...', 'pasemos a...'). "
"SIN PRESENTACIONES ni 'bienvenidos': entren directos en materia como si la clase ya estuviera en marcha. Cierre "
"breve y natural cuando lo importante quede claro. Tono ameno y didactico: ensenar lo esencial a fondo, condensando "
"lo accesorio."
)

BRIEFING_MEDIO_EN = (
"Turn the material into a CONDENSED CLASS in audio, a conversation between Elena (the teacher who masters the topic "
"and explains it with a teacher's clarity) and Daniel (the learner who asks exactly the doubts of a first-time listener). "
"Goal: someone studying while driving -seeing nothing- understands the CENTRAL ideas well and can explain them in their "
"own words. "
"DURATION RULE (key): this is the MEDIUM version, aim for ABOUT HALF the length a full masterclass on the same material "
"would take. Neither a quick summary nor an exhaustive class: a substantial middle ground. Don't dispatch it in four "
"sentences, but don't exhaust every secondary detail either. "
"DEPTH WITH SELECTION: identify the MAIN concepts and conclusions and develop them PROPERLY -intuition, the why, and a "
"real-world example or analogy-, just like a good class. Secondary details, exceptions and minor nuances are mentioned "
"in passing or grouped, not explained one by one. Depth is reserved for what matters. "
"DON'T ASSUME THE ESSENTIALS: if a technical term is key to the main idea, STOP and define it (full name + acronym + "
"micro-explanation the first time). If it's an accessory technicality, a brushstroke is enough. "
"CLARITY: translate any formula or symbol into verbal logic; use everyday analogies (cooking, traffic, water, office) "
"for hard ideas; pick a through-line and return to it. "
"AUDIO-FIRST STYLE: natural flowing spoken text, no lists, bullets, headings or symbols. Elena and Daniel interrupt and "
"re-ask naturally, with spoken connectors. "
"NO INTROS or 'welcome': go straight into the subject as if the class were already underway. Brief, natural close once "
"the important things are clear. Warm, didactic tone: teach the essentials in depth, condensing the accessory."
)

PROFILES = [
    {"name": "sapiens_medio", "old_id": "episode_profile:jezvw2llj3xo4kr4c7sd",
     "description": "Clase condensada ES: ~mitad del denso. Conceptos principales a fondo, secundarios de pasada. Articulos/noticias/papers/semanal.",
     "speaker_config": "sapiens_dueto", "language": "es", "briefing": BRIEFING_MEDIO_ES},
    {"name": "sapiens_medio_en", "old_id": "episode_profile:5qya06su55gf1digis13",
     "description": "Condensed class EN: ~half the dense one. Main concepts in depth, secondary in passing. Articles/news/papers/weekly.",
     "speaker_config": "sapiens_dueto_en", "language": "en", "briefing": BRIEFING_MEDIO_EN},
]

NUM_SEGMENTS = 8  # 6 seg -> 23min para el RSI; 8 apunta a ~30-33min (~mitad del denso de 66min)

def current_id(name):
    """Busca el id actual del perfil por nombre (la API no tiene PUT; hay que borrar por id real)."""
    allp = curl("GET", "/api/episode-profiles")
    if isinstance(allp, list):
        for pr in allp:
            if pr.get("name") == name:
                return pr.get("id")
    return None


for p in PROFILES:
    # borrar el existente buscando su id ACTUAL (no el hardcoded, que pudo cambiar)
    cid = current_id(p["name"])
    if cid:
        curl("DELETE", f"/api/episode-profiles/{cid}")
        print(f"borrado {p['name']}: {cid}")
    res = curl("POST", "/api/episode-profiles", {
        "name": p["name"],
        "description": p["description"],
        "speaker_config": p["speaker_config"],
        "outline_llm": V4FLASH, "transcript_llm": V4FLASH,
        "language": p["language"],
        "num_segments": NUM_SEGMENTS,
        "default_briefing": p["briefing"],
    })
    print(f"{p['name']}: id={res.get('id')} segments={res.get('num_segments')} briefing_len={len(p['briefing'])}")
