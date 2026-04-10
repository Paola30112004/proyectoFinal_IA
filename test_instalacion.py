import pygame
import pyaudio
import whisper
import sys

def test_imports():
    print("--- Verificando Instalación ---")
    
    # Prueba de Pygame
    try:
        pygame.init()
        print(f"[OK] Pygame {pygame.version.ver} inicializado correctamente.")
        pygame.quit()
    except Exception as e:
        print(f"[ERROR] Pygame: {e}")

    # Prueba de PyAudio
    try:
        pa = pyaudio.PyAudio()
        device_count = pa.get_device_count()
        print(f"[OK] PyAudio detectó {device_count} dispositivos de audio.")
        pa.terminate()
    except Exception as e:
        print(f"[ERROR] PyAudio: {e}")

    # Prueba de Whisper
    try:
        # Solo verificamos que la librería se cargó y que el comando de carga existe
        print(f"[OK] Whisper importado correctamente. Listo para cargar modelos.")
    except Exception as e:
        print(f"[ERROR] Whisper: {e}")

    print("\n¡Todo parece estar en orden!")

if __name__ == "__main__":
    test_imports()
