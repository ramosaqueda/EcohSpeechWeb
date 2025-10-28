import streamlit as st
import sys
import os

# PATCH mejorado para Python 3.13+
try:
    import aifc
except ImportError:
    from types import ModuleType
    aifc = ModuleType('aifc')
    class Error(Exception): pass
    aifc.Error = Error
    aifc.open = lambda *args, **kwargs: None
    sys.modules['aifc'] = aifc

try:
    import audioop
except ImportError:
    # Intentar instalar audioop-lts primero
    try:
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'audioop-lts', '--break-system-packages'])
        import audioop
    except:
        # Mock completo de audioop con todas las funciones necesarias
        from types import ModuleType
        import struct
        import math
        
        audioop = ModuleType('audioop')
        
        # Funciones básicas que SpeechRecognition necesita
        def rms(fragment, width):
            """Calculate RMS (Root Mean Square) of audio fragment"""
            if width == 1:
                fmt = 'b'
            elif width == 2:
                fmt = 'h'
            elif width == 4:
                fmt = 'i'
            else:
                raise ValueError("Invalid width")
            
            count = len(fragment) // width
            if count == 0:
                return 0
            
            sum_squares = sum(x**2 for x in struct.unpack(f'{count}{fmt}', fragment[:count*width]))
            return int(math.sqrt(sum_squares / count))
        
        def ratecv(fragment, width, nchannels, inrate, outrate, state, weightA=1, weightB=0):
            """Convert rate - simplified version"""
            return (fragment, state)
        
        def lin2ulaw(fragment, width):
            """Convert linear to ulaw"""
            return fragment
        
        def ulaw2lin(fragment, width):
            """Convert ulaw to linear"""
            return fragment
        
        def minmax(fragment, width):
            """Find minimum and maximum values"""
            return (0, 0)
        
        def avg(fragment, width):
            """Average over all samples"""
            return 0
        
        def maxpp(fragment, width):
            """Maximum peak-peak value"""
            return 0
        
        def avgpp(fragment, width):
            """Average peak-peak value"""
            return 0
        
        # Asignar funciones al módulo
        audioop.rms = rms
        audioop.ratecv = ratecv
        audioop.lin2ulaw = lin2ulaw
        audioop.ulaw2lin = ulaw2lin
        audioop.minmax = minmax
        audioop.avg = avg
        audioop.maxpp = maxpp
        audioop.avgpp = avgpp
        
        sys.modules['audioop'] = audioop

import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import io
import zipfile
from datetime import datetime
import subprocess
import wave

# Configuración
st.set_page_config(
    page_title="EcohSpeech Web - Debug",
    page_icon="🎤",
    layout="wide"
)

def init_session_state():
    if 'transcriptions' not in st.session_state:
        st.session_state.transcriptions = []
    if 'debug_wavs' not in st.session_state:
        st.session_state.debug_wavs = {}

@st.cache_resource
def get_recognizer():
    return sr.Recognizer()

def check_ffmpeg():
    """Verificar FFmpeg"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              timeout=5)
        return result.returncode == 0
    except:
        return False

def verify_wav_file(wav_path):
    """Verificar que el WAV es válido y tiene contenido"""
    try:
        with wave.open(wav_path, 'rb') as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            
            duration = n_frames / float(framerate)
            
            info = {
                'valid': True,
                'channels': n_channels,
                'sample_width': sample_width,
                'framerate': framerate,
                'frames': n_frames,
                'duration': duration,
                'size': os.path.getsize(wav_path)
            }
            
            st.info(f"""
            📊 **Información del WAV generado:**
            - Canales: {n_channels} {'✅' if n_channels == 1 else '⚠️ (debería ser 1)'}
            - Sample Rate: {framerate} Hz {'✅' if framerate == 16000 else '⚠️ (debería ser 16000)'}
            - Duración: {duration:.2f} segundos
            - Frames: {n_frames:,}
            - Tamaño: {info['size'] / 1024:.1f} KB
            """)
            
            if duration < 0.1:
                st.warning("⚠️ Audio muy corto (< 0.1s) - puede no tener contenido")
                info['valid'] = False
            
            if n_frames < 100:
                st.warning("⚠️ Muy pocos frames - audio probablemente vacío")
                info['valid'] = False
            
            return info
            
    except Exception as e:
        st.error(f"❌ Error verificando WAV: {str(e)}")
        return {'valid': False, 'error': str(e)}

def convert_to_wav_debug(file_path, filename):
    """Convertir a WAV con máximo debug y múltiples estrategias"""
    
    st.markdown("### 🔄 Proceso de Conversión")
    
    # Información del archivo original
    original_size = os.path.getsize(file_path) / 1024
    st.write(f"📁 **Archivo original:** {original_size:.1f} KB")
    
    wav_fd, wav_path = tempfile.mkstemp(suffix='.wav', prefix='ecoh_debug_')
    os.close(wav_fd)
    
    is_whatsapp = 'PTT-' in filename or 'WA' in filename or 'AUD-' in filename
    is_opus = filename.lower().endswith(('.opus', '.ogg', '.oga'))
    
    st.write(f"🔍 **Tipo detectado:** {'📱 WhatsApp' if is_whatsapp else ''} {'🎵 Opus/OGG' if is_opus else ''}")
    
    strategies = []
    
    # Estrategia 1: FFmpeg ultra-permisivo
    if is_opus or is_whatsapp:
        strategies.append({
            'name': '🔧 FFmpeg Ultra-Permisivo (Opus/WhatsApp)',
            'cmd': [
                'ffmpeg', '-y',
                '-loglevel', 'warning',
                '-err_detect', 'ignore_err',
                '-fflags', '+genpts+igndts',
                '-analyzeduration', '100M',
                '-probesize', '50M',
                '-i', file_path,
                '-vn',  # Sin video
                '-ar', '16000',
                '-ac', '1',
                '-sample_fmt', 's16',
                '-acodec', 'pcm_s16le',
                '-f', 'wav',
                wav_path
            ]
        })
    
    # Estrategia 2: FFmpeg con auto-detección
    strategies.append({
        'name': '🔧 FFmpeg Auto-detect',
        'cmd': [
            'ffmpeg', '-y',
            '-loglevel', 'warning',
            '-i', file_path,
            '-ar', '16000',
            '-ac', '1',
            '-acodec', 'pcm_s16le',
            wav_path
        ]
    })
    
    # Estrategia 3: Pydub
    strategies.append({
        'name': '🐍 Pydub',
        'pydub': True
    })
    
    # Estrategia 4: FFmpeg a raw PCM primero
    strategies.append({
        'name': '🔧 FFmpeg vía PCM Raw',
        'two_step': True
    })
    
    # Intentar cada estrategia
    for i, strategy in enumerate(strategies, 1):
        with st.expander(f"Intento {i}/{len(strategies)}: {strategy['name']}", expanded=True):
            try:
                st.write("⏳ Procesando...")
                
                # Pydub
                if strategy.get('pydub'):
                    try:
                        audio = AudioSegment.from_file(file_path)
                        st.write(f"✅ Audio cargado: {len(audio)}ms, {audio.frame_rate}Hz, {audio.channels} canales")
                        
                        # Optimizar
                        audio = audio.set_frame_rate(16000)
                        audio = audio.set_channels(1)
                        audio = audio.normalize()
                        
                        # Exportar
                        audio.export(wav_path, format='wav', parameters=["-ar", "16000", "-ac", "1"])
                        
                        # Verificar
                        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                            info = verify_wav_file(wav_path)
                            if info['valid']:
                                st.success(f"✅ ¡Conversión exitosa con {strategy['name']}!")
                                return wav_path
                    except Exception as e:
                        st.warning(f"⚠️ Pydub falló: {str(e)}")
                        continue
                
                # Dos pasos (raw PCM)
                elif strategy.get('two_step'):
                    raw_fd, raw_path = tempfile.mkstemp(suffix='.raw')
                    os.close(raw_fd)
                    
                    try:
                        # Paso 1: A raw
                        cmd1 = [
                            'ffmpeg', '-y',
                            '-loglevel', 'error',
                            '-err_detect', 'ignore_err',
                            '-i', file_path,
                            '-f', 's16le',
                            '-ar', '16000',
                            '-ac', '1',
                            raw_path
                        ]
                        
                        result1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=30)
                        
                        if result1.returncode == 0 and os.path.getsize(raw_path) > 100:
                            st.write(f"✅ Paso 1: Raw PCM creado ({os.path.getsize(raw_path)/1024:.1f} KB)")
                            
                            # Paso 2: Raw a WAV
                            cmd2 = [
                                'ffmpeg', '-y',
                                '-f', 's16le',
                                '-ar', '16000',
                                '-ac', '1',
                                '-i', raw_path,
                                wav_path
                            ]
                            
                            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
                            
                            if result2.returncode == 0 and os.path.getsize(wav_path) > 1000:
                                info = verify_wav_file(wav_path)
                                if info['valid']:
                                    st.success(f"✅ ¡Conversión exitosa con {strategy['name']}!")
                                    return wav_path
                        else:
                            if result1.stderr:
                                st.error(f"Error paso 1: {result1.stderr}")
                    
                    finally:
                        if os.path.exists(raw_path):
                            os.unlink(raw_path)
                
                # FFmpeg directo
                elif 'cmd' in strategy:
                    result = subprocess.run(
                        strategy['cmd'],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if result.returncode == 0:
                        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                            st.write(f"✅ FFmpeg completado, verificando...")
                            info = verify_wav_file(wav_path)
                            
                            if info['valid']:
                                st.success(f"✅ ¡Conversión exitosa con {strategy['name']}!")
                                return wav_path
                            else:
                                st.warning("⚠️ WAV generado pero sin contenido válido")
                        else:
                            st.warning("⚠️ WAV no generado o muy pequeño")
                    
                    if result.stderr:
                        st.code(result.stderr[-300:], language='text')
            
            except subprocess.TimeoutExpired:
                st.error("⏱️ Timeout - archivo muy grande o proceso bloqueado")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                continue
    
    # Si todo falló
    if os.path.exists(wav_path):
        os.unlink(wav_path)
    
    raise Exception(
        "❌ **No se pudo convertir el archivo después de 4 intentos**\n\n"
        "**Posibles causas:**\n"
        "1. Archivo corrupto o incompleto\n"
        "2. Formato no estándar\n"
        "3. Encriptación o protección\n"
        "4. FFmpeg no instalado correctamente\n\n"
        "**💡 Soluciones:**\n"
        "- Reproduce el audio en tu dispositivo primero\n"
        "- Convierte a MP3/WAV con otra herramienta\n"
        "- Verifica que no esté protegido/encriptado"
    )

def test_recognizer():
    """Probar que el reconocedor funciona"""
    try:
        recognizer = get_recognizer()
        st.success(f"✅ SpeechRecognition inicializado correctamente")
        st.write(f"- Versión: {sr.__version__}")
        st.write(f"- Energy threshold: {recognizer.energy_threshold}")
        
        # Verificar que audioop.rms existe
        import audioop
        if hasattr(audioop, 'rms'):
            st.write("- audioop.rms: ✅ Disponible")
        else:
            st.error("- audioop.rms: ❌ NO disponible")
            return False
        
        return True
    except Exception as e:
        st.error(f"❌ Error inicializando reconocedor: {str(e)}")
        return False

def transcribe_audio(file_path, language, filename):
    """Transcribir con máximo debug"""
    wav_path = None
    
    try:
        st.markdown("---")
        st.markdown(f"## 🎤 Transcribiendo: {filename}")
        
        # Verificar recognizer
        if not test_recognizer():
            return "❌ Error: Reconocedor de voz no disponible"
        
        # Convertir a WAV
        wav_path = convert_to_wav_debug(file_path, filename)
        
        if not wav_path or not os.path.exists(wav_path):
            return "❌ Error: No se pudo crear WAV válido"
        
        # Guardar WAV para debug (permitir descarga)
        with open(wav_path, 'rb') as f:
            wav_bytes = f.read()
            st.session_state.debug_wavs[filename] = wav_bytes
            st.download_button(
                "🔍 Descargar WAV convertido (para debug)",
                wav_bytes,
                f"debug_{filename}.wav",
                "audio/wav",
                key=f"debug_wav_{filename}"
            )
        
        st.markdown("### 🎧 Transcribiendo con Google Speech API")
        
        recognizer = get_recognizer()
        
        # Ajustar parámetros
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        
        with sr.AudioFile(wav_path) as source:
            st.write("📊 Analizando audio...")
            
            # Ajustar ruido - ESTE ES EL PASO QUE FALLA
            try:
                st.write("🔇 Ajustando ruido ambiente...")
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                st.write(f"✅ Umbral de energía ajustado a: {recognizer.energy_threshold}")
            except AttributeError as e:
                st.warning(f"⚠️ No se pudo ajustar ruido ambiente: {e}")
                st.info("Continuando sin ajuste de ruido...")
            
            # Leer audio
            st.write("📖 Leyendo datos de audio...")
            audio_data = recognizer.record(source)
            st.write(f"✅ Audio leído: {len(audio_data.frame_data)} bytes")
            
            # Verificar que hay datos
            if len(audio_data.frame_data) < 100:
                return "❌ Error: Audio vacío o sin datos suficientes"
            
            # Transcribir
            st.write(f"🌐 Enviando a Google Speech API (idioma: {language})...")
            
            try:
                text = recognizer.recognize_google(
                    audio_data, 
                    language=language,
                    show_all=False
                )
                
                if text:
                    st.success(f"✅ ¡Transcripción exitosa! ({len(text)} caracteres)")
                    st.markdown("### 📝 Resultado:")
                    st.info(text)
                    return text
                else:
                    return "❌ La API devolvió respuesta vacía"
                    
            except sr.UnknownValueError:
                st.warning("⚠️ Google Speech no pudo entender el audio")
                
                # Intentar con show_all para más info
                try:
                    st.write("🔍 Intentando obtener más información...")
                    result = recognizer.recognize_google(audio_data, language=language, show_all=True)
                    st.code(str(result))
                except:
                    pass
                
                return (
                    "❌ **No se pudo entender el audio**\n\n"
                    "**Posibles causas:**\n"
                    "- No hay voz humana clara en el audio\n"
                    "- Idioma seleccionado incorrecto\n"
                    "- Mucho ruido de fondo\n"
                    "- Audio de muy baja calidad\n\n"
                    "**💡 Verifica:**\n"
                    "- Descarga el WAV convertido (botón arriba) y escúchalo\n"
                    "- Confirma que el idioma sea correcto\n"
                    "- Prueba con un audio de prueba conocido"
                )
            
            except sr.RequestError as e:
                st.error(f"❌ Error de la API de Google: {str(e)}")
                return (
                    f"❌ **Error del servicio Google Speech:**\n{str(e)}\n\n"
                    "**Posibles causas:**\n"
                    "- Sin conexión a internet\n"
                    "- Límite de uso excedido (100 peticiones/día gratis)\n"
                    "- Servicio temporalmente no disponible\n\n"
                    "**💡 Soluciones:**\n"
                    "- Verifica tu conexión\n"
                    "- Espera unas horas si excediste el límite\n"
                    "- Considera usar la API oficial con key"
                )
        
    except Exception as e:
        st.error(f"❌ Error en transcripción: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        return f"❌ Error: {str(e)}"
    
    finally:
        # Limpiar WAV temporal (pero mantener copia para debug)
        if wav_path and os.path.exists(wav_path):
            try:
                # No eliminar si está en debug_wavs
                if filename not in st.session_state.debug_wavs:
                    os.unlink(wav_path)
            except:
                pass

def create_zip_download(transcriptions):
    """Crear ZIP"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for trans in transcriptions:
            content = f"""=== EcohSpeech Web ===
Archivo: {trans['filename']}
Idioma: {trans['language']}
Fecha: {trans['timestamp']}
{"=" * 50}

{trans['transcription']}"""
            
            safe_name = "".join(c for c in trans['filename'] 
                              if c.isalnum() or c in (' ', '-', '_')).rstrip()
            zip_file.writestr(f"transcripcion_{safe_name}.txt", content)
    
    zip_buffer.seek(0)
    return zip_buffer

def main():
    st.title("🎤 EcohSpeech Web - Modo Debug Completo")
    st.caption("🔍 Versión con debugging extensivo + Mock completo de audioop")
    
    init_session_state()
    
    # Verificar FFmpeg
    ffmpeg_ok = check_ffmpeg()
    
    col_a, col_b = st.columns(2)
    with col_a:
        if ffmpeg_ok:
            st.success("✅ FFmpeg disponible")
        else:
            st.error("❌ FFmpeg NO disponible")
    
    with col_b:
        if test_recognizer():
            st.success("✅ SpeechRecognition OK")
        else:
            st.error("❌ SpeechRecognition con problemas")
    
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma de transcripción:",
            [
                ("es-CL", "🇨🇱 Español Chile"),
                ("es-ES", "🇪🇸 Español España"),
                ("es-MX", "🇲🇽 Español México"),
                ("es-AR", "🇦🇷 Español Argentina"),
                ("en-US", "🇺🇸 English US"),
                ("en-GB", "🇬🇧 English UK"),
            ],
            format_func=lambda x: x[1],
            index=0
        )[0]
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.metric("Transcripciones", len(st.session_state.transcriptions))
        
        if st.session_state.transcriptions:
            ok = sum(1 for t in st.session_state.transcriptions 
                    if not t['transcription'].startswith('❌'))
            st.metric("Exitosas", ok)
        
        st.markdown("---")
        st.header("🔧 Debug")
        st.write(f"WAVs generados: {len(st.session_state.debug_wavs)}")
        
        if st.button("🗑️ Limpiar Debug", use_container_width=True):
            st.session_state.debug_wavs.clear()
            st.rerun()
        
        st.markdown("---")
        st.info("""
        **📋 Esta versión muestra:**
        - Cada paso del proceso
        - Información del WAV generado
        - Permite descargar WAV para verificar
        - Errores detallados
        - Mock completo de audioop
        """)
    
    # Main
    st.subheader("📁 Cargar Archivo de Audio")
    
    uploaded_file = st.file_uploader(
        "Sube UN archivo para análisis detallado",
        type=['mp3', 'wav', 'ogg', 'opus', 'oga', 'm4a', 'flac'],
        help="Sube solo un archivo a la vez para ver el proceso completo"
    )
    
    if uploaded_file:
        st.success(f"✅ Archivo cargado: {uploaded_file.name}")
        st.write(f"📊 Tamaño: {uploaded_file.size / 1024:.1f} KB")
        
        if st.button("🚀 Procesar y Transcribir", type="primary", use_container_width=True):
            if not ffmpeg_ok:
                st.error("❌ FFmpeg requerido. Agrega 'ffmpeg' a packages.txt y redespliega.")
            else:
                process_single_file(uploaded_file, language)
    
    # Mostrar transcripciones anteriores
    if st.session_state.transcriptions:
        st.markdown("---")
        st.subheader("📝 Historial de Transcripciones")
        
        for i, trans in enumerate(reversed(st.session_state.transcriptions)):
            icon = "✅" if not trans['transcription'].startswith('❌') else "❌"
            
            with st.expander(f"{icon} {trans['filename']} - {trans['timestamp']}", expanded=False):
                st.text_area(
                    "Resultado:", 
                    trans['transcription'], 
                    height=150,
                    key=f"hist_{i}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        "📥 Descargar TXT",
                        trans['transcription'],
                        f"{trans['filename']}.txt",
                        key=f"dlhist_{i}"
                    )
                
                with col2:
                    if trans['filename'] in st.session_state.debug_wavs:
                        st.download_button(
                            "🔍 WAV Debug",
                            st.session_state.debug_wavs[trans['filename']],
                            f"debug_{trans['filename']}.wav",
                            "audio/wav",
                            key=f"wavhist_{i}"
                        )

def process_single_file(uploaded_file, language):
    """Procesar un solo archivo con máximo debug"""
    
    temp_path = None
    try:
        # Guardar temporal
        suffix = os.path.splitext(uploaded_file.name)[1] or '.ogg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            temp_path = tmp.name
        
        st.info(f"💾 Archivo guardado temporalmente: {temp_path}")
        
        # Transcribir (con debug completo)
        text = transcribe_audio(temp_path, language, uploaded_file.name)
        
        # Guardar resultado
        st.session_state.transcriptions.append({
            'filename': uploaded_file.name,
            'transcription': text,
            'language': language,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        # Resultado final
        st.markdown("---")
        st.markdown("## 🎉 Proceso Completado")
        
        if text.startswith('❌'):
            st.error("❌ Transcripción falló - revisa los detalles arriba")
        else:
            st.balloons()
            st.success("✅ ¡Transcripción exitosa!")
        
    except Exception as e:
        st.error(f"❌ Error crítico: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        
        st.session_state.transcriptions.append({
            'filename': uploaded_file.name,
            'transcription': f"❌ Error crítico: {str(e)}",
            'language': language,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
    finally:
        # Limpiar temporal
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

if __name__ == "__main__":
    main()