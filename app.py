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
    if 'processed_files' not in st.session_state:
        st.session_state.processed_files = []

@st.cache_resource
def get_recognizer():
    """Cache del reconocedor para mejor performance"""
    return sr.Recognizer()

def convert_to_wav(file_path):
    """Convertir archivo a WAV"""
    try:
        audio = AudioSegment.from_file(file_path)
        wav_path = file_path + '.wav'
        
        audio.export(
            wav_path, 
            format='wav',
            parameters=["-ac", "1", "-ar", "16000"]
        )
        
        return wav_path
        
    except Exception as e:
        st.error(f"Error en conversión: {str(e)}")
        return None

def transcribe_audio(file_path, language):
    """Transcribir audio"""
    try:
        recognizer = get_recognizer()
        
        wav_path = convert_to_wav(file_path)
        if not wav_path:
            return "Error en conversión a WAV"
        
        with sr.AudioFile(wav_path) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language=language)
            
        # Limpiar archivo temporal
        if wav_path != file_path and os.path.exists(wav_path):
            os.remove(wav_path)
            
        return text
        
    except sr.UnknownValueError:
        return "No se pudo reconocer el audio"
    except sr.RequestError as e:
        return f"Error del servicio: {str(e)}"
    except Exception as e:
        return f"Error inesperado: {str(e)}"

def create_zip_download(transcriptions):
    """Crear archivo ZIP para descarga múltiple"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for trans in transcriptions:
            filename = trans['filename']
            content = trans['transcription']
            
            file_content = f"""=== EcohSpeech Transcripción ===
Archivo: {filename}
Idioma: {trans['language']}
Fecha: {trans['timestamp']}
{"="*40}

{content}"""
            
            zip_file.writestr(f"transcripcion_{filename}.txt", file_content)
    
    zip_buffer.seek(0)
    return zip_buffer

def main():
    st.title("🎤 EcohSpeech Web - Transcriptor de Audio")
    st.markdown("---")
    
    # Inicializar estado
    init_session_state()
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma:",
            ["es-CL", "es-ES", "en-US", "fr-FR", "de-DE"]
        )
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.write(f"Archivos procesados: {len(st.session_state.processed_files)}")
    
    # Área principal
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📁 Cargar Archivos de Audio")
        
        uploaded_files = st.file_uploader(
            "Selecciona archivos de audio",
            type=['mp3', 'wav', 'm4a', 'ogg', 'flac'],
            accept_multiple_files=True
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} archivo(s) cargado(s)")
    
    with col2:
        st.subheader("🎯 Acciones")
        
        if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True):
            if not uploaded_files:
                st.error("❌ Carga al menos un archivo")
            else:
                process_files(uploaded_files, language)
        
        # Descargar todo
        if st.session_state.transcriptions:
            zip_buffer = create_zip_download(st.session_state.transcriptions)
            st.download_button(
                label="📥 Descargar Todo (ZIP)",
                data=zip_buffer,
                file_name=f"transcripciones_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )

def process_files(uploaded_files, language):
    """Procesar archivos cargados"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, uploaded_file in enumerate(uploaded_files):
        progress = (i + 1) / len(uploaded_files)
        progress_bar.progress(progress)
        status_text.text(f"Procesando: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        
        try:
            # Archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                audio_path = tmp_file.name
            
            # Transcripción
            transcription = transcribe_audio(audio_path, language)
            
            # Guardar en sesión
            trans_data = {
                'filename': uploaded_file.name,
                'transcription': transcription,
                'language': language,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            st.session_state.transcriptions.append(trans_data)
            st.session_state.processed_files.append(uploaded_file.name)
            
            # Mostrar resultado
            with st.expander(f"🎵 {uploaded_file.name}", expanded=True):
                st.text_area(
                    "Transcripción:", 
                    transcription, 
                    height=120,
                    key=f"trans_{i}"
                )
                
                # Descarga individual
                st.download_button(
                    label="📥 Descargar Individual",
                    data=transcription,
                    file_name=f"transcripcion_{uploaded_file.name}.txt",
                    mime="text/plain",
                    key=f"dl_{i}"
                )
            
            # Limpiar
            os.unlink(audio_path)
            
        except Exception as e:
            st.error(f"❌ Error en {uploaded_file.name}: {str(e)}")
    
    # Finalizar
    progress_bar.empty()
    status_text.success("✅ ¡Completado!")

if __name__ == "__main__":
    main()