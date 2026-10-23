# SRAT

Aplicación FastAPI para el sistema SRAT. FastAPI sirve la interfaz en `/`, la API
en `/api` y las imágenes en `/img`, por lo que producción usa un solo dominio.

## Ejecución local

`Iniciar SRAT.bat` configura los valores locales predeterminados de MySQL y
arranca el servidor. Para otros entornos, define `DB_HOST`, `DB_USER`,
`DB_PASSWORD`, `DB_NAME` y, opcionalmente, `DB_PORT` antes de iniciar Uvicorn.

## EasyPanel

Crear el servicio de aplicación desde este repositorio usando el `Dockerfile`,
asignarle las variables `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` y
`DB_PORT` del servicio MySQL, y configurar el dominio para que apunte al puerto
`8000` del contenedor. El esquema inicial está en `database/schema.sql`; debe
aplicarse a la base de datos antes de habilitar el servicio.

El volcado local con datos y archivos de trabajo privados no forman parte del
repositorio ni de la imagen de producción.
