import os
import sys
import time
import multiprocessing
import numpy as np
import pyaudio
import psutil
import jellyfish
import logging
from scipy.signal import butter, lfilter

# Directiva: Silenciar logs de faster_whisper
logging.getLogger("faster_whisper").setLevel(logging.ERROR)

from faster_whisper import WhisperModel

def set_isolate_affinity():
    try:
        p = psutil.Process(os.getpid())
        cores = list(range(psutil.cpu_count()))
        if len(cores) >= 2:
            p.cpu_affinity(cores[1:])
        
        if sys.platform.startswith('win'):
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            p.nice(-10) 
        print("[Sistema] VoiceEngine Aislado y Limitado a su propio entorno Multi-Núcleo.")
    except Exception as e:
        print(f"[Sistema Error] No se pudo alterar prioridad OS: {e}")

# DSP: Filtro Butterworth High-Pass
def butter_highpass(cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    return b, a

def highpass_filter(data, cutoff=100.0, fs=16000.0, order=5):
    b, a = butter_highpass(cutoff, fs, order=order)
    y = lfilter(b, a, data)
    return y

class VoiceController(multiprocessing.Process):
    def __init__(self, cmd_queue, config):
        super().__init__(daemon=True)
        self.cmd_queue = cmd_queue
        
        audio_cfg = config.get("audio_settings", {})
        ai_cfg = config.get("ai_model", {})
        
        self.MIC_INDEX = audio_cfg.get("microphone_index", 1)
        self.SAMPLE_RATE = audio_cfg.get("sample_rate", 16000)
        self.CHANNELS = audio_cfg.get("channels", 1)
        self.W_MODEL = ai_cfg.get("whisper_model", "tiny")
        self.COMMANDS = config.get("commands", {})
        
        self.CHUNK_SIZE = int(self.SAMPLE_RATE * 0.3) # 300ms
        
        # Directiva Guillotina: Buffer dinámico de máximo 1.2 segundos
        self.MAX_BUFFER_LEN = int(self.SAMPLE_RATE * 1.2)
        
        self.noise_floor = 0.05
        self.alpha_noise = 0.1
        self.is_speaking = False
        self.last_inference_end = 0

        # CRITICO: NO usar lista con comas ni palabras repetidas.
        # El decodificador de Whisper extiende el patron del prompt cuando el audio
        # es ambiguo. 'salta, salte, salta...' en el prompt -> alucinacion 'salta, salta, sal'.
        # Usamos una oracion neutra que da contexto sin crear patrones repetibles.
        self.initial_prompt = "Comando de voz para el juego."

        self.spanish_commands = {}
        self.english_commands = {}
        
        # Palabras que se clasifican como espanol (mayor prioridad de scoring)
        ES_VOCABULARY = {
            # JUMP
            "salta", "saltar", "salte", "brinca", "brincar",
            # RUN
            "corre", "correr", "corra", "avanza", "avanzar", "mueve", "moverse",
            # STOP
            "para", "parar", "frena", "frenar", "detente", "quieto", "espera",
            # ATTACK
            "ataca", "atacar", "ataque", "golpea", "golpear", "pega", "pegar"
        }

        for action, words in self.COMMANDS.items():
            for word in words:
                word_clean = word.lower()
                is_spanish = word_clean in ES_VOCABULARY
                
                norm_w = word_clean.replace('ll', 'y').replace('ce', 'se').replace('ci', 'si').replace('z', 's').replace('q', 'k').replace('h', '')
                nysiis_hash = jellyfish.nysiis(norm_w)
                
                if is_spanish:
                    self.spanish_commands[word_clean] = {"action": action, "hash": nysiis_hash, "norm": norm_w}
                else:
                    self.english_commands[word_clean] = {"action": action, "hash": nysiis_hash, "norm": norm_w}

        # =====================================================================
        # MATRIZ DE CONFUSION — Corpus Espanol de Baja Ganancia
        # Cada lista contiene variantes que Whisper tiny INT8 puede producir
        # cuando el usuario dice ese comando con microfono de baja ganancia.
        # Esta matriz tiene prioridad ABSOLUTA sobre el scorer NYSIIS.
        # Politica: STOP > ATTACK > RUN > JUMP (orden de seguridad)
        # =====================================================================
        self.confusion_matrix = {
            # -----------------------------------------------------------------
            # STOP: maximo de variantes porque 'para' es la mas ambigua
            # -----------------------------------------------------------------
            "stop": [
                # Pronunciacion correcta y conjugaciones
                "para", "pare", "paro", "parar", "frena", "frenar", "alto",
                # Comandos directos en espanol
                "detente", "quieto", "espera", "suficiente", "basta",
                # Distorsiones de microfono de baja ganancia (documentadas en logs)
                "pa", "par",
                "bada", "badaa", "badá", "bad", "bana", "bara",
                "va", "ada", "vamos",
                # Alucinaciones de relleno de Whisper en silencio
                "aha", "ah", "eh", "hm",
                # Anglicismos que el usuario puede usar
                "halt", "stop"
            ],
            # -----------------------------------------------------------------
            # ATTACK: variantes fonéticas de 'ataca'
            # -----------------------------------------------------------------
            "attack": [
                # Pronunciacion correcta y formas verbales
                "ataca", "ataque", "atacar", "ataco", "atacas",
                # Sinonimos en español
                "golpea", "golpe", "golpear", "pega", "pegar",
                "dispara", "disparar", "disparo",
                # Distorsiones documentadas de microfono
                "etaca", "atac", "attaca", "adaca",
                # Frase 'a la' que Whisper produce por el microfono
                "a"
            ],
            # -----------------------------------------------------------------
            # RUN: variantes fonéticas de 'corre'
            # -----------------------------------------------------------------
            "run": [
                # Pronunciacion correcta y conjugaciones
                "corre", "corra", "correr", "corres", "corriendo",
                # Sinonimos en español
                "avanza", "avanzar", "mueve", "moverse",
                "anda", "andar", "ve", "vete",
                # Distorsiones documentadas de microfono
                "coca", "core", "cor", "comer",
                # Anglicismo
                "run"
            ],
            # -----------------------------------------------------------------
            # JUMP: variantes fonéticas de 'salta'
            # -----------------------------------------------------------------
            "jump": [
                # Pronunciacion correcta y conjugaciones
                "salta", "salte", "saltar", "salto", "saltas",
                # Sinonimos en español
                "brinca", "brincar", "brincal", "brinca",
                "sube", "subir", "arriba",
                # Distorsiones documentadas de microfono de baja ganancia
                "sawta", "sauta", "alta", "salt", "salda", "sadda", "sanda",
                # Anglicismo
                "jump"
            ]
        }

    def evaluate_phonetics_nysiis(self, text):
        import re
        words = re.findall(r'\b\w+\b', text.lower())
        if not words: return None, None
            
        best_action, best_match_info = None, None
        highest_score = -1.0
        
        for w in words:
            # Filtro: tokens de menos de 3 letras son ruido parásito de Whisper
            if len(w) < 3:
                continue

            norm_w = w.replace('ll', 'y').replace('ce', 'se').replace('ci', 'si').replace('z', 's').replace('q', 'k').replace('h', '')
            user_hash = jellyfish.nysiis(norm_w)
            
            for base_word, attrs in self.spanish_commands.items():
                target_hash = attrs["hash"]
                sim = jellyfish.jaro_winkler_similarity(user_hash, target_hash)
                
                # Umbral elevado a 0.72 para evitar falsos positivos entre comandos
                if sim >= 0.72:
                    score = sim * 1.3
                    if score > highest_score:
                        highest_score = score
                        best_action = attrs["action"]
                        best_match_info = f"ES-Match: '{w}' ({user_hash}) ≈ '{base_word}' ({target_hash}) | Similitud Métrica: {sim:.2f}"
            
            for base_word, attrs in self.english_commands.items():
                target_hash = attrs["hash"]
                sim = jellyfish.jaro_winkler_similarity(user_hash, target_hash)
                
                if sim >= 0.75:
                    score = sim * 0.8
                    if score > highest_score:
                        highest_score = score
                        best_action = attrs["action"]
                        best_match_info = f"EN-Match: '{w}' ({user_hash}) ≈ '{base_word}' ({target_hash}) | Similitud Métrica: {sim:.2f}"

        if highest_score > 0:
            return best_action, best_match_info
        return None, None

    def run(self):
        set_isolate_affinity()
        
        print(f"[Proceso IA] Iniciando FASTER-WHISPER '{self.W_MODEL}' CPU...")
        self.model = WhisperModel(
            self.W_MODEL, 
            device="cpu", 
            compute_type="int8",
            cpu_threads=4
        )
        print("[Proceso IA] Backend CTranslate2 Cargado (INT8 + 4 Threads). Logs silenciados.")
        
        self.pyaudio_instance = pyaudio.PyAudio()
        self.stream = self.pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=self.CHANNELS,
            rate=self.SAMPLE_RATE,
            input=True,
            input_device_index=self.MIC_INDEX,
            frames_per_buffer=self.CHUNK_SIZE
        )
        
        print("[Micrófono] VAD Estricto | Guillotina 1.2s | Multicommand Regex.")
        
        self.latencies = []
        self.is_flushing = False
        self.audio_buffer = np.array([], dtype=np.float32)
        self.silence_chunks = 0
        self.last_command_time = 0.0  # Timestamp para Debounce Timer
        self.DEBOUNCE_SECONDS = 1.5   # Ventana de silencio post-comando
        
        while True:
            try:
                if getattr(self, "is_flushing", False):
                    if self.stream.get_read_available() > 0:
                        self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)
                    time.sleep(0.01)
                    continue

                # Debounce Timer: descarte silencioso sin bloquear el hilo
                if time.time() - self.last_command_time < self.DEBOUNCE_SECONDS:
                    if self.stream.get_read_available() > 0:
                        self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)
                    self.is_flushing = False  # Desbloqueamos ASAP
                    time.sleep(0.03)
                    continue

                data = self.stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                
                chunk_np = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
                chunk_np = highpass_filter(chunk_np, cutoff=100.0, fs=self.SAMPLE_RATE)
                rms = np.sqrt(np.mean(np.square(chunk_np)))
                
                # Calibración Final del VAD: Multiplicador 1.1x, piso 0.0020 y techo 0.0220
                dynamic_threshold = min(max(0.0020, self.noise_floor * 1.1), 0.0220)

                if rms < dynamic_threshold:
                    # --- RAMA DE SILENCIO ---
                    if rms > dynamic_threshold * 0.5:
                        print(f"  [Mic] Sonido detectado ({rms:.4f}), pero bajo el umbral ({dynamic_threshold:.4f})")
                    self.silence_chunks += 1
                    if rms < self.noise_floor * 2:
                        self.noise_floor = (self.alpha_noise * rms) + ((1 - self.alpha_noise) * self.noise_floor)

                    # END-OF-SPEECH: habia voz y ahora detectamos silencio >= 2 chunks (~200ms)
                    # Disparamos inferencia inmediata con el buffer actual, sin esperar 1.2s
                    if self.is_speaking and self.silence_chunks >= 2 and len(self.audio_buffer) > 0:
                        print(f"  [EOS] Fin de voz. Enviando {len(self.audio_buffer)/self.SAMPLE_RATE:.2f}s a Whisper...")
                        self.is_speaking = False
                        # No hacemos continue: caemos hacia la inferencia abajo
                    else:
                        if self.silence_chunks > 3:
                            self.audio_buffer = np.array([], dtype=np.float32)
                            self.is_speaking  = False
                        time.sleep(0.05)
                        continue
                else:
                    # --- RAMA DE VOZ ACTIVA ---
                    self.silence_chunks = 0
                    self.is_speaking    = True
                    self.audio_buffer   = np.concatenate((self.audio_buffer, chunk_np))
                    # Guillotina 1.2s: seguir acumulando hasta el limite
                    if len(self.audio_buffer) < self.MAX_BUFFER_LEN:
                        continue

                # ─── PUNTO DE INFERENCIA ─── (EOS o Guillotina 1.2s)
                if len(self.audio_buffer) > self.MAX_BUFFER_LEN:
                    window_view = self.audio_buffer[:self.MAX_BUFFER_LEN].copy()
                else:
                    window_view = self.audio_buffer.copy()


                self.audio_buffer = np.array([], dtype=np.float32)
                self.is_speaking  = False

                # Filtro 1: Audio demasiado corto = ruido puro, ignorar
                MIN_AUDIO_SECS = 0.20
                if len(window_view) < int(self.SAMPLE_RATE * MIN_AUDIO_SECS):
                    continue

                # Filtro 2: Energy Gate (ANTES de normalizar).
                # La normalizacion eleva cualquier ruido a amplitud 1.0, engañando a Whisper.
                # Verificamos la energia BRUTA del audio contra el noise_floor actual.
                # Si no supera 3x el piso de ruido, es ambiente y no debe ir a inferencia.
                raw_rms = np.sqrt(np.mean(np.square(window_view)))
                if raw_rms < self.noise_floor * 3.0:
                    continue

                max_amp = np.max(np.abs(window_view))
                if max_amp > 0:
                    window_view /= max_amp

                infer_start = time.time()

                segments, info = self.model.transcribe(
                    window_view,
                    language="es",
                    initial_prompt=self.initial_prompt,
                    vad_filter=False,
                    beam_size=1,
                    without_timestamps=True,
                    max_new_tokens=6,
                    condition_on_previous_text=False,
                    # Umbral interno de Whisper para rechazar segmentos de no-habla.
                    # Si la probabilidad de 'sin-voz' supera 0.45, retorna vacio.
                    no_speech_threshold=0.45
                )

                text_parts = [segment.text for segment in segments]
                text = " ".join(text_parts).strip()

                self.last_inference_end = time.time()
                latency_ms = (self.last_inference_end - infer_start) * 1000

                if text:
                    self.latencies.append(latency_ms)
                    if len(self.latencies) > 10: self.latencies.pop(0)
                    avg_lat = sum(self.latencies) / len(self.latencies)

                    print(f"\n[Whisper EOS ⚡ {latency_ms:.0f}ms] Output: '{text}'")
                    print(f"| Latencia Media (ultimas 10): {avg_lat:.0f}ms |")

                    # Filtro anti-alucinacion: si el output tiene >3 palabras
                    # Y ninguna esta en el corpus de comandos, es ruido de Whisper.
                    # Descartar antes de pagar el costo de procesamiento NYSIIS.
                    ALL_KNOWN = set()
                    for v in self.confusion_matrix.values(): ALL_KNOWN.update(v)
                    words_raw = text.lower().split()
                    if len(words_raw) > 3 and not any(w in ALL_KNOWN for w in words_raw):
                        print(f"  [Filtro] Alucinacion descartada: '{text}'")
                        continue

                    # Extraccion de UNICA palabra valida (primera que coincida)
                    words_detected = text.split()
                    hubo_comando_valido = False

                    for w_token in words_detected:
                        # 1. Prioridad Absoluta: Matriz de Confusion (Hard-mapping)
                        hard_action = None
                        for action_key, confusion_words in self.confusion_matrix.items():
                            if any(cw == w_token for cw in confusion_words):
                                hard_action = action_key
                                break

                        # Caso especial subcadena (e.g. "a la")
                        if not hard_action and "a la" in text.lower():
                            hard_action = "attack"

                        if hard_action:
                            action = hard_action
                            match_info = f"CONFUSION-MATRIX: '{w_token}' forzado a '{action.upper()}'"
                        else:
                            # 2. Filtro Fonetico (NYSIIS) si no hay match directo
                            action, match_info = self.evaluate_phonetics_nysiis(w_token)

                        if action:
                            print(f"[Intention Filter] {match_info}")
                            print(f"[Motor] \u21E8 Enviando UNICO comando: {action.upper()}")

                            while not self.cmd_queue.empty():
                                try: self.cmd_queue.get_nowait()
                                except: pass

                            try:
                                self.cmd_queue.put(action, block=False)
                            except: pass

                            hubo_comando_valido = True
                            break

                    if hubo_comando_valido:
                        self.last_command_time = time.time()
                        self.audio_buffer = np.array([], dtype=np.float32)
                        if self.stream.get_read_available() > 0:
                            self.stream.read(self.stream.get_read_available(), exception_on_overflow=False)
                        self.is_flushing = False
                        print(f"[Sistema] Comando ejecutado. Debounce activo (1.5s)...")

                        
            except Exception as e:
                print(f"[Sistema Crítico] Recuperando stream de audio: {e}")
                try:
                    if hasattr(self, 'stream') and self.stream is not None:
                        self.stream.close()
                    self.stream = self.pyaudio_instance.open(
                        format=pyaudio.paInt16,
                        channels=self.CHANNELS,
                        rate=self.SAMPLE_RATE,
                        input=True,
                        input_device_index=self.MIC_INDEX,
                        frames_per_buffer=self.CHUNK_SIZE
                    )
                    self.is_flushing = False
                except Exception as recovery_error:
                    print(f"[Error Fatal] Imposible restaurar PyAudio: {recovery_error}")
                    time.sleep(0.5)
