# ADR 0028: Excepción explícita de importación para Docker local

Estado: aceptado para desarrollo en una máquina de confianza; no para servidores compartidos.

El proxy Next.js conecta desde otro contenedor: publicar un puerto del host en
loopback no convierte ese peer en loopback. Conservamos las dos condiciones
`FAMA_ENV=development` y `FAMA_IMPORT_DEV_MODE=1`, y extendemos la excepción únicamente
a una IP de frontend exacta configurada por el operador, no a rangos privados ni a
`X-Forwarded-For`. El overlay explícito `docker-compose.dev.yml` fija ese peer en una
red dedicada, desactiva cabeceras de proxy en Uvicorn y reemplaza los puertos para
publicar solo `127.0.0.1:3000`. `./iniciar_fama.sh --dev --build` lo selecciona;
el arranque normal no habilita la excepción.

Preferimos una IP estática a confiar en toda la red o en resolución DNS dinámica.
El coste es mantener coordinadas IP, subred y guarda. Una IP no acredita identidad
criptográfica: quien controla Docker, la máquina o el acceso al frontend puede usar
el modo local. No sustituye autenticación en redes compartidas.
Se conserva el propietario aislado `-1`, los filtros privados y la validación Bearer
sin alternativa anónima para credenciales inválidas. La base y archivos de desarrollo
se separan de los normales; el retorno explícito recrea todos los servicios sin
borrar datos. Véase el [procedimiento operativo](../manuales/importacion-datasets-zip.md).
