import streamlit as st
import sys
import os

# PATCH para Python 3.13+ - Antes de importar speech_recognition
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
from pydub.utils import which
import tempfile
import io
import zipfile
from datetime import datetime
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de página
st.set_page_config(
    page_title="EcohSpeech Web",
    page_icon="🎤",
    layout="wide"
)

def check_ffmpeg():
    """Verificar si FFmpeg está disponible"""
    ffmpeg_path = which("ffmpeg")
    if ffmpeg_path:
        logger.info(f"✅ FFmpeg encontrado en: {ffmpeg_path}")
        return True
    else:
        logger.warning("⚠️ FFmpeg NO encontrado")
        return False

def init_session_state():
    """Inicializar estado de la sesión"""
    if 'transcriptions' not in st.session_state:
        st.session_state.transcriptions = []
    if 'ffmpeg_available' not in st.session_state:
        st.session_state.ffmpeg_available = check_ffmpeg()

@st.cache_resource
def get_recognizer():
    """Cache del reconocedor para mejor performance"""
    return sr.Recognizer()

def detect_audio_format(file_bytes, filename):
    """Detectar formato real del archivo de audio"""
    # Firmas de archivos (magic numbers)
    signatures = {
        b'OggS': 'ogg',  # OGG/Opus/Vorbis
        b'RIFF': 'wav',
        b'ID3': 'mp3',
        b'\xff\xfb': 'mp3',
        b'\xff\xf3': 'mp3',
        b'\xff\xf2': 'mp3',
        b'fLaC': 'flac',
    }
    
    # Leer primeros bytes
    header = file_bytes[:4]
    
    for signature, fmt in signatures.items():
        if header.startswith(signature):
            logger.info(f"🔍 Formato detectado por firma: {fmt}")
            return fmt
    
    # Fallback a extensión
    ext = filename.split('.')[-1].lower()
    logger.info(f"🔍 Formato por extensión: {ext}")
    return ext

def convert_to_wav(file_path, original_format):
    """Convertir archivo a WAV optimizado para transcripción"""
    try:
        logger.info(f"🔄 Convirtiendo {original_format} a WAV...")
        
        # Verificar FFmpeg para formatos que lo requieren
        if original_format in ['ogg', 'opus', 'oga', 'm4a'] and not st.session_state.ffmpeg_available:
            raise Exception(f"FFmpeg requerido para formato {original_format}. Ver instrucciones de instalación.")
        
        # Parámetros específicos por formato
        format_params = {
            'ogg': {'codec': 'libvorbis'},
            'opus': {'codec': 'opus'},
            'oga': {'codec': 'libvorbis'},
        }
        
        # Cargar audio con parámetros específicos
        load_params = format_params.get(original_format, {})
        audio = AudioSegment.from_file(file_path, format=original_format, **load_params)
        
        logger.info(f"📊 Audio cargado: {len(audio)}ms, {audio.frame_rate}Hz, {audio.channels} canales")
        
        # Crear archivo temporal WAV
        wav_fd, wav_path = tempfile.mkstemp(suffix='.wav', prefix='ecoh_')
        os.close(wav_fd)  # Cerrar descriptor de archivo
        
        # Optimizar para reconocimiento de voz
        audio = audio.set_frame_rate(16000)  # 16kHz recomendado
        audio = audio.set_channels(1)        # Mono
        audio = audio.set_sample_width(2)    # 16-bit
        
        # Normalizar volumen
        audio = audio.normalize()
        
        # Exportar
        audio.export(
            wav_path, 
            format='wav',
            parameters=["-ar", "16000", "-ac", "1"]
        )
        
        logger.info(f"✅ Conversión exitosa: {wav_path}")
        return wav_path
        
    except Exception as e:
        logger.error(f"❌ Error en conversión: {str(e)}")
        raise Exception(f"Error al convertir audio: {str(e)}")

def transcribe_audio(file_path, language, original_format):
    """Transcribir audio con manejo robusto de errores"""
    wav_path = None
    try:
        recognizer = get_recognizer()
        
        # Ajustar configuración del reconocedor
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        
        # Convertir a WAV
        logger.info(f"🎤 Iniciando transcripción de {original_format}...")
        wav_path = convert_to_wav(file_path, original_format)
        
        with sr.AudioFile(wav_path) as source:
            # Ajustar para ruido ambiente
            logger.info("🔇 Ajustando ruido ambiente...")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            
            # Leer audio
            logger.info("📖 Leyendo audio...")
            audio_data = recognizer.record(source)
            
            # Transcribir con Google Speech Recognition
            logger.info(f"🌐 Transcribiendo en {language}...")
            text = recognizer.recognize_google(audio_data, language=language)
            
        logger.info(f"✅ Transcripción exitosa: {len(text)} caracteres")
        return text
        
    except sr.UnknownValueError:
        logger.warning("⚠️ Audio no entendible")
        return "❌ No se pudo entender el audio. Verifica que:\n- El audio tenga voz clara\n- No haya mucho ruido de fondo\n- El idioma seleccionado sea correcto"
    
    except sr.RequestError as e:
        logger.error(f"❌ Error del servicio: {e}")
        return f"❌ Error del servicio de reconocimiento: {str(e)}\n\nPosibles causas:\n- Sin conexión a internet\n- Límite de uso excedido\n- Servicio temporalmente no disponible"
    
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}")
        return f"❌ Error al procesar el audio: {str(e)}"
    
    finally:
        # Limpiar archivo temporal WAV
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
                logger.info("🗑️ Archivo temporal eliminado")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo eliminar temporal: {e}")

def create_zip_download(transcriptions):
    """Crear archivo ZIP para descarga múltiple"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for trans in transcriptions:
            filename = trans['filename']
            content = trans['transcription']
            
            file_content = f"""=== EcohSpeech Web Transcripción ===
Archivo: {filename}
Idioma: {trans['language']}
Formato: {trans.get('format', 'desconocido')}
Fecha: {trans['timestamp']}
Estado: {'✅ Exitosa' if not content.startswith('❌') else '❌ Con errores'}
{"=" * 50}

{content}"""
            
            # Nombre seguro para el archivo
            safe_name = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).rstrip()
            zip_file.writestr(f"transcripcion_{safe_name}.txt", file_content)
    
    zip_buffer.seek(0)
    return zip_buffer

def main():
    st.title("🎤 EcohSpeech Web - Transcriptor de Audio")
    st.markdown("*Versión web optimizada para Streamlit Cloud con soporte OGG/Opus*")
    
    # Inicializar estado
    init_session_state()
    
    # Mostrar estado de FFmpeg
    if not st.session_state.ffmpeg_available:
        st.warning("""
        ⚠️ **FFmpeg no detectado** - Los formatos OGG/Opus/M4A pueden no funcionar.
        
        **Para habilitar soporte completo:**
        1. Crea un archivo `packages.txt` con: `ffmpeg` y `libavcodec-extra`
        2. Redespliega la aplicación en Streamlit Cloud
        """)
    else:
        st.success("✅ FFmpeg disponible - Todos los formatos soportados")
    
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma de reconocimiento:",
            [
                "es-CL", "es-ES", "es-MX", "es-AR",
                "en-US", "en-GB",
                "fr-FR", "de-DE", "it-IT", "pt-BR"
            ],
            index=0
        )
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.write(f"Transcripciones en sesión: {len(st.session_state.transcriptions)}")
        
        if st.session_state.transcriptions:
            successful = len([t for t in st.session_state.transcriptions 
                            if not t['transcription'].startswith('❌')])
            st.write(f"✅ Exitosas: {successful}")
            st.write(f"❌ Con errores: {len(st.session_state.transcriptions) - successful}")
        
        st.markdown("---")
        st.header("💡 Tips")
        st.info("""
        **Formatos soportados:**
        - ✅ WAV, FLAC (sin FFmpeg)
        - ✅ MP3 (sin FFmpeg)
        - ⚠️ OGG, Opus, M4A (requieren FFmpeg)
        
        **Mejores resultados:**
        - Audio claro y sin ruido
        - Voz a volumen normal
        - Máximo 10MB por archivo
        - Evitar música de fondo
        """)
        
        st.markdown("---")
        st.header("🔧 Información Técnica")
        st.code(f"""
FFmpeg: {'✅ Disponible' if st.session_state.ffmpeg_available else '❌ No disponible'}
Python: {sys.version.split()[0]}
        """)
    
    # Área principal
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📁 Cargar Archivos de Audio")
        
        uploaded_files = st.file_uploader(
            "Arrastra o selecciona archivos de audio",
            type=['mp3', 'wav', 'm4a', 'ogg', 'opus', 'oga', 'flac'],
            accept_multiple_files=True,
            help="Soporta múltiples formatos. OGG/Opus requieren FFmpeg instalado."
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} archivo(s) listo(s) para procesar")
            
            # Mostrar preview de archivos
            with st.expander("📋 Ver archivos cargados", expanded=True):
                for file in uploaded_files:
                    file_size = file.size / (1024 * 1024)  # MB
                    format_detected = detect_audio_format(file.getvalue(), file.name)
                    st.write(f"• **{file.name}** ({file_size:.2f} MB) - Formato: `{format_detected}`")
    
    with col2:
        st.subheader("🎯 Acciones")
        
        # Botón de transcripción
        if st.button("🚀 Iniciar Transcripción", 
                    type="primary", 
                    use_container_width=True,
                    disabled=not uploaded_files):
            process_files(uploaded_files, language)
        
        # Descargar todo
        if st.session_state.transcriptions:
            st.download_button(
                label="📥 Descargar Todo (ZIP)",
                data=create_zip_download(st.session_state.transcriptions),
                file_name=f"transcripciones_ecohspeech_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )
        
        # Limpiar resultados
        if st.button("🗑️ Limpiar Resultados", 
                    use_container_width=True,
                    disabled=not st.session_state.transcriptions):
            st.session_state.transcriptions.clear()
            st.rerun()

def process_files(uploaded_files, language):
    """Procesar archivos cargados con barra de progreso"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_placeholder = st.container()
    
    results = []
    
    for i, uploaded_file in enumerate(uploaded_files):
        # Actualizar progreso
        progress = (i + 1) / len(uploaded_files)
        progress_bar.progress(progress)
        status_text.text(f"🔍 Procesando: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        
        audio_path = None
        try:
            # Detectar formato real
            file_bytes = uploaded_file.getvalue()
            original_format = detect_audio_format(file_bytes, uploaded_file.name)
            
            # Guardar archivo temporal con extensión correcta
            suffix = f".{original_format}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(file_bytes)
                audio_path = tmp_file.name
            
            logger.info(f"💾 Archivo temporal creado: {audio_path}")
            
            # Transcribir
            transcription = transcribe_audio(audio_path, language, original_format)
            
            # Guardar resultado
            trans_data = {
                'filename': uploaded_file.name,
                'transcription': transcription,
                'language': language,
                'format': original_format,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            st.session_state.transcriptions.append(trans_data)
            results.append(trans_data)
            
        except Exception as e:
            logger.error(f"❌ Error procesando {uploaded_file.name}: {e}")
            error_trans = {
                'filename': uploaded_file.name,
                'transcription': f"❌ Error crítico: {str(e)}",
                'language': language,
                'format': 'error',
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            st.session_state.transcriptions.append(error_trans)
            results.append(error_trans)
        
        finally:
            # Limpiar archivo temporal
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                    logger.info(f"🗑️ Temporal eliminado: {audio_path}")
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo eliminar {audio_path}: {e}")
    
    # Mostrar resultados
    with results_placeholder:
        st.subheader("📝 Resultados de Transcripción")
        
        successful = len([r for r in results if not r['transcription'].startswith('❌')])
        
        if successful > 0:
            st.success(f"✅ {successful} de {len(uploaded_files)} transcripciones exitosas!")
        
        if successful < len(uploaded_files):
            st.warning(f"⚠️ {len(uploaded_files) - successful} archivo(s) con errores")
        
        for i, result in enumerate(results):
            # Icono según resultado
            icon = "✅" if not result['transcription'].startswith('❌') else "❌"
            
            with st.expander(f"{icon} {result['filename']} [{result.get('format', 'unknown')}]", 
                           expanded=(i == 0)):
                st.text_area(
                    "Transcripción:", 
                    result['transcription'], 
                    height=150,
                    key=f"result_{i}_{result['timestamp']}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    # Botón de descarga individual
                    st.download_button(
                        label="📥 Descargar TXT",
                        data=result['transcription'],
                        file_name=f"transcripcion_{result['filename']}.txt",
                        mime="text/plain",
                        key=f"download_{i}_{result['timestamp']}"
                    )
                
                with col2:
                    st.caption(f"🕐 {result['timestamp']}")
    
    # Finalizar
    progress_bar.empty()
    if successful == len(uploaded_files):
        status_text.success("🎉 ¡Todas las transcripciones completadas exitosamente!")
        st.balloons()
    else:
        status_text.warning(f"⚠️ Completado con {len(uploaded_files) - successful} error(es)")

if __name__ == "__main__":
    main()
  