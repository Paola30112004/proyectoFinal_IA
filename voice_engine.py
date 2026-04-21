import sys
import os
import json
import queue
import sounddevice as sd
import multiprocessing
from vosk import Model, KaldiRecognizer

class VoiceController:
    def __init__(self, cmd_queue, settings):
        # [PROCESO PADRE]
        # 1. Almacenar SOLO primitivas serializables.
        self.cmd_queue = cmd_queue  # multiprocessing.Queue es seguro para IPC
        self.model_path = "model"
        
        # El JSON debe ser estrictamente válido para que el C++ Backend de KALDI no crashee
        self.grammar = '["jump", "salta", "run", "corre", "stop", "para", "attack", "ataca", "[unk]"]'

    def audio_callback(self, indata, frames, time, status):
        # [PROCESO HIJO] (Invocado como interrupción de hardware)
        if status: pass
        self.audio_queue.put(bytes(indata))

    def start(self):
        # [PROCESO PADRE]
        self.process = multiprocessing.Process(target=self.run, daemon=True)
        self.process.start()

    def terminate(self):
        # [PROCESO PADRE]
        if hasattr(self, 'process') and self.process.is_alive():
            self.process.terminate()

    def run(self):
        # ========================================================
        # [PROCESO HIJO AL DELEGAR START] - NUEVO ESPACIO DE MEMORIA
        # ========================================================
        import queue
        import sys
        import os
        import json
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer
        
        # Escalar la prioridad del hilo en el SO (Vital para i5-7200U)
        import psutil
        try:
            psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
        except Exception:
            pass

        print("[Motor de Voz] Vosk KWS Iniciado. Streaming a 16kHz...")
        
        # 1. Instanciar memoria de hardware y colas thread-safe (Local al hijo)
        self.audio_queue = queue.Queue() 
        
        if not os.path.exists(self.model_path):
            print(f"[Motor de Voz] ERROR FATAL: No se encuentra el modelo en '{self.model_path}'.")
            sys.exit(1)
            
        # 2. Instanciar CFFI Pointers (Vosk) dentro del proceso seguro
        self.model = Model(self.model_path)
        self.recognizer = KaldiRecognizer(self.model, 16000, self.grammar)
        
        # 3. Arrancar Contexto del Micrófono sin fuga de memoria IPC
        # 3. Arrancar Contexto del Micrófono (blocksize reducido a 100ms)
        with sd.RawInputStream(samplerate=16000, blocksize=1600, dtype='int16',
                               channels=1, callback=self.audio_callback):
            while True:
                # Lazo de consumo
                data = self.audio_queue.get() 
                
                # Alimentamos el motor acústico
                is_final = self.recognizer.AcceptWaveform(data)
                
                # Extracción Crítica: Evaluamos el buffer temporal antes del silencio
                partial_str = self.recognizer.PartialResult()
                
                detected_cmd = None
                
                # Búsqueda substring O(N) ultra-rápida (Evita json.loads)
                if "jump" in partial_str or "salta" in partial_str:
                    detected_cmd = "jump"
                elif "run" in partial_str or "corre" in partial_str:
                    detected_cmd = "run"
                elif "stop" in partial_str or "para" in partial_str:
                    detected_cmd = "stop"
                elif "attack" in partial_str or "ataca" in partial_str:
                    detected_cmd = "attack"
                
                # Fallback de seguridad si el fonema pasó a 'final' antes del partial
                if not detected_cmd and is_final:
                    final_str = self.recognizer.Result()
                    for cmd in ["jump", "salta", "run", "corre", "stop", "para", "attack", "ataca"]:
                        if cmd in final_str:
                            detected_cmd = cmd
                            break

                if detected_cmd:
                    try:
                        # 1. Enviar el comando inmediatamente a Pygame
                        self.cmd_queue.put_nowait(detected_cmd)  
                        
                        # 2. GUILLOTINA ACÚSTICA: Resetear el estado de Vosk.
                        # Destruye el buffer acústico actual para no procesar el eco 
                        # o la cola fonética de la palabra que acabas de decir.
                        self.recognizer.Reset()
                        
                        # 3. Vaciado rápido de la cola de hardware pendiente
                        while not self.audio_queue.empty():
                            self.audio_queue.get_nowait()
                            
                    except queue.Full:
                        pass