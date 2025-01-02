import streamlit as st
import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime
import os
import json

# Configuración de constantes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

@st.cache_data
def load_food_data():
    """Carga el dataset de alimentos desde una URL."""
    file_path = "https://raw.githubusercontent.com/JUANJOSEDH028/appCalorias/main/alimentos_limpios.csv"
    return pd.read_csv(file_path)

class NutritionTracker:
    def __init__(self):
        """Inicializa el tracker con los datos de alimentos."""
        self.data = load_food_data()

    def get_drive_service(self, usuario):
        """Configura y retorna el servicio de Google Drive."""
        try:
            if not st.session_state.get('is_authenticated', False):
                client_config = {
                    'web': {
                        'client_id': st.secrets["client_secrets"]["web"]["client_id"],
                        'project_id': st.secrets["client_secrets"]["web"]["project_id"],
                        'auth_uri': st.secrets["client_secrets"]["web"]["auth_uri"],
                        'token_uri': st.secrets["client_secrets"]["web"]["token_uri"],
                        'auth_provider_x509_cert_url': st.secrets["client_secrets"]["web"]["auth_provider_x509_cert_url"],
                        'client_secret': st.secrets["client_secrets"]["web"]["client_secret"],
                        'redirect_uris': [st.secrets["client_secrets"]["web"]["redirect_uris"][-1]]
                    }
                }

                flow = Flow.from_client_config(
                    client_config,
                    SCOPES
                )
                flow.redirect_uri = st.secrets["client_secrets"]["web"]["redirect_uris"][-1]

                auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline', include_granted_scopes='true')
                st.markdown(f"[Haz clic aquí para autorizar]({auth_url})")

                code = st.query_params.get('code')
                if code:
                    try:
                        if isinstance(code, list):
                            code = code[0]
                        flow.fetch_token(code=code)
                        st.session_state['token'] = flow.credentials.to_json()
                        st.session_state['is_authenticated'] = True
                        st.success("¡Autorización exitosa!")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Error al procesar el código de autorización: {str(e)}")
                else:
                    st.error("No se recibió un código de autorización válido.")
                return None

            creds = Credentials.from_authorized_user_info(
                json.loads(st.session_state['token']),
                SCOPES
            )
            return build('drive', 'v3', credentials=creds)

        except Exception as e:
            st.error(f"Error en la autenticación: {str(e)}")
            return None

    def upload_to_drive(self, usuario, content, filename):
        """Sube contenido a Google Drive."""
        try:
            service = self.get_drive_service(usuario)
            if not service:
                return False

            with open(filename, 'w') as f:
                f.write(content)

            file_metadata = {'name': filename}
            media = MediaFileUpload(filename, resumable=True)

            results = service.files().list(
                q=f"name='{filename}' and trashed=false",
                fields="files(id)"
            ).execute()
            existing_files = results.get('files', [])

            if existing_files:
                file = service.files().update(
                    fileId=existing_files[0]['id'],
                    body=file_metadata,
                    media_body=media
                ).execute()
            else:
                file = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()

            os.remove(filename)
            return True

        except Exception as e:
            st.error(f"Error al subir archivo: {str(e)}")
            return False

    def register_food(self, usuario, alimento_nombre, cantidad):
        """Registra un alimento consumido."""
        try:
            if self.data.empty:
                st.error("No se han cargado los datos de alimentos")
                return False

            alimento = self.data[self.data["name"] == alimento_nombre].iloc[0]
            valores = alimento[["Calories", "Fat (g)", "Protein (g)", "Carbohydrate (g)"]] * (cantidad / 100)

            nuevo_registro = pd.DataFrame({
                'Fecha y Hora': [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                'Alimento': [alimento["name"]],
                'Cantidad (g)': [cantidad],
                'Calorías': [valores["Calories"]],
                'Grasas (g)': [valores["Fat (g)"]],
                'Proteínas (g)': [valores["Protein (g)"]],
                'Carbohidratos (g)': [valores["Carbohydrate (g)"]]
            })

            if 'historial' not in st.session_state:
                st.session_state.historial = nuevo_registro
            else:
                st.session_state.historial = pd.concat(
                    [st.session_state.historial, nuevo_registro],
                    ignore_index=True
                )

            filename = f"historial_consumo_{usuario}.csv"
            return self.upload_to_drive(
                usuario,
                st.session_state.historial.to_csv(index=False),
                filename
            )

        except Exception as e:
            st.error(f"Error al registrar alimento: {str(e)}")
            return False

    def get_daily_summary(self):
        """Obtiene el resumen diario de nutrición."""
        if 'historial' in st.session_state and not st.session_state.historial.empty:
            return st.session_state.historial[
                ["Calorías", "Grasas (g)", "Proteínas (g)", "Carbohidratos (g)"]
            ].sum()
        return None

def main():
    st.title("📊 Seguimiento Nutricional")

    if 'tracker' not in st.session_state:
        st.session_state.tracker = NutritionTracker()

    if 'is_authenticated' not in st.session_state:
        st.session_state['is_authenticated'] = False

    st.sidebar.header("👤 Usuario")
    usuario = st.sidebar.text_input("Email:", key="user_email")

    if not usuario:
        st.warning("⚠️ Por favor, ingresa tu email para comenzar.")
        return

    if not st.session_state['is_authenticated']:
        st.warning("⚠️ Por favor, autentícate con Google para continuar.")
        st.session_state.tracker.get_drive_service(usuario)
        return

    st.sidebar.header("🎯 Metas Diarias")
    calorias_meta = st.sidebar.number_input(
        "Meta de calorías (kcal):",
        min_value=1000,
        max_value=5000,
        value=2000
    )

    proteinas_meta = st.sidebar.number_input(
        "Meta de proteínas (g):",
        min_value=30,
        max_value=300,
        value=150
    )

    menu = st.sidebar.selectbox(
        "📋 Menú:",
        ["Registrar Alimentos", "Resumen Diario"]
    )

    if menu == "Registrar Alimentos":
        st.header("🍽️ Registro de Alimentos")

        col1, col2 = st.columns(2)
        with col1:
            alimento = st.selectbox(
                "Alimento:",
                st.session_state.tracker.data["name"] if not st.session_state.tracker.data.empty else []
            )
        with col2:
            cantidad = st.number_input("Cantidad (g):", min_value=1.0, step=1.0)

        if st.button("📝 Registrar"):
            if st.session_state.tracker.register_food(usuario, alimento, cantidad):
                st.success("✅ Alimento registrado correctamente")

    elif menu == "Resumen Diario":
        st.header("📈 Resumen del Día")
        resumen = st.session_state.tracker.get_daily_summary()

        if resumen is not None:
            col1, col2 = st.columns(2)

            with col1:
                st.metric(
                    "Calorías",
                    f"{resumen['Calorías']:.1f} kcal",
                    f"{resumen['Calorías'] - calorias_meta:.1f} kcal"
                )

            with col2:
                st.metric(
                    "Proteínas",
                    f"{resumen['Proteínas (g)']:.1f} g",
                    f"{resumen['Proteínas (g)'] - proteinas_meta:.1f} g"
                )

            st.table(resumen)
        else:
            st.info("📝 No hay registros para hoy")

if __name__ == "__main__":
    main()
