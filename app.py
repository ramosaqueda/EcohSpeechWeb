import streamlit as st
import sys
import os

# PATCH para Python 3.13+
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
    from types import ModuleType
    audioop = ModuleType('audioop')
    audioop.ratecv = lambda *args: (args[0], None)
    audioop.lin2ulaw = lambda fragment, width: fragment
    audioop.ulaw2lin = lambda fragment, width: fragment
    sys.modules['audioop'] = audioop

import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import io
import zipfile
from datetime import datetime
import subprocess

# Configuración
st.set_page_config(
    page_title="EcohSpeech Web",
    page_icon="🎤",
    layout="wide"
)

def init_session_state():
    if 'transcriptions' not in st.session_state:
        st.session_state.transcriptions = []

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

def convert_to_wav_robust(file_path, filename):
    """
    Convertir a WAV con múltiples estrategias para archivos problemáticos
    Especialmente diseñado para archivos de WhatsApp y Opus/OGG corruptos
    """
    wav_fd, wav_path = tempfile.mkstemp(suffix='.wav')
    os.close(wav_fd)
    
    # Detectar si es archivo de WhatsApp
    is_whatsapp = 'PTT-' in filename or 'WA' in filename or 'AUD-' in filename
    is_opus = filename.lower().endswith(('.opus', '.ogg', '.oga'))
    
    strategies = []
    
    # ESTRATEGIA 1: FFmpeg directo con parámetros permisivos (para Opus/OGG problemáticos)
    if is_opus or is_whatsapp:
        strategies.append({
            'name': 'FFmpeg permisivo (Opus/OGG)',
            'cmd': [
                'ffmpeg', '-y',
                '-err_detect', 'ignore_err',  # Ignorar errores de decodificación
                '-fflags', '+genpts+igndts',  # Generar timestamps
                '-analyzeduration', '10M',    # Más tiempo para analizar
                '-probesize', '10M',          # Más datos para detectar formato
                '-i', file_path,
                '-ar', '16000',               # 16kHz
                '-ac', '1',                   # Mono
                '-sample_fmt', 's16',         # 16-bit
                '-acodec', 'pcm_s16le',       # PCM sin compresión
                wav_path
            ]
        })
    
    # ESTRATEGIA 2: Pydub con parámetros específicos
    strategies.append({
        'name': 'Pydub con parámetros',
        'pydub': True,
        'params': {'format': 'ogg'} if is_opus else {}
    })
    
    # ESTRATEGIA 3: FFmpeg con conversión forzada a raw PCM primero
    if is_opus:
        strategies.append({
            'name': 'FFmpeg vía PCM raw',
            'two_step': True
        })
    
    # ESTRATEGIA 4: FFmpeg estándar
    strategies.append({
        'name': 'FFmpeg estándar',
        'cmd': [
            'ffmpeg', '-y',
            '-i', file_path,
            '-ar', '16000',
            '-ac', '1',
            wav_path
        ]
    })
    
    # Intentar cada estrategia
    for i, strategy in enumerate(strategies, 1):
        try:
            st.info(f"🔄 Intento {i}/{len(strategies)}: {strategy['name']}")
            
            # Estrategia Pydub
            if strategy.get('pydub'):
                audio = AudioSegment.from_file(file_path, **strategy.get('params', {}))
                audio = audio.set_frame_rate(16000).set_channels(1).normalize()
                audio.export(wav_path, format='wav')
                
                # Verificar que el archivo se creó
                if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                    st.success(f"✅ Conversión exitosa con: {strategy['name']}")
                    return wav_path
            
            # Estrategia dos pasos (raw PCM)
            elif strategy.get('two_step'):
                # Paso 1: A raw PCM
                raw_fd, raw_path = tempfile.mkstemp(suffix='.raw')
                os.close(raw_fd)
                
                cmd1 = [
                    'ffmpeg', '-y',
                    '-err_detect', 'ignore_err',
                    '-i', file_path,
                    '-f', 's16le',
                    '-ar', '16000',
                    '-ac', '1',
                    raw_path
                ]
                
                result1 = subprocess.run(cmd1, capture_output=True, timeout=30)
                
                if result1.returncode == 0 and os.path.getsize(raw_path) > 1000:
                    # Paso 2: Raw PCM a WAV
                    cmd2 = [
                        'ffmpeg', '-y',
                        '-f', 's16le',
                        '-ar', '16000',
                        '-ac', '1',
                        '-i', raw_path,
                        wav_path
                    ]
                    
                    result2 = subprocess.run(cmd2, capture_output=True, timeout=30)
                    
                    # Limpiar raw
                    if os.path.exists(raw_path):
                        os.unlink(raw_path)
                    
                    if result2.returncode == 0 and os.path.getsize(wav_path) > 1000:
                        st.success(f"✅ Conversión exitosa con: {strategy['name']}")
                        return wav_path
            
            # Estrategia FFmpeg directo
            elif 'cmd' in strategy:
                result = subprocess.run(
                    strategy['cmd'],
                    capture_output=True,
                    timeout=30,
                    text=True
                )
                
                # Verificar éxito
                if result.returncode == 0 and os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                    st.success(f"✅ Conversión exitosa con: {strategy['name']}")
                    return wav_path
                else:
                    # Mostrar error solo en modo debug
                    if result.stderr:
                        with st.expander(f"⚠️ Error en {strategy['name']}", expanded=False):
                            st.code(result.stderr[-500:], language='text')
        
        except Exception as e:
            st.warning(f"⚠️ {strategy['name']} falló: {str(e)[:100]}")
            continue
    
    # Si todas las estrategias fallaron
    if os.path.exists(wav_path):
        os.unlink(wav_path)
    
    raise Exception(
        "No se pudo convertir el archivo después de múltiples intentos. "
        "Posibles causas:\n"
        "• Archivo corrupto o incompleto\n"
        "• Formato no estándar (ej: WhatsApp con encriptación)\n"
        "• Codec no soportado\n\n"
        "💡 Sugerencias:\n"
        "• Intenta reproducir el audio en tu teléfono primero\n"
        "• Reenvía el audio (sin reenviar como documento)\n"
        "• Convierte manualmente a MP3 o WAV antes de subir"
    )

def transcribe_audio(file_path, language, filename):
    """Transcribir audio con manejo robusto"""
    wav_path = None
    try:
        recognizer = get_recognizer()
        
        # Convertir a WAV con estrategias robustas
        st.info(f"🔄 Procesando: {filename}")
        wav_path = convert_to_wav_robust(file_path, filename)
        
        # Verificar que el WAV es válido
        if not wav_path or not os.path.exists(wav_path):
            return "❌ No se pudo crear archivo WAV válido"
        
        file_size = os.path.getsize(wav_path) / 1024
        st.info(f"📊 WAV creado: {file_size:.1f} KB")
        
        # Transcribir
        with sr.AudioFile(wav_path) as source:
            st.info("🎧 Ajustando ruido ambiente...")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            
            st.info("📖 Leyendo audio...")
            audio_data = recognizer.record(source)
            
            st.info(f"🌐 Transcribiendo en {language}...")
            text = recognizer.recognize_google(audio_data, language=language)
        
        if text:
            st.success(f"✅ Transcrito: {len(text)} caracteres")
        
        return text
        
    except sr.UnknownValueError:
        return "❌ No se pudo entender el audio.\n\n💡 Consejos:\n• Verifica que haya voz clara\n• Reduce ruido de fondo\n• Confirma el idioma correcto"
    
    except sr.RequestError as e:
        return f"❌ Error del servicio Google Speech:\n{str(e)}\n\n💡 Verifica tu conexión a internet"
    
    except Exception as e:
        error_msg = str(e)
        if "after multiple" in error_msg:
            return f"❌ {error_msg}"
        return f"❌ Error: {error_msg}"
    
    finally:
        # Limpiar WAV temporal
        if wav_path and os.path.exists(wav_path):
            try:
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
    st.title("🎤 EcohSpeech Web - Transcriptor Robusto")
    st.caption("✨ Optimizado para archivos de WhatsApp y formatos problemáticos")
    
    init_session_state()
    
    # Verificar FFmpeg
    ffmpeg_ok = check_ffmpeg()
    if ffmpeg_ok:
        st.success("✅ FFmpeg disponible - Soporte completo para Opus/OGG")
    else:
        st.error("❌ FFmpeg NO disponible - Archivos Opus/OGG no funcionarán")
        st.info("📋 Agrega `packages.txt` con 'ffmpeg' y redespliega")
    
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma:",
            ["es-CL", "es-ES", "es-MX", "en-US", "en-GB"],
            index=0
        )
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.metric("Transcripciones", len(st.session_state.transcriptions))
        
        if st.session_state.transcriptions:
            ok = sum(1 for t in st.session_state.transcriptions 
                    if not t['transcription'].startswith('❌'))
            st.metric("Exitosas", ok)
            st.metric("Con errores", len(st.session_state.transcriptions) - ok)
        
        st.markdown("---")
        st.header("💡 Tips")
        st.info("""
        **✅ Formatos soportados:**
        • WAV, MP3, FLAC
        • OGG, Opus (con FFmpeg)
        • M4A (con FFmpeg)
        
        **📱 WhatsApp:**
        • Archivos PTT soportados
        • Usa múltiples estrategias
        • Maneja archivos corruptos
        
        **🎯 Mejores resultados:**
        • Voz clara y audible
        • Sin música de fondo
        • Max 10MB por archivo
        """)
        
        st.markdown("---")
        with st.expander("🔧 Información Técnica"):
            st.code(f"""
FFmpeg: {'✅' if ffmpeg_ok else '❌'}
Python: {sys.version.split()[0]}
Streamlit: {st.__version__}
            """)
    
    # Main
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📁 Cargar Audio")
        
        files = st.file_uploader(
            "Arrastra archivos (incluye PTT de WhatsApp)",
            type=['mp3', 'wav', 'ogg', 'opus', 'oga', 'm4a', 'flac'],
            accept_multiple_files=True,
            help="Soporta archivos de WhatsApp y formatos problemáticos"
        )
        
        if files:
            st.success(f"✅ {len(files)} archivo(s) cargado(s)")
            with st.expander("📋 Ver archivos", expanded=True):
                for f in files:
                    size_mb = f.size / 1024 / 1024
                    icon = "📱" if 'PTT-' in f.name or 'WA' in f.name else "🎵"
                    st.write(f"{icon} **{f.name}** ({size_mb:.2f} MB)")
    
    with col2:
        st.subheader("🎯 Acciones")
        
        if st.button("🚀 Transcribir", 
                    type="primary",
                    disabled=not files or not ffmpeg_ok,
                    use_container_width=True):
            process_files(files, language)
        
        if not ffmpeg_ok:
            st.warning("⚠️ FFmpeg requerido")
        
        if st.session_state.transcriptions:
            st.download_button(
                "📥 Descargar ZIP",
                create_zip_download(st.session_state.transcriptions),
                f"transcripciones_{datetime.now():%Y%m%d_%H%M}.zip",
                "application/zip",
                use_container_width=True
            )
        
        if st.button("🗑️ Limpiar",
                    disabled=not st.session_state.transcriptions,
                    use_container_width=True):
            st.session_state.transcriptions.clear()
            st.rerun()

def process_files(files, language):
    """Procesar archivos con feedback detallado"""
    progress = st.progress(0)
    
    for i, file in enumerate(files):
        st.markdown(f"### 📄 Procesando {i+1}/{len(files)}: {file.name}")
        progress.progress((i + 1) / len(files))
        
        temp_path = None
        try:
            # Guardar temporal
            suffix = os.path.splitext(file.name)[1] or '.ogg'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file.getvalue())
                temp_path = tmp.name
            
            # Transcribir (con feedback interno)
            text = transcribe_audio(temp_path, language, file.name)
            
            # Guardar resultado
            st.session_state.transcriptions.append({
                'filename': file.name,
                'transcription': text,
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # Mostrar resultado inmediato
            if text.startswith('❌'):
                st.error(f"Error en {file.name}")
            else:
                st.success(f"✅ ¡Transcripción exitosa!")
                with st.expander("Ver transcripción", expanded=True):
                    st.write(text)
            
        except Exception as e:
            st.error(f"Error crítico: {str(e)}")
            st.session_state.transcriptions.append({
                'filename': file.name,
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
        
        st.markdown("---")
    
    # Finalizar
    progress.empty()
    
    successful = sum(1 for t in st.session_state.transcriptions[-len(files):] 
                    if not t['transcription'].startswith('❌'))
    
    if successful == len(files):
        st.balloons()
        st.success(f"🎉 ¡{successful} transcripciones completadas!")
    else:
        st.warning(f"⚠️ Completado: {successful}/{len(files)} exitosas")
    
    # Resumen de resultados
    st.subheader("📝 Resumen de Resultados")
    for i, trans in enumerate(st.session_state.transcriptions[-len(files):]):
        icon = "✅" if not trans['transcription'].startswith('❌') else "❌"
        
        with st.expander(f"{icon} {trans['filename']}", expanded=False):
            st.text_area(
                "Transcripción:", 
                trans['transcription'], 
                height=150,
                key=f"result_{len(st.session_state.transcriptions)-len(files)+i}"
            )
            st.download_button(
                "📥 Descargar TXT",
                trans['transcription'],
                f"{trans['filename']}.txt",
                key=f"dl_{len(st.session_state.transcriptions)-len(files)+i}"
            )

if __name__ == "__main__":
    main()