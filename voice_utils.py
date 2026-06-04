"""
voice_utils.py — Motor de voz NEURONAL para YUE y KAI
Coloca este archivo junto a YUE.PY y KAI.PY (ambos lo importan).

VOCES NATURALES (recomendado):
  Usa **edge-tts**, las voces neuronales de Microsoft. Son gratis,
  NO necesitan API key y suenan mucho más naturales que gTTS.

  YUE → es-ES-ElviraNeural  (femenina, cálida y clara)
  KAI → es-MX-JorgeNeural   (masculina, serena y natural)

  Ya NO se distorsiona el tono con trucos de frame_rate: edge-tts
  permite ajustar rate/pitch/volume de forma nativa sin artefactos.

INSTALAR:
  pip install edge-tts pygame python-dotenv
  (gTTS queda solo como respaldo opcional: pip install gtts)

NOTA: edge-tts y gTTS necesitan conexión a internet en tiempo real
      (igual que la API de Groq que ya usa la app).

Otras voces que puedes probar (cambia VOICE_YUE / VOICE_KAI abajo):
  Femeninas: es-MX-DaliaNeural, es-CO-SalomeNeural, es-ES-XimenaNeural
  Masculinas: es-ES-AlvaroNeural (más grave), es-MX-CarlosNeural,
              es-CO-GonzaloNeural, es-AR-TomasNeural
"""

import threading
import tempfile
import os
import re
import asyncio

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ──────────────────────────────────────────────────────────
#  CONFIGURACIÓN DE VOCES  (cámbialas a tu gusto)
# ──────────────────────────────────────────────────────────
VOICE_YUE = "es-CO-SalomeNeural"   # YUE: femenina, cálida, clara
VOICE_KAI = "es-MX-CarlosNeural"    # KAI: masculina, serena, natural

# Ajustes finos por personaje (edge-tts, sin distorsión):
#   rate   -> velocidad      ("+0%", "-5%", "+10%"...)
#   pitch  -> tono           ("+0Hz", "+8Hz", "-4Hz"...)
#   volume -> volumen        ("+0%", "-10%"...)
YUE_PROSODY = {"rate": "+4%",  "pitch": "+8Hz", "volume": "+0%"}   # dulce y viva
KAI_PROSODY = {"rate": "-3%",  "pitch": "-4Hz", "volume": "+0%"}   # firme y reposado

# ── Reproductor de audio (pygame) ─────────────────────────
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

# ── Motor TTS principal: edge-tts (neuronal) ──────────────
try:
    import edge_tts
    EDGE_OK = True
    print("[voice_utils] ✅ edge-tts (voces neuronales) conectado.")
except Exception:
    EDGE_OK = False
    print("[voice_utils] ⚠️  edge-tts no disponible. Instala con: pip install edge-tts")

# ── Motor de respaldo: gTTS (más robótico) ────────────────
try:
    from gtts import gTTS
    GTTS_OK = True
except Exception:
    GTTS_OK = False

# ── Pitch-shift SOLO para el respaldo gTTS de KAI ─────────
try:
    from pydub import AudioSegment
    PITCH_OK = True
except Exception:
    PITCH_OK = False

if not EDGE_OK and not GTTS_OK:
    print("[voice_utils] ❌ No hay ningún motor TTS. Instala: pip install edge-tts")

# ── Estado global ─────────────────────────────────────────
_voice_enabled = True
_lock = threading.Lock()


def set_voice_enabled(val: bool):
    global _voice_enabled
    _voice_enabled = val


def is_voice_enabled() -> bool:
    return _voice_enabled


def stop_voice():
    """Detiene la reproducción actual."""
    if PYGAME_OK:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass


# ── Normalización de texto ────────────────────────────────
_NAME_FIXES = [
    (re.compile(r'\bYUE\b', re.IGNORECASE), 'Yue'),
    (re.compile(r'\bKAI\b', re.IGNORECASE), 'Kai'),
    (re.compile(r'\bNEXIA\b', re.IGNORECASE), 'Nexia'),
]


def _normalize_names(text: str) -> str:
    for pat, repl in _NAME_FIXES:
        text = pat.sub(repl, text)
    return text


def _clean_text(text: str) -> str:
    """Elimina emojis/símbolos y normaliza los nombres para el TTS."""
    text = re.sub(
        r'[\U00010000-\U0010ffff'
        r'\U0001F600-\U0001F64F'
        r'\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF'
        r'\u2600-\u26FF\u2700-\u27BF]+',
        '', text, flags=re.UNICODE
    )
    text = re.sub(r'[*_~`#►▸●◆✨🌟]+', '', text)
    text = _normalize_names(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Generación con edge-tts (voz neuronal) ────────────────
async def _edge_save(text: str, voice: str, prosody: dict, output_path: str):
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=prosody.get("rate", "+0%"),
        pitch=prosody.get("pitch", "+0Hz"),
        volume=prosody.get("volume", "+0%"),
    )
    await communicate.save(output_path)


def _generate_speech_edge(text: str, voice: str, prosody: dict, output_path: str) -> bool:
    if not EDGE_OK:
        return False
    try:
        asyncio.run(_edge_save(text, voice, prosody, output_path))
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[voice_utils] edge-tts error: {e}")
        return False


# ── Respaldo: gTTS ────────────────────────────────────────
def _generate_speech_gtts(text: str, tld: str, output_path: str) -> bool:
    if not GTTS_OK:
        return False
    try:
        gTTS(text=text, lang='es', tld=tld, slow=False).save(output_path)
        return True
    except Exception as e:
        print(f"[voice_utils] gTTS error: {e}")
        return False


def _pitch_shift(in_path: str, out_path: str, semitones: float) -> bool:
    """Solo para el respaldo gTTS de KAI (necesita pydub + ffmpeg)."""
    if not PITCH_OK:
        return False
    try:
        sound = AudioSegment.from_file(in_path, format="mp3")
        new_rate = int(sound.frame_rate * (2.0 ** (semitones / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={'frame_rate': new_rate})
        shifted = shifted.set_frame_rate(44100)
        shifted.export(out_path, format="mp3")
        return True
    except Exception as e:
        print(f"[voice_utils] pitch shift error: {e}")
        return False


# ── Reproducción ──────────────────────────────────────────
def _play_audio(path: str, volume: float = 1.0):
    if not PYGAME_OK:
        return
    with _lock:
        stop_voice()
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(80)


def _speak_character(text, voice, prosody, vol_level, fallback_tld, fallback_semitones=0.0):
    """Genera (edge-tts → gTTS de respaldo) y reproduce la voz."""
    if not PYGAME_OK:
        print("[voice_utils] pygame no disponible")
        return
    clean = _clean_text(text)
    if not clean:
        return

    base_path = None
    shifted_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            base_path = f.name

        play_path = base_path
        used_edge = _generate_speech_edge(clean, voice, prosody, base_path)

        if not used_edge:
            # Respaldo gTTS (más robótico, pero mantiene la app funcionando)
            if not _generate_speech_gtts(clean, fallback_tld, base_path):
                return
            if fallback_semitones != 0.0 and PITCH_OK:
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                    shifted_path = f.name
                if _pitch_shift(base_path, shifted_path, fallback_semitones):
                    play_path = shifted_path

        _play_audio(play_path, volume=vol_level)
    except Exception as e:
        print(f"[voice_utils error] {e}")
    finally:
        for p in (base_path, shifted_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _speak_yue(text: str):
    """Voz YUE — neuronal femenina, cálida y clara."""
    _speak_character(text, VOICE_YUE, YUE_PROSODY,
                     vol_level=1.0, fallback_tld='es', fallback_semitones=0.0)


def _speak_kai(text: str):
    """Voz KAI — neuronal masculina, serena y natural."""
    _speak_character(text, VOICE_KAI, KAI_PROSODY,
                     vol_level=0.97, fallback_tld='com.mx', fallback_semitones=-3.0)


def speak(text: str, character: str = "yue"):
    """Lanza la voz en un hilo aparte para no bloquear la UI."""
    if not _voice_enabled:
        return
    fn = _speak_yue if character == "yue" else _speak_kai
    threading.Thread(target=fn, args=(text,), daemon=True).start()
