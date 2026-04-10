# Proyecto Inteligencia

Este repositorio contiene la configuración y scripts para el proyecto de inteligencia artificial, utilizando **Python 3.10** para asegurar la compatibilidad con las librerías de audio y reconocimiento de voz.

## Requisitos Instalados

Se han instalado las siguientes librerías clave:
- **Pygame**: Para manejo de gráficos y sonido.
- **PyAudio**: Para captura de audio en tiempo real.
- **OpenAI-Whisper**: Para transcripción de voz a texto (STT).
- **PyTorch**: Motor de inteligencia artificial (dependencia de Whisper).

## Cómo ejecutar el proyecto

Para asegurar que se utilicen las librerías instaladas, siempre debes ejecutar tus scripts con el lanzador de Python especificando la versión **3.10**:

```powershell
py -3.10 nombre_de_tu_script.py
```

## Verificación de la instalación

Puedes verificar que todo esté correctamente configurado ejecutando el script de prueba:

```powershell
py -3.10 test_instalacion.py
```

## Notas Adicionales
- **FFmpeg**: OpenAI-Whisper requiere que FFmpeg esté instalado en el sistema para procesar archivos de audio. Si encuentras errores de "ffmpeg not found", asegúrate de tenerlo instalado y en tu PATH.
- **Versión de Python**: Evite usar Python 3.14 para este proyecto, ya que muchas dependencias aún no son compatibles.
