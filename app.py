# app.py
import streamlit as st
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import os
import io
import zipfile
from datetime import datetime

# Configuración de página
st.set_page_config(
    page_title="EcohSpeech Web",
    page_icon="🎤",
    layout="wide"
)

def init_session_state():
    """Inicializar estado de la sesión"""
    if 'transcriptions' not in st.session_state:
        st.session_state.transcriptions = []

@st.cache_resource
def get_recognizer():
    """Cache del reconocedor para mejor performance"""
    return sr.Recognizer()

def convert_to_wav(file_path):
    """Convertir archivo a WAV optimizado para transcripción"""
    try:
        # Cargar audio
        audio = AudioSegment.from_file(file_path)
        
        # Crear archivo temporal WAV
        wav_path = file_path + '.wav'
        
        # Exportar optimizado para reconocimiento de voz
        audio = audio.set_frame_rate(16000)  # 16kHz recomendado
        audio = audio.set_channels(1)        # Mono
        
        audio.export(
            wav_path, 
            format='wav',
            parameters=["-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le"]
        )
        
        return wav_path
        
    except Exception as e:
        st.error(f"Error en conversión de audio: {str(e)}")
        return None

def transcribe_audio(file_path, language):
    """Transcribir audio con manejo robusto de errores"""
    try:
        recognizer = get_recognizer()
        
        # Convertir a WAV si es necesario
        wav_path = convert_to_wav(file_path)
        if not wav_path:
            return "❌ Error: No se pudo convertir el audio a formato compatible"
        
        with sr.AudioFile(wav_path) as source:
            # Ajustar para ruido ambiente
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            
            # Leer audio
            audio_data = recognizer.record(source)
            
            # Transcribir con Google Speech Recognition
            text = recognizer.recognize_google(audio_data, language=language)
            
        # Limpiar archivo temporal WAV
        if wav_path != file_path and os.path.exists(wav_path):
            os.remove(wav_path)
            
        return text
        
    except sr.UnknownValueError:
        return "❌ No se pudo entender el audio. Intenta con un archivo más claro."
    except sr.RequestError as e:
        return f"❌ Error del servicio de reconocimiento: {str(e)}"
    except Exception as e:
        return f"❌ Error inesperado: {str(e)}"

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
    st.markdown("*Versión web optimizada para Streamlit Cloud*")
    st.markdown("---")
    
    # Inicializar estado
    init_session_state()
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma de reconocimiento:",
            [
                "es-CL", "es-ES", "es-MX", "es-AR",  # Variantes de español
                "en-US", "en-GB",                    # Inglés
                "fr-FR", "de-DE", "it-IT", "pt-BR"   # Otros idiomas
            ],
            index=0
        )
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.write(f"Transcripciones en sesión: {len(st.session_state.transcriptions)}")
        
        if st.session_state.transcriptions:
            successful = len([t for t in st.session_state.transcriptions if not t['transcription'].startswith('❌')])
            st.write(f"✅ Exitosas: {successful}")
            st.write(f"❌ Con errores: {len(st.session_state.transcriptions) - successful}")
        
        st.markdown("---")
        st.header("💡 Tips")
        st.info("""
        - Formatos soportados: MP3, WAV, M4A, OGG, FLAC
        - Audio claro = Mejor transcripción
        - Máximo ~10MB por archivo
        """)
    
    # Área principal
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📁 Cargar Archivos de Audio")
        
        uploaded_files = st.file_uploader(
            "Arrastra o selecciona archivos de audio",
            type=['mp3', 'wav', 'm4a', 'ogg', 'flac'],
            accept_multiple_files=True,
            help="Puedes seleccionar múltiples archivos a la vez"
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} archivo(s) listo(s) para procesar")
            
            # Mostrar preview de archivos
            with st.expander("📋 Ver archivos cargados", expanded=True):
                for file in uploaded_files:
                    file_size = file.size / (1024 * 1024)  # MB
                    st.write(f"• **{file.name}** ({file_size:.2f} MB)")
    
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
    results_placeholder = st.empty()
    
    results = []
    
    for i, uploaded_file in enumerate(uploaded_files):
        # Actualizar progreso
        progress = (i + 1) / len(uploaded_files)
        progress_bar.progress(progress)
        status_text.text(f"🔍 Procesando: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        
        try:
            # Guardar archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                audio_path = tmp_file.name
            
            # Transcribir
            transcription = transcribe_audio(audio_path, language)
            
            # Guardar resultado
            trans_data = {
                'filename': uploaded_file.name,
                'transcription': transcription,
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            st.session_state.transcriptions.append(trans_data)
            results.append(trans_data)
            
            # Limpiar archivo temporal
            os.unlink(audio_path)
            
        except Exception as e:
            error_trans = {
                'filename': uploaded_file.name,
                'transcription': f"❌ Error crítico: {str(e)}",
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            st.session_state.transcriptions.append(error_trans)
            results.append(error_trans)
    
    # Mostrar resultados
    with results_placeholder.container():
        st.subheader("📝 Resultados de Transcripción")
        
        successful = len([r for r in results if not r['transcription'].startswith('❌')])
        
        if successful > 0:
            st.success(f"✅ {successful} de {len(uploaded_files)} transcripciones exitosas!")
        
        for i, result in enumerate(results):
            # Icono según resultado
            icon = "✅" if not result['transcription'].startswith('❌') else "❌"
            
            with st.expander(f"{icon} {result['filename']}", expanded=(i == 0)):
                st.text_area(
                    "Transcripción:", 
                    result['transcription'], 
                    height=150,
                    key=f"result_{i}"
                )
                
                # Botón de descarga individual
                st.download_button(
                    label="📥 Descargar Individual",
                    data=result['transcription'],
                    file_name=f"transcripcion_{result['filename']}.txt",
                    mime="text/plain",
                    key=f"download_{i}"
                )
    
    # Finalizar
    progress_bar.empty()
    if successful == len(uploaded_files):
        status_text.success("🎉 ¡Todas las transcripciones completadas exitosamente!")
        st.balloons()
    else:
        status_text.warning(f"⚠️ Completado con {len(uploaded_files) - successful} error(es)")

if __name__ == "__main__":
    main()