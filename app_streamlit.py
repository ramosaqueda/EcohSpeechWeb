# app_streamlit.py
import streamlit as st
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import os
import hashlib
from datetime import datetime
import zipfile
import io

# Configuración de página
st.set_page_config(
    page_title="EcohSpeech Web",
    page_icon="🎤",
    layout="wide"
)

def init_session_state():
    if 'transcriptions' not in st.session_state:
        st.session_state.transcriptions = []
    if 'processed_files' not in st.session_state:
        st.session_state.processed_files = []

def save_transcription_locally(filename, transcription, language):
    """Guardar transcripción en sistema de archivos local"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).rstrip()
    output_filename = f"transcripcion_{safe_filename}_{timestamp}.txt"
    
    output_path = os.path.join("transcripciones", output_filename)
    os.makedirs("transcripciones", exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"=== EcohSpeech Transcripción ===\n")
        f.write(f"Archivo: {filename}\n")
        f.write(f"Idioma: {language}\n")
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 40 + "\n\n")
        f.write(transcription)
    
    return output_path

def convert_to_wav(file_path):
    """Convertir archivo a WAV (similar a tu función original)"""
    try:
        audio_format = file_path.split('.')[-1].lower()
        
        if audio_format == 'wav':
            return file_path
            
        audio = AudioSegment.from_file(file_path)
        wav_path = file_path + '.wav'
        
        # Exportar con configuraciones optimizadas
        audio.export(
            wav_path, 
            format='wav',
            parameters=["-ac", "1", "-ar", "16000"]
        )
        
        return wav_path
        
    except Exception as e:
        st.error(f"Error en conversión: {str(e)}")
        return None

def transcribe_audio(file_path, language, enable_preprocessing=True):
    """Transcribir audio - adaptada de tu código"""
    try:
        recognizer = sr.Recognizer()
        
        # Convertir a WAV si es necesario
        wav_path = convert_to_wav(file_path)
        if not wav_path:
            return "Error en conversión a WAV"
        
        with sr.AudioFile(wav_path) as source:
            # Ajustar para ruido ambiente
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
            
            # Transcribir con Google
            text = recognizer.recognize_google(audio_data, language=language)
            
        # Limpiar archivo temporal WAV si se creó
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
    """Crear archivo ZIP para descargar múltiples transcripciones"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for trans in transcriptions:
            filename = trans['filename']
            content = trans['transcription']
            
            # Crear contenido del archivo
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
    
    # Inicializar estado de sesión
    init_session_state()
    
    # Sidebar - Configuración
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        language = st.selectbox(
            "Idioma de reconocimiento:",
            ["es-CL", "es-ES", "en-US", "fr-FR", "de-DE", "it-IT", "pt-BR"]
        )
        
        enable_preprocessing = st.checkbox(
            "Activar preprocesamiento", 
            value=True,
            help="Aplica filtros de audio para mejor reconocimiento"
        )
        
        st.markdown("---")
        st.header("📊 Estadísticas")
        st.write(f"Archivos procesados: {len(st.session_state.processed_files)}")
        st.write(f"Transcripciones guardadas: {len(st.session_state.transcriptions)}")
    
    # Área principal
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("📁 Cargar Archivos de Audio")
        
        uploaded_files = st.file_uploader(
            "Selecciona archivos de audio",
            type=['opus', 'mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac'],
            accept_multiple_files=True,
            help="Formatos soportados: OPUS, MP3, WAV, M4A, AAC, OGG, FLAC"
        )
        
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} archivo(s) cargado(s)")
            
            # Mostrar lista de archivos
            for file in uploaded_files:
                st.write(f"• {file.name} ({file.size / 1024:.1f} KB)")
    
    with col2:
        st.subheader("🎯 Acciones")
        
        if st.button("🚀 Iniciar Transcripción", type="primary", use_container_width=True):
            if not uploaded_files:
                st.error("❌ Por favor, carga al menos un archivo de audio")
            else:
                process_files(uploaded_files, language, enable_preprocessing)
        
        # Botón para descargar todo
        if st.session_state.transcriptions:
            st.download_button(
                label="📥 Descargar Todo (ZIP)",
                data=create_zip_download(st.session_state.transcriptions),
                file_name=f"transcripciones_ecohspeech_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )
        
        if st.button("🗑️ Limpiar Resultados", use_container_width=True):
            st.session_state.transcriptions = []
            st.session_state.processed_files = []
            st.rerun()

def process_files(uploaded_files, language, enable_preprocessing):
    """Procesar archivos cargados"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.container()
    
    with results_container:
        st.subheader("📝 Resultados de Transcripción")
        
        for i, uploaded_file in enumerate(uploaded_files):
            # Actualizar progreso
            progress = (i + 1) / len(uploaded_files)
            progress_bar.progress(progress)
            status_text.text(f"Procesando: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
            
            try:
                # Guardar archivo temporal
                with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    audio_path = tmp_file.name
                
                # Transcribir
                transcription = transcribe_audio(audio_path, language, enable_preprocessing)
                
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
                with st.expander(f"🎵 {uploaded_file.name}", expanded=(i == 0)):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.text_area(
                            "Transcripción:", 
                            transcription, 
                            height=150,
                            key=f"trans_{i}"
                        )
                    
                    with col2:
                        # Descargar individual
                        st.download_button(
                            label="📥 Descargar",
                            data=f"""=== EcohSpeech Transcripción ===
Archivo: {uploaded_file.name}
Idioma: {language}
Fecha: {trans_data['timestamp']}
{"="*40}

{transcription}""",
                            file_name=f"transcripcion_{uploaded_file.name}.txt",
                            mime="text/plain",
                            key=f"dl_{i}"
                        )
                        
                        # Guardar localmente
                        if st.button("💾 Guardar Local", key=f"save_{i}"):
                            local_path = save_transcription_locally(
                                uploaded_file.name, 
                                transcription, 
                                language
                            )
                            st.success(f"Guardado en: {local_path}")
                
                # Limpiar archivo temporal
                os.unlink(audio_path)
                
            except Exception as e:
                st.error(f"❌ Error procesando {uploaded_file.name}: {str(e)}")
        
        # Finalizar
        progress_bar.empty()
        status_text.success(f"✅ Transcripción completada! {len(uploaded_files)} archivo(s) procesado(s)")
        
        # Mostrar resumen
        st.balloons()
        successful = len([t for t in st.session_state.transcriptions if "Error" not in t['transcription']])
        st.info(f"**Resumen:** {successful} exitosas, {len(uploaded_files) - successful} con errores")

if __name__ == "__main__":
    main()