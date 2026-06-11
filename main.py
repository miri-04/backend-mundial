import sqlite3
import requests 
import logging
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware;
from apscheduler.schedulers.background import BackgroundScheduler

#CONFIGURACION DE REGISTROS 
#SE CREA UN ARCHIVO LLAMADO 'HISTORIAL_ROBOT.LOG' PARA REVISAR SI EL ROBOT TRABAJO CORRECTAMENTE 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers= [
        logging.FileHandler("historial_robot.log", encoding="utf-8"),
        logging.StreamHandler() #MOSTRARA LOS MENSAJES EN LA TERMINAL NEGRA
    ]
)
 
#CREANDO EL SERVIDOR WEB (FASTAPI)
app = FastAPI(title="Backen Mundial 2026")

#PERMITIR QUE LA INTERFAZ WEB (FRONTEND) PUEDA COMUNICARSE CON FLUIDES CON EL BACKEND
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "mundial.db"

#FUNCION QUE CREARA LA BASE DE DATOS Y LA TABLA 
def inicializar_base_de_datos():
    #CONEXION A LA BASE DE DATOS PERO SI NO EXISTE SQLITE LO CREARA AUTOMATICAMENTE
    conexion = sqlite3.connect(DB_NAME)
    cursor = conexion.cursor()
    
 #SCRIP PARA CREAR LA TABLA DE PARTIDOS 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS partidos (
                   id TEXT PRIMARY KEY,
                   fase TEXT,
                   fecha_utc TEXT,
                   hora_utc TEXT,
                   estadio TEXT,
                   ciudad TEXT,
                   equipo_local TEXT,
                   equipo_visitante TEXT,
                   goles_local INTEGER,
                   goles_visitante INTEGER
                   
                   )

        """)
    conexion.commit()
    conexion.close()


#ESTE ES EL ROBOT QUE CONSULTARA INTERNET Y REALIZARA UN "UPSERT"
def conectar_api_y_actualizar():
    logging.info("🤖 El robot esta activado. Conectando a la API deportiva...")

    #ENLACE A LA API GRATIUTA CON LOS DATOS D ELA COPA DEL MUNDO 
    url_api = "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?id=4429"

    try:
        #INTENTAMOS CONECTAR CON INTERNET 
        respuesta = requests.get(url_api, timeout=10)

        #REINTENTOS DE CONEXION POR SI EL SERVIDOR DE INTERNET NO RESPONDE, SE LANZA UN ERROR 
        if respuesta.status_code != 200:
            logging.error(f"❌ La API tiene un error de codigo: {respuesta.status_code}")
            return
        
        datos = respuesta.json()
        partidos_internet = datos.get("events", [])

        if not partidos_internet:
            logging.warning("⚠️ La API no devolvio partidos para este torneo.")
            return
        
        #CONEXION A LA BASE DE DATOS PARA GUARDAR LO QUE SE ENCONTRO 
        conexion = sqlite3.connect(DB_NAME)
        cursor = conexion.cursor()

        contador_actualizados = 0

        for evento in partidos_internet:
            #SE HACE ESTRACCION Y LIMPIEZA DE LOS DATOS OBTENIDOS DE INTERNET

            id_partido = str(evento.get("idEvent"))
            fase = evento.get("strRound", "Fase de Grupos")
            fecha = evento.get("dateEvent", "Por definir")
            hora = evento.get("strTime", "00:00:00")[:5] #SE CORTA PARA SOLO TENER HORAS Y MINUTOS
            estadio = evento.get("strVenue", "Por definir")
            ciudad = evento.get("strCountry", "Por definir")
            local = evento.get("strHomeTeam", "Por definir")
            visitante = evento.get("strAwayTeam", "Por definir")

            #GOLES PUEDEN SER NUMEROS O ESTAR VACIO SI NO HAN JUGADO 
            goles_l = evento.get("intHomeScore")
            goles_v = evento.get("intAwayScore")

            #ACCION UPSERT SI YA EXISTE EL ID_PARTIDO SE INSERTA Y ACTUALIZA
            cursor.execute("""
                INSERT INTO partidos (id, fase, fecha_utc, hora_utc, estadio, ciudad, equipo_local, equipo_visitante, goles_local, goles_visitante)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)    
                ON CONFLICT (id) DO UPDATE SET
                    fase = excluded.fase,
                    fecha_utc = excluded.fecha_utc,
                    hora_utc = excluded.hora_utc,
                    estadio = excluded.estadio,
                    ciudad = excluded.ciudad,
                    equipo_local = excluded.equipo_local,
                    equipo_visitante = excluded.equipo_visitante,
                    goles_local = excluded.goles_local,
                    goles_visitante =excluded.goles_visitante                          
            """, (id_partido, fase, fecha, hora, estadio, ciudad, local, visitante, goles_l, goles_v))
            
            contador_actualizados +=1
        
        conexion.commit()
        conexion.close()
        logging.info(f"✅ Exito! El robot a procesado y actualizado {contador_actualizados} partidos en la base de datos. ")
    
    except requests.exceptions.RequestException as e:
        #SI EL SERVIDOR SE CAE O NO TIENE INTERNER, EL ROBOT REGISTRARA EL ERROR Y NO ROMPE LA APP
        logging.error(f"❌ Error de conexion al intertar actualizar: {e}")


#EL RELOJ (SCHEDULER)
#ESTE COMPONENTE SE ENCARGARA DE ACTIVAR AL ROBOT DE MANERA AUTOMATICA CADA 12HR
scheduler = BackgroundScheduler()

#SE LE INDICA AL RELOJ LA TAREA, EL TIEMPO Y CUANDO INICIAR 
scheduler.add_job(conectar_api_y_actualizar, 'interval', hours=12)

#INICIAMOS EL RELOJ DE FONDO
scheduler.start()

#INICIMOS LA BASE DE DATOS VACIA AL INICIAR EL ARRANQUE 
inicializar_base_de_datos()

#FORZAMOS EL ARRANQUE DEL ROBOT UNA VEZ INICIADO EL SERVIDOR PARA EVITAR LA ESPERA DE 12HR
conectar_api_y_actualizar()

#ENDPOINT: VENTANILLAS DE SERVICIO DEL SERVIDOR TODOS SON METODOS DE DONDE SE OBTENDRA INFORMACION 
@app.get("/estado")
def inicio():
    return {"mensaje": "¡El servidor para el mundial este encendido y funcionando! ⚽"}

@app.get("/partidos")
def obtener_todos_los_partidos():
    """Ventanilla que entrega la lista completa de partidos guardados en la base de datos"""
    conexion = sqlite3.connect(DB_NAME)
    #CAMBIO DE FORMATO PARA QUE DEVUELVA LOS DATOS COMO UN DICCIONARIO MAS FACIL DE LEER 
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()
    cursor.execute("SELECT * FROM partidos ORDER BY fecha_utc ASC, hora_utc ASC")
    #CONVERTIMOS LOS RENGLONES DE LA BASE DE DATOS EN UNA LISTA COMUN DE PYTHON
    resultados = [dict(fila) for fila in cursor.fetchall()]
    conexion.close()
    return resultados

@app.get("/partidos/equipo/{nombre_equipo}")
def obtener_partidos_por_equipo(nombre_equipo: str):
    """Ventanilla que filtrara y entregara solo los partidos de un equipo en particular"""
    conexion = sqlite3.connect(DB_NAME)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()

    #BUSCARA LOS PARTIDOS DONDE EL EQUIPO SEA LOCAL O VISITANTE 
    #USAMOS '%NOMBRE%' PARA QUE ENCUENTRE COINCIDENCIAS DENTRO DE LA BASE DE DATOS AUNQUE EL USUARIO ESCRIBIERA CON MINUSCULAS
    cursor.execute("""
       SELECT * FROM partidos 
       WHERE equipo_local LIKE ? OR equipo_visitante LIKE ?
       ORDER BY fecha_utc ASC 
    """, (f"%{nombre_equipo}%", f"%{nombre_equipo}%"))
    resultado = [dict(fila) for fila in cursor.fetchall()]
    conexion.close()
    return resultado

app.mount("/", StaticFiles(directory=".", html=True), name="static")