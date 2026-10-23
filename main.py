from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Literal
import mysql.connector
import calendar
import os
import secrets
import time
from datetime import date, time as datetime_time, timedelta
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Permitir conexión desde el Frontend (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

required_db_settings = ("DB_HOST", "DB_USER", "DB_NAME")
missing_db_settings = [name for name in required_db_settings if not os.getenv(name)]
if missing_db_settings:
    raise RuntimeError(
        "Faltan variables de entorno para MySQL: " + ", ".join(missing_db_settings)
    )
if os.getenv("APP_ENV") == "production" and not os.getenv("DB_PASSWORD"):
    raise RuntimeError("DB_PASSWORD debe configurarse en producción")

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "user": os.environ["DB_USER"],
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.environ["DB_NAME"],
    "port": int(os.getenv("DB_PORT", "3306")),
}

ACTIVE_SESSIONS = {}
SESSION_TTL_SECONDS = 12 * 60 * 60
PROJECT_DIR = Path(__file__).resolve().parent

app.mount(
    "/img",
    StaticFiles(directory=PROJECT_DIR / "img"),
    name="images",
)

class UserSession(BaseModel):
    documento: str
    nombre: str
    rol: str

def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Exception as e:
        print(f"Error al conectar con MySQL: {e}")
        return None

def get_current_user(authorization: str | None = Header(default=None)) -> UserSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sesión no autenticada")

    token = authorization.removeprefix("Bearer ").strip()
    session = ACTIVE_SESSIONS.get(token)
    if not session or session["expires_at"] <= time.time():
        ACTIVE_SESSIONS.pop(token, None)
        raise HTTPException(status_code=401, detail="La sesión venció; ingrese nuevamente")

    return UserSession(**session["user"])

def require_role(user: UserSession, *roles: str) -> None:
    if user.rol not in roles:
        raise HTTPException(status_code=403, detail="No tiene permiso para esta consulta")

def authorize_student_access(user: UserSession, student_documento: str, cursor) -> None:
    if user.rol == "Estudiante":
        if user.documento != student_documento:
            raise HTTPException(status_code=403, detail="Solo puede consultar sus propios registros")
        return

    if user.rol == "Padre":
        cursor.execute(
            """
            SELECT 1
            FROM padres_estudiantes pe
            JOIN usuarios u ON u.id = pe.padre_id
            JOIN estudiantes e ON e.id = pe.estudiante_id
            WHERE u.documento = %s AND e.documento = %s
            """,
            (user.documento, student_documento),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=403, detail="No tiene acceso al resumen de este estudiante")
        return

    require_role(user, "Coordinador", "Docente")

def invalidate_user_sessions(documento: str) -> None:
    tokens = [
        token for token, session in ACTIVE_SESSIONS.items()
        if session["user"]["documento"] == documento
    ]
    for token in tokens:
        ACTIVE_SESSIONS.pop(token, None)

def replace_parent_student_links(cursor, parent_id: int, student_documents: list[str]) -> None:
    unique_documents = list(dict.fromkeys(document.strip() for document in student_documents if document.strip()))
    if unique_documents:
        placeholders = ", ".join(["%s"] * len(unique_documents))
        cursor.execute(
            f"SELECT documento FROM estudiantes WHERE documento IN ({placeholders})",
            tuple(unique_documents),
        )
        found_documents = {row["documento"] for row in cursor.fetchall()}
        missing_documents = set(unique_documents) - found_documents
        if missing_documents:
            raise HTTPException(status_code=422, detail="Uno o más estudiantes vinculados no existen")

    cursor.execute("DELETE FROM padres_estudiantes WHERE padre_id = %s", (parent_id,))
    if unique_documents:
        placeholders = ", ".join(["%s"] * len(unique_documents))
        cursor.execute(
            f"""
            INSERT INTO padres_estudiantes (padre_id, estudiante_id)
            SELECT %s, id FROM estudiantes WHERE documento IN ({placeholders})
            """,
            (parent_id, *unique_documents),
        )

class LoginSchema(BaseModel):
    role: str
    username: str
    password: str

class RegistroTardeSchema(BaseModel):
    estudiante_documento: str
    justificacion: str
    motivo: str

class ActualizarRegistroTardeSchema(BaseModel):
    estudiante_documento: str
    fecha: date
    hora: datetime_time
    justificacion: str
    motivo: str

class CrearEstudianteSchema(BaseModel):
    documento: str
    nombre: str
    grado: str

class CrearUsuarioSchema(BaseModel):
    documento: str
    nombre: str
    rol: Literal["Coordinador", "Docente", "Estudiante", "Padre"]
    password: str | None = None
    grado: str | None = None
    estudiantes_documentos: list[str] = Field(default_factory=list)

class ActualizarUsuarioSchema(BaseModel):
    nombre: str
    rol: Literal["Coordinador", "Docente", "Estudiante", "Padre"]
    password: str | None = None
    grado: str | None = None
    estudiantes_documentos: list[str] = Field(default_factory=list)

class CambiarContrasenaSchema(BaseModel):
    contrasena_actual: str
    contrasena_nueva: str

@app.get("/")
def home():
    return FileResponse(PROJECT_DIR / "Frontend.html")

@app.get("/health")
def health():
    return {"mensaje": "API S.R.A.T funcionando correctamente"}

@app.post("/api/login")
def login(data: LoginSchema):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM usuarios WHERE documento = %s AND password = %s AND rol = %s", 
            (data.username, data.password, data.role)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user:
            raise HTTPException(status_code=401, detail="Credenciales incorrectas o rol no coincide")

        token = secrets.token_urlsafe(32)
        session_user = {"nombre": user["nombre"], "rol": user["rol"], "documento": user["documento"]}
        ACTIVE_SESSIONS[token] = {"user": session_user, "expires_at": time.time() + SESSION_TTL_SECONDS}
        
        return {
            "mensaje": "Inicio de sesión exitoso",
            "usuario": session_user,
            "token": token,
        }
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {e}")

@app.get("/api/estudiantes")
def obtener_estudiantes(user: UserSession = Depends(get_current_user)):
    require_role(user, "Coordinador", "Docente")
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT documento, nombre, grado FROM estudiantes ORDER BY nombre ASC")
        estudiantes = cursor.fetchall()
        cursor.close()
        conn.close()
        return estudiantes
    except Exception as e:
        print(f"Error al obtener estudiantes: {e}")
        if conn:
            conn.close()
        return []

@app.post("/api/estudiantes", status_code=201)
def crear_estudiante(
    data: CrearEstudianteSchema,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Coordinador")
    documento = data.documento.strip()
    nombre = data.nombre.strip()
    grado = data.grado.strip()
    if not documento or not nombre or not grado:
        raise HTTPException(status_code=422, detail="Documento, nombre y grado son obligatorios")
    if len(documento) > 20 or len(nombre) > 100 or len(grado) > 20:
        raise HTTPException(status_code=422, detail="Uno o más campos exceden la longitud permitida")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO estudiantes (documento, nombre, grado) VALUES (%s, %s, %s)",
            (documento, nombre, grado),
        )
        cursor.execute(
            "INSERT INTO usuarios (documento, nombre, password, rol) VALUES (%s, %s, %s, %s)",
            (documento, nombre, documento, "Estudiante"),
        )
        conn.commit()
        return {
            "status": "ok",
            "mensaje": "Estudiante creado. Su contraseña inicial es su número de documento.",
        }
    except mysql.connector.IntegrityError as e:
        conn.rollback()
        if e.errno == 1062:
            raise HTTPException(status_code=409, detail="Ya existe un usuario o estudiante con ese documento")
        raise HTTPException(status_code=500, detail=f"Error al crear el estudiante: {e}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear el estudiante: {e}")
    finally:
        cursor.close()
        conn.close()

@app.get("/api/usuarios")
def obtener_usuarios(user: UserSession = Depends(get_current_user)):
    require_role(user, "Coordinador")
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT u.documento, u.nombre, u.rol, e.grado
            FROM usuarios u
            LEFT JOIN estudiantes e ON e.documento = u.documento
            ORDER BY u.rol, u.nombre
            """
        )
        usuarios = cursor.fetchall()
        cursor.execute(
            """
            SELECT u.documento AS padre_documento, e.documento AS estudiante_documento
            FROM padres_estudiantes pe
            JOIN usuarios u ON u.id = pe.padre_id
            JOIN estudiantes e ON e.id = pe.estudiante_id
            """
        )
        vinculos = {}
        for vinculo in cursor.fetchall():
            vinculos.setdefault(vinculo["padre_documento"], []).append(vinculo["estudiante_documento"])

        for cuenta in usuarios:
            cuenta["estudiantes_documentos"] = vinculos.get(cuenta["documento"], [])
        return usuarios
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar los usuarios: {e}")
    finally:
        cursor.close()
        conn.close()

@app.post("/api/usuarios", status_code=201)
def crear_usuario(data: CrearUsuarioSchema, user: UserSession = Depends(get_current_user)):
    require_role(user, "Coordinador")
    documento = data.documento.strip()
    nombre = data.nombre.strip()
    grado = (data.grado or "").strip()
    password = data.password or (documento if data.rol == "Estudiante" else "")

    if not documento or not nombre:
        raise HTTPException(status_code=422, detail="Documento y nombre son obligatorios")
    if len(documento) > 20 or len(nombre) > 100:
        raise HTTPException(status_code=422, detail="Documento o nombre excede la longitud permitida")
    if len(password) < 8:
        raise HTTPException(
            status_code=422,
            detail="La contraseña debe tener al menos 8 caracteres; para estudiantes se usa el documento si se deja vacía",
        )
    if data.rol == "Estudiante" and (not grado or len(grado) > 20):
        raise HTTPException(status_code=422, detail="El grado es obligatorio y no debe exceder 20 caracteres")
    if data.rol == "Padre" and not data.estudiantes_documentos:
        raise HTTPException(status_code=422, detail="Vincule al menos un estudiante a la cuenta Padre")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM usuarios WHERE documento = %s", (documento,))
        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="Ya existe un usuario con ese documento")

        if data.rol == "Estudiante":
            cursor.execute("SELECT id FROM estudiantes WHERE documento = %s", (documento,))
            estudiante = cursor.fetchone()
            if estudiante:
                cursor.execute(
                    "UPDATE estudiantes SET nombre = %s, grado = %s WHERE documento = %s",
                    (nombre, grado, documento),
                )
            else:
                cursor.execute(
                    "INSERT INTO estudiantes (documento, nombre, grado) VALUES (%s, %s, %s)",
                    (documento, nombre, grado),
                )

        cursor.execute(
            "INSERT INTO usuarios (documento, nombre, password, rol) VALUES (%s, %s, %s, %s)",
            (documento, nombre, password, data.rol),
        )
        user_id = cursor.lastrowid

        if data.rol == "Padre":
            replace_parent_student_links(cursor, user_id, data.estudiantes_documentos)

        conn.commit()
        return {
            "status": "ok",
            "mensaje": (
                "Usuario creado. La contraseña inicial del estudiante es su documento."
                if data.rol == "Estudiante" and not data.password
                else "Usuario creado correctamente."
            ),
        }
    except HTTPException:
        conn.rollback()
        raise
    except mysql.connector.IntegrityError as e:
        conn.rollback()
        if e.errno == 1062:
            raise HTTPException(status_code=409, detail="Ya existe una cuenta o estudiante con ese documento")
        raise HTTPException(status_code=500, detail=f"Error al crear el usuario: {e}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear el usuario: {e}")
    finally:
        cursor.close()
        conn.close()

@app.put("/api/usuarios/{documento}")
def actualizar_usuario(
    documento: str,
    data: ActualizarUsuarioSchema,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Coordinador")
    nombre = data.nombre.strip()
    grado = (data.grado or "").strip()
    if not nombre or len(nombre) > 100:
        raise HTTPException(status_code=422, detail="El nombre es obligatorio y no debe exceder 100 caracteres")
    if data.password is not None and data.password and len(data.password) < 8:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 8 caracteres")
    if data.rol == "Estudiante" and (not grado or len(grado) > 20):
        raise HTTPException(status_code=422, detail="El grado es obligatorio y no debe exceder 20 caracteres")
    if data.rol == "Padre" and not data.estudiantes_documentos:
        raise HTTPException(status_code=422, detail="Vincule al menos un estudiante a la cuenta Padre")
    if documento == user.documento and data.rol != "Coordinador":
        raise HTTPException(status_code=409, detail="No puede cambiar su propia cuenta fuera del rol Coordinador")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, rol FROM usuarios WHERE documento = %s", (documento,))
        cuenta = cursor.fetchone()
        if not cuenta:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if cuenta["rol"] == "Coordinador" and data.rol != "Coordinador":
            cursor.execute("SELECT COUNT(*) AS total FROM usuarios WHERE rol = 'Coordinador'")
            if cursor.fetchone()["total"] <= 1:
                raise HTTPException(status_code=409, detail="Debe existir al menos una cuenta Coordinador")

        if data.password:
            cursor.execute(
                "UPDATE usuarios SET nombre = %s, rol = %s, password = %s WHERE documento = %s",
                (nombre, data.rol, data.password, documento),
            )
        else:
            cursor.execute(
                "UPDATE usuarios SET nombre = %s, rol = %s WHERE documento = %s",
                (nombre, data.rol, documento),
            )

        if data.rol == "Estudiante":
            cursor.execute("SELECT id FROM estudiantes WHERE documento = %s", (documento,))
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE estudiantes SET nombre = %s, grado = %s WHERE documento = %s",
                    (nombre, grado, documento),
                )
            else:
                cursor.execute(
                    "INSERT INTO estudiantes (documento, nombre, grado) VALUES (%s, %s, %s)",
                    (documento, nombre, grado),
                )

        if data.rol == "Padre":
            replace_parent_student_links(cursor, cuenta["id"], data.estudiantes_documentos)
        else:
            cursor.execute("DELETE FROM padres_estudiantes WHERE padre_id = %s", (cuenta["id"],))

        conn.commit()
        if documento == user.documento:
            for session in ACTIVE_SESSIONS.values():
                if session["user"]["documento"] == documento:
                    session["user"]["nombre"] = nombre
                    session["user"]["rol"] = data.rol
        else:
            invalidate_user_sessions(documento)
        return {"status": "ok", "mensaje": "Usuario actualizado correctamente"}
    except HTTPException:
        conn.rollback()
        raise
    except mysql.connector.IntegrityError as e:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"No se pudo actualizar el usuario: {e}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar el usuario: {e}")
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/usuarios/{documento}")
def eliminar_usuario(documento: str, user: UserSession = Depends(get_current_user)):
    require_role(user, "Coordinador")
    if documento == user.documento:
        raise HTTPException(status_code=409, detail="No puede eliminar su propia cuenta")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, rol FROM usuarios WHERE documento = %s", (documento,))
        cuenta = cursor.fetchone()
        if not cuenta:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if cuenta["rol"] == "Coordinador":
            cursor.execute("SELECT COUNT(*) AS total FROM usuarios WHERE rol = 'Coordinador'")
            if cursor.fetchone()["total"] <= 1:
                raise HTTPException(status_code=409, detail="No puede eliminar la última cuenta Coordinador")

        cursor.execute("DELETE FROM padres_estudiantes WHERE padre_id = %s", (cuenta["id"],))
        cursor.execute("DELETE FROM usuarios WHERE id = %s", (cuenta["id"],))
        conn.commit()
        invalidate_user_sessions(documento)
        return {
            "status": "ok",
            "mensaje": (
                "Cuenta eliminada. El perfil y los registros académicos del estudiante se conservaron."
                if cuenta["rol"] == "Estudiante"
                else "Usuario eliminado correctamente."
            ),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar el usuario: {e}")
    finally:
        cursor.close()
        conn.close()

@app.post("/api/mi-contrasena")
def cambiar_contrasena_docente(
    data: CambiarContrasenaSchema,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Docente")
    if len(data.contrasena_nueva) < 8:
        raise HTTPException(status_code=422, detail="La contraseña nueva debe tener al menos 8 caracteres")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE usuarios SET password = %s WHERE documento = %s AND password = %s AND rol = %s",
            (data.contrasena_nueva, user.documento, data.contrasena_actual, "Docente"),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=400, detail="La contraseña actual no coincide")
        conn.commit()
        return {"status": "ok", "mensaje": "Contraseña actualizada correctamente"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al cambiar la contraseña: {e}")
    finally:
        cursor.close()
        conn.close()

@app.get("/api/padres/estudiantes")
def obtener_estudiantes_para_padres(user: UserSession = Depends(get_current_user)):
    require_role(user, "Padre")
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT e.documento, e.nombre, e.grado
            FROM padres_estudiantes pe
            JOIN usuarios u ON u.id = pe.padre_id
            JOIN estudiantes e ON e.id = pe.estudiante_id
            WHERE u.documento = %s
            ORDER BY e.grado, e.nombre
            """,
            (user.documento,),
        )
        estudiantes = cursor.fetchall()
        cursor.close()
        conn.close()
        return estudiantes
    except Exception as e:
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error al cargar estudiantes: {e}")

@app.post("/api/registro-tarde")
def registrar_tarde(data: RegistroTardeSchema, user: UserSession = Depends(get_current_user)):
    require_role(user, "Coordinador", "Docente")
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Sin conexión a la base de datos")
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM estudiantes WHERE documento = %s", (data.estudiante_documento,))
        est = cursor.fetchone()
        
        if not est:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Estudiante no encontrado")
            
        cursor.execute(
            """
            INSERT INTO llegadas_tardes (
                estudiante_id, trae_justificacion, motivo, registrado_por, registrado_por_rol
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (est["id"], data.justificacion, data.motivo, user.nombre, user.rol)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return {"status": "ok", "mensaje": "Registro completado con éxito"}
    except HTTPException:
        if conn:
            conn.close()
        raise
    except Exception as e:
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error al guardar registro: {e}")

@app.put("/api/registro-tarde/{registro_id}")
def actualizar_registro_tarde(
    registro_id: int,
    data: ActualizarRegistroTardeSchema,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Coordinador")
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM estudiantes WHERE documento = %s", (data.estudiante_documento,))
        estudiante = cursor.fetchone()
        if not estudiante:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado")

        cursor.execute(
            """
            UPDATE llegadas_tardes
            SET estudiante_id = %s, fecha = %s, hora = %s,
                trae_justificacion = %s, motivo = %s
            WHERE id = %s
            """,
            (
                estudiante["id"], data.fecha, data.hora, data.justificacion,
                data.motivo, registro_id,
            ),
        )
        if cursor.rowcount == 0:
            cursor.execute("SELECT id FROM llegadas_tardes WHERE id = %s", (registro_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Registro no encontrado")

        conn.commit()
        return {"status": "ok", "mensaje": "Registro actualizado"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar el registro: {e}")
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/registro-tarde/{registro_id}")
def eliminar_registro_tarde(
    registro_id: int,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Coordinador")
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Sin conexión a la base de datos")

    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM llegadas_tardes WHERE id = %s", (registro_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        conn.commit()
        return {"status": "ok", "mensaje": "Registro eliminado"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar el registro: {e}")
    finally:
        cursor.close()
        conn.close()

@app.get("/api/reporte-llegadas")
def obtener_reporte(
    estudiante_documento: str | None = None,
    user: UserSession = Depends(get_current_user),
):
    require_role(user, "Coordinador", "Docente")

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
                 SELECT l.id, e.documento AS estudiante_documento, e.nombre, e.grado,
                     DATE_FORMAT(l.fecha, '%Y-%m-%d') as fecha,
                     TIME_FORMAT(l.hora, '%h:%i %p') as hora,
                     TIME_FORMAT(l.hora, '%H:%i') as hora_editable,
                   l.trae_justificacion, l.motivo,
                   l.registrado_por, l.registrado_por_rol
            FROM llegadas_tardes l
            JOIN estudiantes e ON l.estudiante_id = e.id
        """

        if estudiante_documento:
            query += " WHERE e.documento = %s ORDER BY l.fecha DESC, l.hora DESC"
            cursor.execute(query, (estudiante_documento,))
        else:
            query += " ORDER BY e.grado ASC, l.fecha DESC, l.hora DESC"
            cursor.execute(query)

        reporte = cursor.fetchall()
        cursor.close()
        conn.close()
        return reporte
    except HTTPException:
        cursor.close()
        conn.close()
        raise
    except Exception as e:
        print(f"Error al obtener reporte: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Error al cargar el reporte: {e}")

@app.get("/api/estudiantes/{estudiante_documento}/resumen")
def obtener_resumen_estudiante(
    estudiante_documento: str,
    user: UserSession = Depends(get_current_user),
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="No hay conexión con la base de datos")

    cursor = conn.cursor(dictionary=True)
    try:
        authorize_student_access(user, estudiante_documento, cursor)
        cursor.execute(
            """
            SELECT l.fecha
            FROM llegadas_tardes l
            JOIN estudiantes e ON e.id = l.estudiante_id
            WHERE e.documento = %s AND l.fecha IS NOT NULL
            ORDER BY l.fecha
            """,
            (estudiante_documento,),
        )
        fechas = [fila["fecha"] for fila in cursor.fetchall()]
        hoy = date.today()

        periodo_actual = (hoy.month - 1) // 3
        periodos = []
        for indice in range(periodo_actual + 1):
            inicio_mes = indice * 3 + 1
            inicio = date(hoy.year, inicio_mes, 1)
            fin = date(hoy.year, inicio_mes + 2, calendar.monthrange(hoy.year, inicio_mes + 2)[1])
            periodos.append({
                "nombre": f"Periodo {indice + 1}",
                "inicio": inicio.isoformat(),
                "fin": fin.isoformat(),
                "actual": indice == periodo_actual,
                "llegadas": sum(inicio <= fecha <= min(fin, hoy) for fecha in fechas),
            })

        inicio_mes_actual = date(hoy.year, hoy.month, 1)
        meses = []
        for desplazamiento in range(5, -1, -1):
            mes_indice = hoy.year * 12 + hoy.month - 1 - desplazamiento
            anio, mes_cero = divmod(mes_indice, 12)
            inicio = date(anio, mes_cero + 1, 1)
            siguiente_mes = date(anio + (mes_cero + 1 == 12), (mes_cero + 1) % 12 + 1, 1)
            fin = siguiente_mes - timedelta(days=1)
            meses.append({
                "nombre": inicio.strftime("%Y-%m"),
                "llegadas": sum(inicio <= fecha <= min(fin, hoy) for fecha in fechas),
            })

        lunes_actual = hoy - timedelta(days=hoy.weekday())
        semanas = []
        for desplazamiento in range(7, -1, -1):
            inicio = lunes_actual - timedelta(weeks=desplazamiento)
            fin = inicio + timedelta(days=6)
            semanas.append({
                "inicio": inicio.isoformat(),
                "fin": min(fin, hoy).isoformat(),
                "actual": desplazamiento == 0,
                "llegadas": sum(inicio <= fecha <= min(fin, hoy) for fecha in fechas),
            })

        return {
            "periodos": periodos,
            "meses": meses,
            "semanas": semanas,
            "total_periodo_actual": periodos[-1]["llegadas"],
            "total_mes_actual": sum(inicio_mes_actual <= fecha <= hoy for fecha in fechas),
            "total_semana_actual": semanas[-1]["llegadas"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al calcular el resumen: {e}")
    finally:
        cursor.close()
        conn.close()

@app.post("/api/logout")
def logout(
    authorization: str = Header(default=""),
    user: UserSession = Depends(get_current_user),
):
    token = authorization.removeprefix("Bearer ").strip()
    session = ACTIVE_SESSIONS.get(token)
    if session and session["user"]["documento"] == user.documento:
        ACTIVE_SESSIONS.pop(token, None)
    return {"status": "ok"}