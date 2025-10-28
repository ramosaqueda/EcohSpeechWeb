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
    try:
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'audioop-lts', '--break-system-packages'])
        import audioop
    except:
        from types import ModuleType
        import struct
        import math
        
        audioop = ModuleType('audioop')
        
        def rms(fragment, width):
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
            return (fragment, state)
        
        audioop.rms = rms
        audioop.ratecv = ratecv
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
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              timeout=5)
        return result.returncode == 0
    except:
        return False

def convert_to_wav(file_path, filename):
    """Convertir a WAV con múltiples estrategias"""
    wav_fd, wav_path = tempfile.mkstemp(suffix='.wav')
    os.close(wav_fd)
    
    is_opus = filename.lower().endswith(('.opus', '.ogg', '.oga'))
    is_whatsapp = 'PTT-' in filename or 'WA' in filename
    
    strategies = []
    
    # Estrategia 1: FFmpeg permisivo para Opus/WhatsApp
    if is_opus or is_whatsapp:
        strategies.append([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-err_detect', 'ignore_err',
            '-fflags', '+genpts+igndts',
            '-analyzeduration', '100M',
            '-probesize', '50M',
            '-i', file_path,
            '-ar', '16000', '-ac', '1',
            '-acodec', 'pcm_s16le',
            wav_path
        ])
    
    # Estrategia 2: FFmpeg estándar
    strategies.append([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', file_path,
        '-ar', '16000', '-ac', '1',
        '-acodec', 'pcm_s16le',
        wav_path
    ])
    
    # Estrategia 3: Pydub
    strategies.append('pydub')
    
    # Intentar cada estrategia
    for strategy in strategies:
        try:
            if strategy == 'pydub':
                audio = AudioSegment.from_file(file_path)
                audio = audio.set_frame_rate(16000).set_channels(1).normalize()
                audio.export(wav_path, format='wav')
            else:
                result = subprocess.run(strategy, capture_output=True, timeout=30)
                if result.returncode != 0:
                    continue
            
            # Verificar que se creó correctamente
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
                return wav_path
        except:
            continue
    
    # Si todo falló
    if os.path.exists(wav_path):
        os.unlink(wav_path)
    raise Exception("No se pudo convertir el archivo de audio")

def transcribe_audio(file_path, language, filename):
    """Transcribir audio"""
    wav_path = None
    
    try:
        recognizer = get_recognizer()
        
        # Convertir a WAV
        wav_path = convert_to_wav(file_path, filename)
        
        # Transcribir
        with sr.AudioFile(wav_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language=language)
        
        return text
        
    except sr.UnknownValueError:
        return "❌ No se pudo entender el audio (verifica idioma y calidad)"
    except sr.RequestError as e:
        return f"❌ Error del servicio: {str(e)}"
    except Exception as e:
        return f"❌ Error: {str(e)}"
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except:
                pass

def create_zip_download(transcriptions):
    """Crear ZIP con todas las transcripciones"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for trans in transcriptions:
            content = f"""EcohSpeech Web - Transcripción
{"=" * 50}
Archivo: {trans['filename']}
Idioma: {trans['language']}
Fecha: {trans['timestamp']}
{"=" * 50}

{trans['transcription']}"""
            
            safe_name = "".join(c for c in trans['filename'] 
                              if c.isalnum() or c in (' ', '-', '_')).rstrip()
            zip_file.writestr(f"{safe_name}.txt", content)
    
    zip_buffer.seek(0)
    return zip_buffer

def main():
    st.title("🎤 EcohSpeech Web")
    st.caption("Transcriptor de audio a texto")
    
    init_session_state()
    
    # Verificar FFmpeg
    if not check_ffmpeg():
        st.error("⚠️ FFmpeg no disponible - Archivos OGG/Opus no funcionarán")
    
    st.markdown("---")
    
    # Layout principal
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("📁 Cargar Archivos")
        
        # Selector de idioma
        language = st.selectbox(
            "Idioma:",
            [
                ("es-CL", "🇨🇱 Español Chile"),
                ("es-ES", "🇪🇸 Español España"),
                ("es-MX", "🇲🇽 Español México"),
                ("en-US", "🇺🇸 English US"),
            ],
            format_func=lambda x: x[1]
        )[0]
        
        # Subir archivos (MÚLTIPLES)
        uploaded_files = st.file_uploader(
            "Selecciona uno o más archivos de audio:",
            type=['mp3', 'wav', 'ogg', 'opus', 'oga', 'm4a', 'flac'],
            accept_multiple_files=True,
            key="file_uploader"
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} archivo(s) seleccionado(s)")
            
            # Mostrar archivos
            with st.expander("Ver archivos", expanded=True):
                for f in uploaded_files:
                    st.write(f"• {f.name} ({f.size/1024:.1f} KB)")
    
    with col2:
        st.subheader("🎯 Acciones")
        
        # Botón transcribir
        if st.button(
            "🚀 Transcribir",
            type="primary",
            disabled=not uploaded_files,
            use_container_width=True
        ):
            process_files(uploaded_files, language)
        
        # Botón reset
        if st.button(
            "🔄 Reset",
            disabled=len(st.session_state.transcriptions) == 0,
            use_container_width=True
        ):
            st.session_state.transcriptions = []
            st.rerun()
        
        # Descargar ZIP
        if st.session_state.transcriptions:
            st.download_button(
                "📥 Descargar ZIP",
                create_zip_download(st.session_state.transcriptions),
                f"transcripciones_{datetime.now():%Y%m%d_%H%M}.zip",
                "application/zip",
                use_container_width=True
            )
        
        # Estadísticas
        if st.session_state.transcriptions:
            st.markdown("---")
            total = len(st.session_state.transcriptions)
            exitosas = sum(1 for t in st.session_state.transcriptions 
                          if not t['transcription'].startswith('❌'))
            
            st.metric("Total", total)
            st.metric("Exitosas", exitosas)
    
    # Mostrar historial
    if st.session_state.transcriptions:
        st.markdown("---")
        st.subheader("📝 Historial de Transcripciones")
        
        for i, trans in enumerate(st.session_state.transcriptions):
            icon = "✅" if not trans['transcription'].startswith('❌') else "❌"
            
            with st.expander(
                f"{icon} {trans['filename']} - {trans['timestamp']}", 
                expanded=False
            ):
                st.text_area(
                    "Transcripción:",
                    trans['transcription'],
                    height=150,
                    key=f"trans_{i}_{trans['timestamp']}"
                )
                
                st.download_button(
                    "📥 Descargar",
                    trans['transcription'],
                    f"{trans['filename']}.txt",
                    key=f"download_{i}_{trans['timestamp']}"
                )

def process_files(uploaded_files, language):
    """Procesar múltiples archivos"""
    
    progress_bar = st.progress(0)
    status = st.empty()
    
    new_transcriptions = []
    
    for i, uploaded_file in enumerate(uploaded_files):
        # Actualizar progreso
        progress = (i + 1) / len(uploaded_files)
        progress_bar.progress(progress)
        status.text(f"⏳ Procesando {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
        
        temp_path = None
        try:
            # Guardar temporal
            suffix = os.path.splitext(uploaded_file.name)[1] or '.ogg'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getvalue())
                temp_path = tmp.name
            
            # Transcribir
            text = transcribe_audio(temp_path, language, uploaded_file.name)
            
            # Guardar resultado
            trans_data = {
                'filename': uploaded_file.name,
                'transcription': text,
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            new_transcriptions.append(trans_data)
            
        except Exception as e:
            new_transcriptions.append({
                'filename': uploaded_file.name,
                'transcription': f"❌ Error: {str(e)}",
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
    
    # Agregar todas las nuevas transcripciones al historial
    st.session_state.transcriptions.extend(new_transcriptions)
    
    # Limpiar
    progress_bar.empty()
    status.empty()
    
    # Resultados
    st.markdown("---")
    st.subheader("✨ Resultados")
    
    exitosas = sum(1 for t in new_transcriptions 
                   if not t['transcription'].startswith('❌'))
    
    if exitosas == len(uploaded_files):
        st.success(f"🎉 ¡{exitosas} transcripciones completadas exitosamente!")
        st.balloons()
    else:
        st.warning(f"⚠️ Completado: {exitosas}/{len(uploaded_files)} exitosas")
    
    # Mostrar resultados recientes
    for i, trans in enumerate(new_transcriptions):
        icon = "✅" if not trans['transcription'].startswith('❌') else "❌"
        
        with st.expander(f"{icon} {trans['filename']}", expanded=(i == 0)):
            st.text_area(
                "Resultado:",
                trans['transcription'],
                height=120,
                key=f"result_{len(st.session_state.transcriptions) - len(new_transcriptions) + i}"
            )

if __name__ == "__main__":
    main()