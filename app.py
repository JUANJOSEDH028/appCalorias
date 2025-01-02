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
                        st.set_query_params()  # Limpia los parámetros de la URL
                        st.success("¡Autorización exitosa!")
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

            # Recuperar archivo existente si st.session_state['historial'] está vacío
            filename = f"historial_consumo_{usuario}_actual.csv"
            if 'historial' not in st.session_state or st.session_state.historial.empty:
                service = self.get_drive_service(usuario)
                if service:
                    results = service.files().list(
                        q=f"name='{filename}' and trashed=false",
                        fields="files(id, name)"
                    ).execute()
                    files = results.get('files', [])
                    if files:
                        file_id = files[0]['id']
                        request = service.files().get_media(fileId=file_id)
                        with open(filename, "wb") as f:
                            f.write(request.execute())
                        st.session_state.historial = pd.read_csv(filename)

            # Registrar nuevo alimento
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

            # Backup automático en Drive
            self.upload_to_drive(
                usuario,
                st.session_state.historial.to_csv(index=False),
                filename
            )

            return True

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

def calculate_requirements(gender, age, weight, target_weight, goal):
    """Calcula los requerimientos diarios de calorías y proteínas."""
    if gender == 'Hombre':
        bmr = 10 * weight + 6.25 * 170 - 5 * age + 5  # Altura promedio de 170 cm
    else:
        bmr = 10 * weight + 6.25 * 160 - 5 * age - 161  # Altura promedio de 160 cm

    if goal == 'Déficit calórico':
        calories = bmr - 500
    elif goal == 'Superávit calórico':
        calories = bmr + 500
    else:
        calories = bmr

    protein = weight * 1.6 if weight > target_weight else target_weight * 1.6
    return calories, protein

def calculate_days_to_goal(current_weight, target_weight, daily_caloric_deficit):
    """Calcula los días necesarios para alcanzar el peso ideal."""
    if daily_caloric_deficit <= 0:
        return float('inf')  # No se perderá peso sin déficit calórico
    calories_per_kg = 7700  # Calorías aproximadas en 1 kg de grasa
    total_calories_to_burn = abs(target_weight - current_weight) * calories_per_kg
    return total_calories_to_burn / daily_caloric_deficit

def main():
    st.title("📊 Seguimiento Nutricional")

    if 'tracker' not in st.session_state:
        st.session_state.tracker = NutritionTracker()

    if 'is_authenticated' not in st.session_state:
        st.session_state['is_authenticated'] = False

    # Preguntas iniciales
    st.sidebar.header("👤 Datos Personales")
    gender = st.sidebar.selectbox("Género:", ["Hombre", "Mujer"])
    age = st.sidebar.number_input("Edad (años):", min_value=10, max_value=100, step=1)
    weight = st.sidebar.number_input("Peso actual (kg):", min_value=30.0, max_value=300.0, step=0.1)
    target_weight = st.sidebar.number_input("Peso ideal (kg):", min_value=30.0, max_value=300.0, step=0.1)
    goal = st.sidebar.selectbox("Objetivo:", ["Mantenimiento", "Déficit calórico", "Superávit calórico"])

    calories, protein = calculate_requirements(gender, age, weight, target_weight, goal)

    st.sidebar.markdown(f"### Requerimientos diarios:")
    st.sidebar.markdown(f"- Calorías: {calories:.0f} kcal")
    st.sidebar.markdown(f"- Proteínas: {protein:.1f} g")

    # Calcular días para alcanzar el peso ideal
    if st.sidebar.button("Calcular tiempo para alcanzar el peso ideal"):
        burned_calories = st.number_input("Calorías quemadas hoy (kcal):", min_value=0, step=10)
        daily_deficit = calories - burned_calories
        days_to_goal = calculate_days_to_goal(weight, target_weight, daily_deficit)
        st.sidebar.markdown(f"### Tiempo estimado para alcanzar el peso ideal: {days_to_goal:.1f} días")

    # Menú principal
    st.sidebar.header("🎯 Metas Diarias")
    calorias_meta = st.sidebar.number_input(
        "Meta de calorías (kcal):",
        min_value=1000,
        max_value=5000,
        value=int(calories)
    )

    proteinas_meta = st.sidebar.number_input(
        "Meta de proteínas (g):",
        min_value=30,
        max_value=300,
        value=int(protein)
    )

    menu = st.sidebar.selectbox(
        "📋 Menú:",
        ["Registrar Alimentos", "Resumen Diario", "Cerrar Día"]
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
            if st.session_state.tracker.register_food("usuario", alimento, cantidad):
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

    elif menu == "Cerrar Día":
        st.header("🔒 Cerrar Día")
        if st.button("🔒 Cerrar Día"):
            close_day("usuario")

if __name__ == "__main__":
    main()

