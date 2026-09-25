# Home server Debian 13 (trixie) con Ansible

Servidores Debian con roles definidos por grupos del inventario:

- Todos los hosts: hostname y Avahi (mDNS), antes de configurar los roles.
- `container`: Docker Swarm. El primer host es el manager; los demás se unen como
  workers al mismo Swarm. Mantén estable ese orden: no es un mecanismo de failover.
- `storage`: discos existentes unidos en `/mnt/data` con mergerfs, Samba y NFS.

Un servidor puede pertenecer a ambos grupos, como `server1` en el ejemplo.

El manager crea `public-ingress` como una red overlay compartida y persistente
del Swarm. Overlay permite conectar servicios desplegados en distintos nodos y
`attachable` permite conectar también contenedores independientes, además de
servicios del Swarm como `cloudflared`. La red existe fuera de los
stacks, por lo que cada aplicación pública debe declararla como externa:

```yaml
services:
  web:
    image: example/app:latest
    networks:
      - public-ingress

networks:
  public-ingress:
    external: true
```

Una aplicación que no esté conectada a `public-ingress` no será accesible a
través de `cloudflared`. Las redes compartidas se configuran
en `roles/docker_swarm_networks/defaults/main.yml`; el role solo las crea desde
un manager y no inicializa ni modifica la membresía del Swarm.

`cloudflared` se despliega como un servicio del Swarm conectado a
`public-ingress`. Antes de ejecutar Ansible, guarda únicamente el token del
túnel administrado remotamente en un archivo local:

```sh
mkdir -p secrets
chmod 700 secrets
printf '%s' '<CLOUDFLARE_TUNNEL_TOKEN>' > secrets/cloudflared_token
chmod 600 secrets/cloudflared_token
./run.sh --ask-become-pass
```

`secrets/cloudflared_token` está ignorado por Git. Ansible lee el archivo desde
el equipo de administración, guarda su contenido como un Docker secret y monta
el secret en `/run/secrets/cloudflared_token`; el token no se pasa como variable
de entorno ni como argumento visible del servicio. Al cambiar el archivo,
Ansible crea una versión nueva del secret y actualiza `cloudflared`.

El manager ejecuta Jenkins LTS con Java 21 como servicio de Swarm. El bind mount
`/var/lib/jenkins:/var/jenkins_home` conserva el Jenkins home existente y una
restricción `node.hostname` fija el servicio al primer manager, que es el nodo
que puede ver esa ruta. Publica 8080 para la web y 50000 para agentes inbound.
También monta `/var/run/docker.sock` para Jenkins Docker Plugin; ese acceso
equivale a root, así que ejecuta solo jobs confiables y protege Jenkins con
autenticación.

Jenkins se conecta a la red overlay attachable `jenkins-agents`. Configura el
campo **Network** de las plantillas `rsync` y `node` del Docker Plugin con ese
mismo nombre y usa `http://jenkins:8080/` como **Jenkins URL**. Los contenedores
efímeros se conectan entonces al servicio por DNS interno de Swarm; no necesitan
conocer la IP del manager. La red es dedicada y no expone los agentes a los
servicios de `public-ingress`.

En la primera migración, Ansible detecta la versión nativa y usa la imagen
`jenkins/jenkins:<misma-versión>-lts-jdk21` como base. Luego construye y publica
`jenkins-controller:lts-jdk21`, remapeando dentro de la imagen el usuario
`jenkins` al UID/GID existentes. Así Git, SSH y el home conservan la misma
identidad sin cambiar ownership en `/var/lib/jenkins`. Después construye los
agentes, detiene systemd y arranca el container. El paquete nativo queda
instalado pero deshabilitado. Si el nuevo controller no responde, Ansible retira
el servicio fallido y restaura systemd. Después de la migración,
`jenkins_image` controla la imagen base de las actualizaciones.

Obtén la contraseña inicial y revisa el servicio desde la LAN:

```sh
sudo cat /var/lib/jenkins/secrets/initialAdminPassword
sudo docker service ps jenkins
sudo docker service logs jenkins
```

Para volver al servicio nativo durante la ventana inicial, usa una copia
consistente de `/var/lib/jenkins`, retira el servicio Swarm y habilita systemd.
No arranques una versión nativa anterior sobre un home ya actualizado por una
imagen posterior.

También ejecuta `registry:3` como contenedor independiente, escuchando en la IP
LAN configurada en `swarm_advertise_addr`. Las imágenes persisten en
`/srv/docker-registry`, fuera de `/mnt/data`. Ejemplo de build y push desde un
job de Jenkins, usando la IP fija del manager:

```sh
docker build -t <SERVER_LAN_IP>:5000/mi-app:latest .
docker push <SERVER_LAN_IP>:5000/mi-app:latest
```

El registro no usa TLS ni autenticación. Ansible autoriza como registros HTTP
la IP del manager y `<SERVER_HOSTNAME>.local:5000` en Docker del manager. No
expongas el puerto 5000 a Internet. Un equipo cliente adicional debe añadir el
endpoint que use a `insecure-registries` en su propia configuración Docker.
Este diseño cubre el servidor Swarm actual de un nodo; cada futuro worker
también necesitará esa configuración para descargar imágenes.

Verifica el registro:

```sh
curl http://<SERVER_LAN_IP>:5000/v2/
curl http://<SERVER_HOSTNAME>.local:5000/v2/
sudo docker ps --filter name=local-registry
```

## Agentes efímeros de Jenkins

`docker/jenkins-agents/Dockerfile` define dos plantillas para Jenkins Docker
Plugin. El controller
solicita el label `rsync` o `node`, el plugin crea el agente inbound, ejecuta el
pipeline y elimina el contenedor al terminar:

```text
Jenkins Controller -> Docker Plugin -> agente efímero -> pipeline -> eliminado
```

Ambas imágenes usan Jenkins Remoting con JDK 21 como usuario no-root `jenkins`.
Durante el playbook, Ansible copia ese Dockerfile al primer manager, construye
los targets `rsync` y `node` y publica sus tags versionados en el registry local
antes de migrar o actualizar el controller. Solo reconstruye cuando cambia el
Dockerfile, la configuración de build o falta la imagen local.

Incluyen Docker CLI y Buildx para conectarse a un daemon externo; no incluyen ni
ejecutan Docker Engine. No guardes claves SSH, tokens del registry ni otras
credenciales en las imágenes: inyéctalas desde Jenkins durante cada build.

Construye las dos imágenes o un solo target:

```sh
docker buildx bake -f docker/jenkins-agents/docker-bake.hcl
docker buildx bake -f docker/jenkins-agents/docker-bake.hcl rsync
docker buildx bake -f docker/jenkins-agents/docker-bake.hcl node
```

Por defecto se generan `jenkins-agent-rsync:1` y `jenkins-agent-node:24` para
`linux/amd64`. Para ajustar el UID/GID del agente rsync a los archivos montados:

```sh
JENKINS_UID="$(id -u)" JENKINS_GID="$(id -g)" \
  docker buildx bake -f docker/jenkins-agents/docker-bake.hcl rsync
```

Los valores deben ser enteros mayores que cero. Un GID existente se reutiliza;
el build falla si el UID solicitado ya pertenece a otro usuario. Node se descarga
desde `nodejs.org` y se valida con SHA-256. Al cambiar `NODE_VERSION`, actualiza
también `NODE_SHA256`; usa `NODE_TAG` para el tag visible:

```sh
NODE_VERSION=24.21.0 NODE_SHA256=<SHA256> NODE_TAG=24 \
  docker buildx bake -f docker/jenkins-agents/docker-bake.hcl node
```

Publica tags versionados en el registry local, sin una barra final en
`REGISTRY`. `latest` es opcional:

```sh
REGISTRY=<SERVER_LAN_IP>:5000 \
  docker buildx bake -f docker/jenkins-agents/docker-bake.hcl --push
REGISTRY=<SERVER_LAN_IP>:5000 PUBLISH_LATEST=true \
  docker buildx bake -f docker/jenkins-agents/docker-bake.hcl --push
```

Comprueba las imágenes sin iniciar Jenkins Remoting:

```sh
docker run --rm --entrypoint rsync jenkins-agent-rsync:1 --version
docker run --rm --entrypoint ssh jenkins-agent-rsync:1 -V
docker run --rm --entrypoint docker jenkins-agent-rsync:1 --version
docker run --rm --entrypoint id jenkins-agent-rsync:1

docker run --rm --entrypoint node jenkins-agent-node:24 --version
docker run --rm --entrypoint npm jenkins-agent-node:24 --version
docker run --rm --entrypoint git jenkins-agent-node:24 --version
docker run --rm --entrypoint docker jenkins-agent-node:24 --version
```

La configuración posterior de Jenkins Docker Plugin usará estas plantillas; no
está automatizada todavía:

```text
label: rsync   image: <registry>/jenkins-agent-rsync:1
label: node    image: <registry>/jenkins-agent-node:24
```

Samba gestiona únicamente `[data]` desde el fragmento
`playbooks/files/samba/server1/smb.conf`. Adopta el bloque existente o lo agrega
si falta, usando marcadores Ansible para evitar duplicados. Conserva el resto
de `/etc/samba/smb.conf`, incluidos globales, homes e impresoras.
Para otro host de storage, añade su fragmento `[data]` en
`playbooks/files/samba/<nombre-del-inventario>/smb.conf`.
Ansible valida con `testparm` antes de reemplazar el archivo y guarda un backup.
Gestiona `smbd` y `nmbd`; conserva el estado existente de `samba-ad-dc`.
El arranque de `smbd` depende de `/mnt/data`; agregar esa dependencia reinicia
el servicio una vez. Los cambios posteriores de smb.conf recargan los servicios.
No modifica usuarios, contraseñas Samba, propietarios ni ACL de los datos.
En una máquina nueva debes restaurar o crear las cuentas y grupos existentes
(en este caso `nas-user` y `jenkins`) y las credenciales Samba por separado.
Para aplicar solo Samba: `ansible-playbook playbooks/samba.yml --ask-become-pass`.
Docker se instala desde el [repositorio oficial para Debian](https://docs.docker.com/engine/install/debian/),
canal `stable`, suite `trixie`. Cada ejecución instala o actualiza Docker CE,
CLI, containerd, Buildx y Compose a la versión disponible. Los demás paquetes
proceden de Debian. Las actualizaciones pueden reiniciar Docker y sus contenedores.
Se retiran paquetes Docker de Debian incompatibles, sin purga ni autoremove;
no se borran `/var/lib/docker`, `/var/lib/containerd` ni los datos de aplicaciones.
Las entradas antiguas en `docker.list` y `docker.sources` se respaldan al cambiarlas.
Si configuraste el repositorio Docker en otros archivos APT, elimina las entradas
duplicadas o de otra versión de Debian antes de ejecutar.

Si quedó una instalación parcial del intento anterior, ejecuta primero:

```sh
source .venv/bin/activate
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/docker.yml --ask-become-pass
./run.sh --ask-become-pass
```

El playbook independiente usa las mismas tareas de instalación y comprueba
`dpkg --audit`. No fuerza sobrescrituras ni elimina bloqueos de dpkg: si APT no
o dpkg no pueden retirar los paquetes incompatibles, conserva el error para diagnosticarlo
antes de intentar reparaciones manuales. Antes de migrar, guarda una copia o
snapshot consistente de los datos y anota las versiones instaladas. Para volver
atrás, restaura ese snapshot y sus versiones; no hagas downgrade del motor sobre
datos que ya haya actualizado una versión nueva.

En cada servidor necesitas Debian 13, SSH, Python 3 y un usuario con sudo. Reserva una IP
LAN fija para Swarm. No necesitas instalar Ansible en los servidores destino.

En tu equipo de administración usa **Python 3.13** (indicado en `.python-version`),
un cliente SSH y un entorno virtual. `requirements.txt` fija las dependencias de
Python; `requirements.yml` instala las colecciones de Ansible.
Python 3.13 está soportado por [Ansible Core 2.19](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html).

En un equipo de administración Debian 13:

```sh
sudo apt install python3.13 python3.13-venv openssh-client
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n inventory.example.yml inventory.yml
```

Si tu sistema no ofrece Python 3.13 y ya tienes `uv`, puedes crear el entorno con
`uv venv --python 3.13 .venv`, instalar con
`uv pip install --python .venv/bin/python -r requirements.txt` y activarlo con
`source .venv/bin/activate`.
Activa el entorno en cada terminal antes de usar `./run.sh` o las pruebas.
Usa autenticación SSH por clave; comprueba primero `ssh usuario@servidor`.

`inventory.yml` es local y está excluido de Git. Si ya existe, no repitas el
comando `cp`: sobrescribiría tus valores. Reemplaza los placeholders con la IP,
usuario SSH, dirección LAN de Swarm y discos reales. Obtén
los UUID y tipos de filesystem en cada servidor de storage con `lsblk -f`. Los discos deben estar
formateados previamente; estos playbooks no crean particiones ni filesystems.
Usa `/srv/disks/<nombre>` o `/mnt/<nombre>` (por ejemplo `/mnt/disk1`) para cada
disco. `/mnt/data` está reservado para el pool mergerfs, no para discos individuales.
Si ya están montados en otro lugar,
migra primero esos montajes y sus consumidores para evitar entradas duplicadas.
Si aplicaste una versión anterior con el pool en otra ruta, detén sus consumidores
y retira el montaje y su entrada antigua de `/etc/fstab` antes de aplicar este cambio.
El playbook no desmonta automáticamente pools anteriores.

```sh
./run.sh --syntax-check
./run.sh --ask-become-pass
```

El script instala las colecciones de `requirements.yml` (omite las que ya cumplen
la versión requerida), usa el inventario local y acepta argumentos adicionales de Ansible,
por ejemplo `./run.sh --ask-become-pass -e ansible_host=192.168.1.50`.

En todos los hosts, configura `server_hostname` con un nombre corto único,
por ejemplo `server1`. El playbook común configura ese hostname,
su entrada en `/etc/hosts` e instala y habilita Avahi y la resolución mDNS.
Para la primera ejecución usa la IP en `ansible_host`: Avahi todavía no está
configurado. Después puedes cambiarlo a `server1.local`.

Declara conexión y hostname bajo `all.hosts`, y las variables específicas de
cada rol en su grupo, como muestra el inventario. `playbooks/common.yml` también
puede ejecutarse por separado; ejecútalo primero si vas a aplicar los playbooks
de roles individualmente. Avahi permite resolver el nombre del servidor; no
instala NFS ni publica automáticamente recursos compartidos.

El equipo desde el que ejecutas Ansible también debe resolver mDNS (en Debian,
instala `avahi-daemon` y `libnss-mdns`). Comprueba `getent hosts server1.local`
antes de cambiar el inventario. mDNS necesita multicast UDP 5353 en la LAN;
no asumas que funciona entre VLANs o subredes.

`swarm_advertise_addr` sigue siendo una IP LAN fija, incluso si `ansible_host`
es un hostname. [Docker acepta IP o interfaz para advertise-addr](https://docs.docker.com/reference/cli/docker/swarm/init/#specify-interface-for-outbound-control-plane-traffic---advertise-addr),
no nombres DNS. Estos playbooks usan una IP sin puerto porque también la usan
para conectar workers al manager. Avahi no elimina la necesidad de una IP estable
para Swarm. Cambiar esa variable no reconfigura la dirección de un Swarm existente.

Puedes ejecutar `playbooks/storage.yml` por separado. `playbooks/swarm.yml`
requiere que `/mnt/data` ya esté montado solo en hosts que también sean
`storage`; los hosts exclusivamente `container` no necesitan discos mergerfs.
Una lista de discos vacía o un UUID
ausente detiene la configuración. No uses `--check` como simulación completa de
la primera instalación: los paquetes y montajes aún no existen.

Los montajes son obligatorios al arrancar: un disco ausente puede llevar Debian
a modo de emergencia; se prioriza no escribir accidentalmente en el disco del
sistema. Docker espera al pool solo en servidores con ambos roles. Cambiar o
retirar su dependencia de systemd reinicia Docker.
mergerfs agrega capacidad, no proporciona redundancia ni reemplaza un backup.
Eliminar discos del inventario no desmonta ni borra entradas antiguas de fstab:
la retirada de discos requiere migrar sus datos y montajes explícitamente.

Docker conserva imágenes y capas en `/var/lib/docker`, fuera de mergerfs. Las
apps podrán usar bind mounts de `/mnt/data`; conserva bases de datos en un
filesystem local apropiado para la aplicación. No se despliegan aplicaciones
de usuario; `cloudflared`, Jenkins y el registro son servicios base.
No se abre el firewall: mantén los puertos de Swarm dentro de tu red de confianza.

NFS exporta `/mnt/data` con lectura/escritura únicamente a las IPv4
`swarm_advertise_addr` de los hosts `container`. Deben ser las IP de origen
que el storage verá al conectar los nodos. Las reglas se guardan en
`/etc/exports.d/home-server.exports`; no se modifican otros exports existentes.
Si ya había una exportación de `/mnt/data` con otros clientes, retírala para no
ampliar el acceso. Permite TCP 2049 desde esas IPs si tienes firewall.
Se usa NFSv4 (se deshabilita NFSv3 en el servidor), `sync`, `no_root_squash` y un
fsid estable. NFS solo exporta cuando `/mnt/data` es un punto de montaje.
El playbook crea y exporta `/mnt/data/tournament` con UID/GID `1000:1000`, modo
`0770` y `no_root_squash`; puede montarse directamente usando
`device: ":/mnt/data/tournament"`. Solo concede acceso a los hosts `container`
del inventario, pero root remoto conserva privilegios root dentro de ese export.

Para activar NFS sobre el pool existente, primero ejecuta:

```sh
ansible-playbook playbooks/storage.yml --ask-become-pass
```

Después reinicia el servidor storage en una ventana de mantenimiento y ejecuta:

```sh
ansible-playbook playbooks/nfs.yml --ask-become-pass
```

El reinicio aplica `noforget,inodecalc=path-hash`, requeridos para
[exportar mergerfs 2.40 por NFS](https://github.com/trapexit/mergerfs/tree/2.40.2#nfs).
El playbook actualiza fstab sin desmontar un pool en uso. `noforget` aumenta
el consumo de memoria al recordar los archivos visitados. En instalaciones
nuevas las opciones se aplican al primer montaje.

En cada stack, usa un volumen NFS con el driver local de Docker, que lo monta
en el nodo donde se ejecute el servicio; no necesitas bind mounts locales:

```yaml
services:
  app:
    image: <IMAGEN_DE_TU_APP>
    user: "<UID>:<GID>"
    volumes:
      - type: volume
        source: data
        target: /mnt/data
        volume:
          nocopy: true
volumes:
  data:
    driver: local
    driver_opts:
      type: nfs
      o: "addr=<IP_STORAGE>,nfsvers=4,rw,hard"
      device: ":/mnt/data"
```

Sustituye los placeholders antes de desplegar. El ejemplo sigue el
[driver NFS de Docker](https://docs.docker.com/engine/storage/volumes/).
Usa UID/GID numéricos con permisos sobre los datos (consulta `id nas-user` y
`getent group jenkins` en storage); NFS no aplica el `force group` de Samba.
Root remoto conserva privilegios root en ambos exports mediante
`no_root_squash`. La autorización por IP confía en los hosts de la LAN; no
identifica cada container ni cifra el tráfico.
Evita escrituras simultáneas al mismo archivo por Samba, NFS y acceso local.
El storage sigue siendo un punto único de fallo; NFS comparte, no replica.
Comprueba `sudo exportfs -v` en storage y lectura/escritura desde un servicio
con el UID/GID real antes de mover aplicaciones. Los clientes se preparan con
`nfs-common`, pero el playbook no despliega servicios ni monta encima del pool.

Para agregar servidores, decláralos en el grupo correspondiente con sus propias
variables de conexión, IP LAN y, para `storage`, discos. Al agregar workers,
ejecuta incluyendo al manager: el token se obtiene durante esa ejecución y no se
guarda en el inventario ni se muestra en logs. Entre nodos de Swarm permite
2377/TCP, 7946/TCP+UDP y 4789/UDP en la red de confianza.
Un único manager no proporciona alta disponibilidad. mergerfs es local a cada
servidor: no comparte ni replica datos entre nodos. Las apps con bind mounts
necesitarán restricciones de ubicación o almacenamiento compartido al distribuirse.
Quitar un rol no desinstala servicios ni retira nodos de Swarm; esa retirada es manual.

Verificación después de aplicar y después de reiniciar (montaje en hosts
`storage`, listado de nodos en el manager e información Docker en `container`):

```sh
findmnt -t fuse.mergerfs
sudo docker node ls
sudo docker info --format '{{.Swarm.LocalNodeState}}'
sudo docker network ls --filter name=public-ingress
sudo docker network inspect public-ingress --format '{{.Driver}} {{.Attachable}}'
sudo docker network inspect jenkins-agents --format '{{.Driver}} {{.Attachable}}'
sudo docker secret ls --filter name=cloudflared_token
sudo docker service ps cloudflared
sudo docker service ps jenkins
sudo docker service logs --tail 100 jenkins
curl http://<SERVER_LAN_IP>:8080/login
curl http://<SERVER_LAN_IP>:5000/v2/
```

Repite el playbook sin cambiar variables: debe terminar sin cambios. Comprueba
también que cada UUID de `lsblk -f` esté montado en su ruta configurada.

Prueba local de las validaciones del inventario, sin SSH ni cambios al servidor:
`python3 tests/check_config.py` (con Ansible y PyYAML instalados).

Referencias: [mergerfs](https://github.com/trapexit/mergerfs),
[Swarm](https://docs.docker.com/engine/swarm/swarm-mode/) y
[módulo Ansible](https://docs.ansible.com/projects/ansible/latest/collections/community/docker/docker_swarm_module.html).
