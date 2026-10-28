# Despliegue en una máquina virtual de Azure (Azure CLI, Cloudflare y GitHub Actions)

Esta guía despliega la misma aplicación (Django + gunicorn + nginx + PostgreSQL, todo con `docker compose`) en una **máquina virtual (VM) de Azure**. Está escrita para quien ya conoce el despliegue en AWS de este repositorio ([`despliegue-ec2.md`](despliegue-ec2.md)) y casi no conoce Azure: cada concepto nuevo se explica comparándolo con su equivalente en AWS.

> Fecha de verificación de datos de Azure: **2026-10-27** (documentación en learn.microsoft.com, página de servicios gratuitos, API pública de precios minoristas y repositorios oficiales). Lo que no se pudo verificar está marcado como **"verificar en ..."**. Azure cambia nombres, precios y cuotas con frecuencia: ante una diferencia, manda la documentación oficial.

## Ruta rápida

1. **Antes de empezar**: la imagen debe estar publicada en GHCR y el paquete `proyectoweb` debe ser **público** (igual que en AWS; la VM no compila imágenes, solo las descarga).
2. Instalar y autenticar la CLI: `brew install azure-cli && az login` (sección 3).
3. Definir las variables y ejecutar los comandos de la sección 4 (grupo de recursos, red, NSG, IP estática) y la sección 5 (VM con `cloud-init.yaml`). Alternativa: un solo `az deployment group create` con Bicep (sección 13).
4. Crear en Cloudflare un registro `A` (proxy activado) hacia la IP pública (sección 6).
5. Crear el superusuario con `az vm run-command invoke` (sección 7).
6. Verificar: `https://<tu-host>/healthz/` responde `ok`.
7. Opcional: CI/CD por OIDC (sección 8), presupuesto y etiquetas (sección 9), respaldos (sección 10).

## 1. Mapa de conceptos AWS → Azure

| AWS (lo que ya conoces) | Azure | Qué es, en una línea |
|-------------------------|-------|----------------------|
| Cuenta de AWS | **Tenant** (Microsoft Entra ID) + **Suscripción** | La suscripción es la unidad de facturación y de permisos; el tenant es el directorio de identidades. Una cuenta de AWS se parece más a una suscripción |
| Región | **Región** (`location`) | Igual: un centro de datos geográfico (`mexicocentral`, `southcentralus`) |
| *(no existe un equivalente directo; lo más cercano son los stacks de CloudFormation y las etiquetas)* | **Grupo de recursos (Resource Group, RG)** | Carpeta lógica que contiene todos los recursos de un proyecto. Se crea, etiqueta, da permisos, mide costos y **se borra como una unidad** (sección 12) |
| VPC | **Red virtual (VNet)** | Red privada aislada con un rango CIDR (`10.20.0.0/16`) |
| Subred pública | **Subred (Subnet)** | Segmento de la VNet. En Azure una subred no es "pública" o "privada" por sí misma: lo que expone la VM es tener una IP pública asociada y un NSG que lo permita |
| Security Group | **Network Security Group (NSG)** | Conjunto de reglas de entrada/salida con prioridad (número menor gana). Se asocia a una NIC o a una subred. Tiene reglas por defecto (deniega todo lo que viene de Internet) |
| Prefix list / IP de Cloudflare en el SG | **Etiquetas de servicio (service tags)** vs. lista de CIDR | Una *service tag* (`AzureCloud`, `Storage`, `Internet`) es una lista de IP **de servicios de Azure** que Microsoft mantiene. Cloudflare no es un servicio de Azure, así que no hay etiqueta para él: se listan sus CIDR a mano en la regla, como hace el stack de AWS |
| Elastic IP | **IP pública estática, SKU Standard** | IP fija que sobrevive a detener/desasignar la VM. La SKU Basic se retiró el 2025-09-30; hoy se usa Standard (que además nace cerrada: no recibe tráfico hasta que un NSG lo permite) |
| Interfaz de red de la instancia | **NIC (Network Interface)** | Recurso aparte que conecta la VM a la subred y lleva la IP privada, la pública y el NSG |
| EC2 | **Máquina virtual (VM)** | Servidor virtual. El "tipo de instancia" es el **tamaño** (`Standard_B2ats_v2`) |
| Serie t3 (créditos de CPU) | **Serie B (burstable)** | CPU con línea base baja y ráfagas por créditos. `B2ats_v2` tiene base de 20 % y acumula créditos |
| EBS | **Disco administrado (Managed Disk)** | Volumen de bloques. Tipos: Standard HDD, **Standard SSD** (equivale a gp-barato), Premium SSD |
| AMI | **Imagen (publisher:offer:sku:version)** | Se identifica con una "URN", p. ej. `Canonical:ubuntu-24_04-lts:server:latest` |
| User data | **cloud-init (custom data)** | Mismo mecanismo (cloud-init) y misma idea: se ejecuta **solo en el primer arranque**. Se pasa con `--custom-data` |
| SSM Session Manager / Run Command | **`az vm run-command invoke`** / Serial Console / **Azure Bastion** | Run Command ejecuta scripts por el agente de la VM sin puertos abiertos (equivale a SSM Run Command). Para un shell interactivo: Serial Console (gratis, limitado) o Bastion (cuesta por hora); ver sección 7 |
| Rol IAM + OIDC de GitHub | **App registration o identidad administrada asignada por el usuario + credencial federada + asignación de rol (RBAC)** | GitHub presenta un token OIDC; Entra ID lo canjea por un token de Azure sin secretos guardados. El **rol RBAC** acotado a un alcance (suscripción, RG o recurso) define qué puede hacer |
| AWS Budgets | **Presupuestos de Cost Management** | Umbrales de gasto real o pronosticado con correos de alerta |
| Etiquetas (tags) | **Etiquetas (tags)** | Igual (clave/valor), pero **no se heredan solas** del RG a los recursos; se resuelve con la política "Inherit a tag from the resource group" (sección 9) |
| DLM (snapshots programados) | **Instantáneas incrementales** / **Azure Backup** | Las instantáneas incrementales son baratas pero no tienen programador nativo simple; Azure Backup programa y retiene, pero cuesta más |
| Alarma de CloudWatch que recupera la instancia | **Service healing** (automático) | Si el host físico falla, Azure vuelve a desplegar la VM en otro host por sí mismo (misma IP y discos). No hay alarma que configurar (verificar en "VM availability" de learn.microsoft.com) |
| CDK (Python) | **Bicep** (o Terraform) | Lenguaje declarativo propio de Azure que compila a plantillas ARM. Sección 13 |
| CloudFormation stack / `cdk destroy` | **`az group delete`** | Borra el RG y todo lo que contiene |

### El grupo de recursos: el concepto que más se olvida

En AWS un `cdk destroy` borra "un stack". En Azure **todo recurso vive dentro de exactamente un grupo de recursos**, y el grupo es la unidad natural de:

| Se hace por grupo de recursos | Efecto práctico |
|-------------------------------|-----------------|
| Ciclo de vida | `az group delete` elimina VM, discos, NIC, IP, NSG y VNet de un golpe |
| Permisos | Un rol asignado al RG aplica a todo lo que contiene (se usa en el CI/CD, sección 8) |
| Costos | Cost Management filtra y presupuesta por RG |
| Etiquetas | Las del RG se pueden heredar a los recursos |

Regla de oro: **un RG por proyecto y ambiente** (`canaco-prod-rg`). Mezclar proyectos en un RG hace imposible borrar o medir uno solo.

## 2. Arquitectura

```
Visitante
   │ HTTPS
   ▼
Cloudflare (proxy, SSL "Full")
   │ HTTPS 443 (solo CIDR de Cloudflare, regla del NSG)
   ▼
IP pública estática (Standard) ─► NIC + NSG ─► VM Ubuntu 24.04 (Standard_B2ats_v2)
                                                 └─ Docker Compose (proyecto canaco-prod)
                                                     ├─ nginx :80/:443 ─► gunicorn (web :8000) ─► PostgreSQL 17 (volumen)
                                                     └─ certificado autofirmado u Origin CA

Todo dentro de: Suscripción ─► Grupo de recursos canaco-prod-rg ─► VNet 10.20.0.0/16 ─► Subred 10.20.1.0/24

GitHub Actions ─ OIDC ─► app registration ─► rol sobre el RG ─► az vm run-command ─► VM
Operador ─────────────── az vm run-command invoke ───────────────────────────────► VM
```

| Decisión | Motivo |
|----------|--------|
| Sin puerto 22 abierto | El acceso puntual y el despliegue usan Run Command; el NSG no tiene ninguna regla para SSH |
| NSG solo con CIDR de Cloudflare en 80/443 | Nadie llega al origen sin pasar por Cloudflare (mismo criterio que el Security Group de AWS) |
| IP pública Standard estática | Equivale a la Elastic IP: la dirección no cambia al reiniciar o desasignar |
| Sin NAT Gateway ni Bastion | Ahorra costo; la IP pública de la NIC da salida a Internet a la VM |
| VM única con Postgres en contenedor | Mínimo costo; los respaldos cubren el riesgo (sección 10) |
| Tamaño burstable de 1 GiB de RAM + 2 GiB de swap | Mismo criterio que la `t3.micro` |
| Disco Standard SSD de 32 GiB, `delete option = Detach` | La base de datos sobrevive a un borrado accidental de la VM (sección 5) |

> **Cambio reciente de Azure que afecta a los principiantes:** las redes virtuales creadas con APIs posteriores al 2026-03-31 usan subredes privadas por defecto, es decir, **sin acceso saliente implícito a Internet**. Esta guía no depende de eso porque la VM lleva su propia IP pública (da salida explícita), pero si algún día quitas la IP pública necesitarás un NAT Gateway u otro método de salida para que `docker pull` funcione.

## 3. Requisitos previos

### 3.1 Cuenta de Azure

Hay dos formas de empezar (verificado en azure.microsoft.com/free, 2026-10-27):

| Opción | Qué incluye |
|--------|-------------|
| **Cuenta gratuita de Azure** (solo clientes nuevos) | **200 USD de crédito durante 30 días**, más cantidades mensuales gratuitas de 20+ servicios por **12 meses** y 65+ servicios siempre gratuitos. Protección de gasto: la tarjeta no se cobra mientras uses la cuenta gratuita |
| **Pago por uso (pay-as-you-go)** | Sin crédito; pagas lo que uses |

Puntos importantes:

- Para conservar los 12 meses de servicios gratuitos debes **pasar a pago por uso dentro de los primeros 30 días** (según la nota al pie de la página de servicios gratuitos). Si no, al terminar el crédito o los 30 días los recursos se deshabilitan.
- Para máquinas virtuales Linux o Windows, los 12 meses gratuitos dan **750 horas al mes de cada uno** de estos tamaños burstable: **B1s, B2pts v2 (Arm) y B2ats v2 (AMD)**. 750 horas cubren una VM encendida las 24 horas (un mes tiene ~730 h). Las 750 h son por tamaño, no se suman entre tamaños.
- **No verificado:** la cantidad gratuita de discos administrados y de IP pública (la página de servicios gratuitos no los listó al consultarla). Históricamente se mencionaban discos P6 de 64 GiB; **verificar en azure.microsoft.com/pricing/free-services**. Asume que el disco y la IP pública **sí se cobran** (salen del crédito).
- El crédito y las horas gratuitas son **por suscripción nueva**; no los acumulas con una suscripción vieja.

### 3.2 Azure CLI

```bash
brew install azure-cli
az version                  # comprobar la instalación
az login                    # abre el navegador; elige tu cuenta
az account list -o table    # ver las suscripciones disponibles
az account set --subscription "<nombre o id de la suscripción>"
az account show -o table    # confirmar cuál quedó activa
```

La CLI siempre actúa sobre **una suscripción activa**; `az account show` es el equivalente de `aws sts get-caller-identity`. Ejecútalo antes de crear nada: es la forma de no desplegar (y cobrar) en la suscripción equivocada.

### 3.3 Elegir la región

| Región | Ubicación | Comentarios (precios de lista Linux, API de precios, 2026-10-27) |
|--------|-----------|--------------------------------------------------------------------|
| `mexicocentral` | Querétaro, México | La más cercana a usuarios en México. VM B2ats v2: 0.0103 USD/h. No tiene región par (`N/A`) y 3 zonas de disponibilidad |
| `southcentralus` | Texas, EE. UU. | Alternativa de baja latencia hacia México y con más catálogo. VM B2ats v2: 0.0113 USD/h |
| `eastus` / `eastus2` | Virginia, EE. UU. | VM B2ats v2: 0.0094 USD/h (más barata, mayor latencia) |

Como el tráfico pasa por Cloudflare (que cachea los estáticos), la latencia hacia el origen importa poco para la mayoría de las páginas; elige por costo y disponibilidad si no necesitas el origen en México.

**Antes de elegir, confirma que el tamaño existe en tu suscripción y región** (las cuentas gratuitas tienen cuotas bajas y algunos tamaños no están disponibles en todas las regiones; es el error más común, ver sección 14):

```bash
az vm list-skus --location mexicocentral --size Standard_B2ats --resource-type virtualMachines -o table
# La columna "Restrictions" debe estar vacía (NotAvailableForSubscription = no disponible para ti)
```

## 4. Crear la red y la seguridad (Azure CLI)

Pega las variables una sola vez; el resto de la guía las reutiliza (misma terminal).

```bash
# --- Variables (edítalas) ---------------------------------------------------
LOCATION=mexicocentral              # o southcentralus
RG=canaco-prod-rg
VNET=canaco-vnet
SUBNET=canaco-subnet
NSG=canaco-nsg
PIP=canaco-ip
VM=canaco-vm
ADMIN=azureuser
DOMAIN=canaco-az.jjjl.dev           # hostname que atenderá Django (sección 6)
REPO_URL=https://github.com/JoryerJL/proyectoweb.git
OWNER_EMAIL=tu@correo.com

# Etiquetas FinOps (mismas claves que en AWS)
TAGS="Project=canaco Application=canaco-web Environment=prod Owner=joryer CostCenter=m4-proyectoweb ManagedBy=azure-cli Repository=github.com/JoryerJL/proyectoweb"
```

### 4.1 Grupo de recursos

```bash
az group create --name "$RG" --location "$LOCATION" --tags $TAGS
```

`$TAGS` va **sin comillas** a propósito: la CLI recibe cada `clave=valor` como un argumento separado. (En zsh, si falla, usa `${=TAGS}`.)

### 4.2 Red virtual y subred

```bash
az network vnet create \
  --resource-group "$RG" --name "$VNET" --location "$LOCATION" \
  --address-prefixes 10.20.0.0/16 \
  --subnet-name "$SUBNET" --subnet-prefixes 10.20.1.0/24 \
  --tags $TAGS
```

### 4.3 NSG: solo Cloudflare en 80/443 y nada de SSH

Un NSG nuevo ya trae reglas por defecto (prioridades 65000+): permiten el tráfico dentro de la VNet y **deniegan todo lo demás que venga de Internet**. Por eso no hace falta una regla de denegación: solo agregamos la regla que **permite** Cloudflare.

```bash
az network nsg create --resource-group "$RG" --name "$NSG" --location "$LOCATION" --tags $TAGS

# Rangos IPv4 vigentes de Cloudflare (se descargan, no se copian a mano)
CF_IPS=($(curl -fsS https://www.cloudflare.com/ips-v4))
echo "${#CF_IPS[@]} rangos"      # hoy: 15

az network nsg rule create \
  --resource-group "$RG" --nsg-name "$NSG" \
  --name allow-cloudflare-web \
  --priority 100 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes "${CF_IPS[@]}" \
  --source-port-ranges '*' \
  --destination-address-prefixes '*' \
  --destination-port-ranges 80 443
```

Notas:

- **No se crea ninguna regla para el puerto 22.** Sin regla `Allow`, el NSG deniega el SSH aunque la VM tenga un servidor SSH escuchando.
- Una regla acepta muchos CIDR (el límite documentado es de 2,000 direcciones/rangos por origen en una regla; los 15 de Cloudflare caben de sobra; verificar en "Azure subscription and service limits" si algún día crece).
- Solo IPv4: la VM tiene una IP pública IPv4 y Cloudflare se conecta al origen por esa dirección. Los rangos IPv6 (`/ips-v6`) no se necesitan para esta arquitectura.
- Cloudflare casi no cambia sus rangos, pero si cambian debes **repetir el comando** (misma regla, mismo nombre: la CLI la actualiza) y actualizar `deploy/nginx/cloudflare-realip.conf`, que usa los mismos rangos para leer la IP real del visitante.

### 4.4 IP pública estática

```bash
az network public-ip create \
  --resource-group "$RG" --name "$PIP" --location "$LOCATION" \
  --sku Standard --allocation-method Static --version IPv4 \
  --tags $TAGS

az network public-ip show -g "$RG" -n "$PIP" --query ipAddress -o tsv
```

Una IP pública Standard **estática se cobra siempre** (0.005 USD/h ≈ 3.65 USD/mes), esté o no asociada a una VM en marcha. Es el mismo trato que la IPv4 de AWS.

## 5. Crear la VM con cloud-init

### 5.1 El archivo `cloud-init.yaml`

Es el equivalente al `user_data.py` del stack de AWS, pero para Ubuntu 24.04 (apt en lugar de dnf). Guárdalo como `cloud-init.yaml` en tu directorio de trabajo. Contiene dos marcadores, `__DOMAIN__` y `__REPO_URL__`, que se sustituyen antes de enviarlo (cloud-init no interpola variables por sí mismo).

```yaml
#cloud-config
# Canaco bootstrap para Azure. cloud-init lo ejecuta UNA sola vez, en el primer arranque,
# como root. El script que escribe es idempotente: puedes repetirlo a mano sin romper nada.
write_files:
  - path: /usr/local/sbin/canaco-bootstrap.sh
    owner: root:root
    permissions: "0750"
    content: |
      #!/bin/bash
      set -euo pipefail
      export HOME=/root
      export DEBIAN_FRONTEND=noninteractive
      exec > >(tee -a /var/log/canaco-bootstrap.log) 2>&1
      echo "=== canaco bootstrap started $(date -u +%FT%TZ) ==="

      APP_DIR=/opt/canaco
      DOMAIN='__DOMAIN__'
      REPO_URL='__REPO_URL__'
      APT='apt-get -o DPkg::Lock::Timeout=300 -y'

      # 1. Swap (el tamaño B2ats_v2 tiene 1 GiB de RAM y no trae disco temporal) ------
      if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
      fi
      swapon --show | grep -q /swapfile || swapon /swapfile
      grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

      # 2. Docker Engine + plugin compose desde el repositorio apt oficial de Docker ----
      if ! docker compose version >/dev/null 2>&1; then
        $APT update
        $APT install ca-certificates curl git openssl
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
          > /etc/apt/sources.list.d/docker.list
        $APT update
        $APT install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      fi
      systemctl enable --now docker
      docker compose version

      # 3. Código de la aplicación ----------------------------------------------------
      if [ -d "$APP_DIR/.git" ]; then
        git -C "$APP_DIR" pull --ff-only
      else
        git clone "$REPO_URL" "$APP_DIR"
      fi
      cd "$APP_DIR"

      # 4. .env (solo si no existe: los secretos se generan una vez y no se sobrescriben)
      set_kv() {
        if grep -q "^$1=" .env; then
          sed -i "s|^$1=.*|$1=$2|" .env
        else
          echo "$1=$2" >> .env
        fi
      }
      if [ ! -f .env ]; then
        umask 077
        cp deploy/env.example .env
        set_kv DJANGO_SECRET_KEY "$(openssl rand -base64 48 | tr -d '\n/+=')"
        set_kv DB_PASSWORD "$(openssl rand -hex 24)"
        set_kv DJANGO_DEBUG false
        set_kv DJANGO_ALLOWED_HOSTS "$DOMAIN"
        set_kv DJANGO_CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
        set_kv DJANGO_USE_PROXY_SSL_HEADER true
        set_kv DJANGO_SECURE_SSL_REDIRECT true
        set_kv DJANGO_SESSION_COOKIE_SECURE true
        set_kv DJANGO_CSRF_COOKIE_SECURE true
        chmod 600 .env
        echo ".env generated."
      else
        echo ".env already exists, left untouched."
      fi

      # 5. Levantar el stack ----------------------------------------------------------
      # Nunca se compila en la VM (1 GiB de RAM): o se descarga la imagen o se avisa y se sale.
      if docker compose -f docker-compose.prod.yml pull; then
        docker compose -f docker-compose.prod.yml up -d --no-build
      else
        echo "WARNING: could not pull the images. Is the GHCR package published and public?"
        echo "Fix it, then run: cd $APP_DIR && docker compose -f docker-compose.prod.yml up -d --no-build"
      fi
      echo "=== canaco bootstrap finished $(date -u +%FT%TZ) ==="

runcmd:
  - [bash, /usr/local/sbin/canaco-bootstrap.sh]
```

Diferencias con el script de AWS, por si las comparas:

| Tema | AWS (`user_data.py`) | Azure (`cloud-init.yaml`) |
|------|----------------------|---------------------------|
| Formato | Script bash directo | `#cloud-config` que escribe el script con `write_files` y lo ejecuta con `runcmd` |
| Paquetes | `dnf install docker git` + binario de compose descargado y verificado con sha256 | Repositorio apt oficial de Docker (`docker-compose-plugin`); apt verifica las firmas |
| Sustitución de valores | `string.Template` de Python | Marcadores `__DOMAIN__`/`__REPO_URL__` reemplazados con `sed` (o `replace()` en Bicep) |
| `$` en el script | Se escapa como `$$` | No hace falta: cloud-init no interpola |
| Bloqueo de apt | No aplica | `DPkg::Lock::Timeout=300`: en el primer arranque `unattended-upgrades` puede tener el bloqueo de apt unos minutos |

### 5.2 Idempotencia: qué significa y qué no

- **cloud-init corre solo en el primer arranque de la instancia.** Si lo modificas después, **no** se vuelve a ejecutar (igual que el user data de EC2). Para aplicar un cambio, edita lo que necesites a mano con Run Command (sección 7) o ejecuta `sudo /usr/local/sbin/canaco-bootstrap.sh` otra vez.
- **Volver a ejecutar el script es seguro**: el swap, Docker y el clon se omiten o actualizan, y `.env` **nunca se sobrescribe** (los secretos y el `IMAGE_TAG` que fijó un despliegue se conservan).
- Si `docker pull` falla porque el paquete es privado, el script termina con aviso (no con error) y la VM queda sin app. Soluciona la visibilidad y vuelve a ejecutarlo.

### 5.3 Generar el archivo final y crear la VM

```bash
# Sustituir los marcadores (macOS usa sed -i '' ; aquí se genera un archivo nuevo)
sed -e "s|__DOMAIN__|${DOMAIN}|g" -e "s|__REPO_URL__|${REPO_URL}|g" cloud-init.yaml > cloud-init.rendered.yaml

az vm create \
  --resource-group "$RG" --name "$VM" --location "$LOCATION" \
  --image Canonical:ubuntu-24_04-lts:server:latest \
  --size Standard_B2ats_v2 \
  --admin-username "$ADMIN" --generate-ssh-keys \
  --vnet-name "$VNET" --subnet "$SUBNET" \
  --nsg "$NSG" --nsg-rule NONE \
  --public-ip-address "$PIP" --public-ip-sku Standard \
  --storage-sku StandardSSD_LRS --os-disk-size-gb 32 \
  --os-disk-delete-option Detach --nic-delete-option Delete \
  --custom-data cloud-init.rendered.yaml \
  --tags $TAGS
```

Qué hace cada decisión:

| Opción | Por qué |
|--------|---------|
| `--image Canonical:ubuntu-24_04-lts:server:latest` | URN de Ubuntu 24.04 LTS, x86_64, generación 2 (verificado en la documentación de Ubuntu para Azure). `latest` toma la imagen más reciente al crear; la VM no se actualiza sola después |
| `--size Standard_B2ats_v2` | Ver tabla de tamaños abajo |
| `--generate-ssh-keys` | Azure exige una credencial de administrador al crear una VM Linux. Se crea una llave en `~/.ssh` y se instala en la VM, **pero el NSG no deja entrar a nadie por el 22**, así que no se usa para operar |
| `--nsg "$NSG" --nsg-rule NONE` | Usa el NSG que ya creamos y evita que la CLI agregue una regla `Allow SSH` automática (por defecto lo haría en Linux) |
| `--public-ip-address "$PIP" --public-ip-sku Standard` | Reutiliza la IP estática creada en 4.4 |
| `--storage-sku StandardSSD_LRS --os-disk-size-gb 32` | Disco SSD estándar de 32 GiB (equivale al tier E4, 2.40 USD/mes en South Central US). El Premium SSD P4 de 32 GiB cuesta el doble y para esta carga no hace falta |
| `--os-disk-delete-option Detach` | Si borras **la VM**, el disco **queda** (con la base de datos), como el `DeleteOnTermination=false` del stack de AWS. Con `Delete` el disco se borra con la VM |
| `--nic-delete-option Delete` | La NIC se borra con la VM; no tiene datos |
| `--custom-data` | Es el cloud-init (límite de 64 KB de custom data; verificar en learn.microsoft.com si cambia) |

La IP pública **no** se borra con la VM (es un recurso independiente), a propósito: así la dirección sobrevive, como una Elastic IP. Esa independencia también significa que **sigue cobrando** si la olvidas.

> Si `--nsg-rule NONE` o `--nsg` te dan un error de sintaxis en tu versión de la CLI, revisa `az vm create --help` (los valores aceptados de `--nsg-rule` son `NONE`, `RDP`, `SSH`). Una VM creada con una regla SSH abierta se corrige con `az network nsg rule delete -g "$RG" --nsg-name "$NSG" -n default-allow-ssh`.

### 5.4 Elegir el tamaño

Datos verificados el 2026-10-27 (documentación de tamaños + página de servicios gratuitos + API de precios, Linux, bajo demanda, 730 h/mes):

| Tamaño | vCPU / RAM | Arquitectura | Gratis 12 meses | Precio en `mexicocentral` | Precio en `southcentralus` |
|--------|-----------|--------------|-----------------|---------------------------|---------------------------|
| **`Standard_B2ats_v2`** (recomendado) | 2 / 1 GiB, base de CPU 20 % | AMD x86_64 | Sí (750 h) | 0.0103 USD/h ≈ 7.52 USD/mes | 0.0113 USD/h ≈ 8.25 USD/mes |
| `Standard_B1s` | 1 / 1 GiB | x86_64 | Sí (750 h) | 0.0114 USD/h ≈ 8.32 USD/mes | 0.0125 USD/h ≈ 9.13 USD/mes |
| `Standard_B2pts_v2` | 2 / 1 GiB | **Arm64** | Sí (750 h) | no listada en `mexicocentral` | 0.0101 USD/h ≈ 7.37 USD/mes |
| `Standard_B2s_v2` | 2 / 8 GiB | x86_64 | No | no consultada | 0.0998 USD/h ≈ 72.85 USD/mes |

Recomendación: **`Standard_B2ats_v2`**. Es elegible para la capa gratuita, tiene 2 vCPU (mejor que B1s para el arranque de gunicorn y Postgres) y es **x86_64**, igual que la imagen que publica el CI. `B2pts_v2` es Arm: la imagen de GHCR tendría que publicarse también para `linux/arm64`. Con **1 GiB de RAM** el sistema trabaja gracias a los 2 GiB de swap del cloud-init, exactamente como la `t3.micro` de AWS; si ves contenedores terminados por falta de memoria, sube a un tamaño de más RAM (sección 14).

Recuerda que "elegible para capa gratuita" no es lo mismo que "disponible": confirma con `az vm list-skus` (sección 3.3).

### 5.5 Ver el progreso del primer arranque

`az vm create` termina cuando Azure aprovisionó la VM, **no** cuando cloud-init terminó de instalar Docker. Revisa el estado sin SSH:

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript \
  --scripts "cloud-init status --long; tail -50 /var/log/canaco-bootstrap.log" \
  --query "value[0].message" -o tsv
```

Espera `status: done` y la línea `=== canaco bootstrap finished ...`. Si ves `status: running`, espera unos minutos y repite. Logs completos de cloud-init: `/var/log/cloud-init-output.log`.

### 5.6 Apagado automático (FinOps, opcional)

```bash
az vm auto-shutdown -g "$RG" -n "$VM" --time 0500 --email "$OWNER_EMAIL"   # hora UTC, HHMM
az vm auto-shutdown -g "$RG" -n "$VM" --off                                # desactivar
```

Es útil para entornos de prueba (la VM se **desasigna** cada noche y no cobra cómputo), pero **deja la app fuera de línea** hasta que alguien la inicie (`az vm start`). Para producción no es lo apropiado.

## 6. Cloudflare

Igual que en AWS ([sección 4 de la guía de EC2](despliegue-ec2.md)):

1. DNS > registro `A`, nombre `canaco-az` (o el que elijas), contenido = IP pública, **Proxied** (nube naranja). La IP: `az network public-ip show -g "$RG" -n "$PIP" --query ipAddress -o tsv`.
2. SSL/TLS > modo **Full**: funciona con el certificado autofirmado que genera nginx.
3. (Recomendado) **Full (strict)** con un certificado de origen: SSL/TLS > Origin Server > Create Certificate (hostname `canaco-az.jjjl.dev`). Guarda los archivos como `/opt/canaco/deploy/certs/origin.pem` y `origin.key` (`chmod 600 origin.key`) usando Run Command (ver ejemplo abajo), reinicia nginx (`docker compose -f docker-compose.prod.yml restart nginx`) y cambia el modo a Full (strict).

### ¿Hostname nuevo o cambiar el existente?

| Opción | Cómo | Ventajas / cuidados |
|--------|------|---------------------|
| **Hostname distinto** (recomendado): `canaco-az.jjjl.dev` | `DOMAIN=canaco-az.jjjl.dev` en las variables | Las dos versiones (AWS y Azure) conviven y se pueden comparar. Cada una tiene su propio `DJANGO_ALLOWED_HOSTS`: una petición a la otra recibiría un 400 |
| **Mismo hostname** `canaco.jjjl.dev` | Crea la VM con `DOMAIN=canaco.jjjl.dev` y **cambia el contenido** del registro `A` a la IP de Azure | Cambio de proveedor con un solo registro y reversible (devuelves la IP anterior). Mientras tanto la instancia de AWS deja de recibir tráfico (apágala para no pagar de más) |

Ejemplo para guardar el certificado de origen sin SSH (pega el contenido de tus archivos en los heredocs):

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts '
set -e
mkdir -p /opt/canaco/deploy/certs
cat > /opt/canaco/deploy/certs/origin.pem <<"PEM"
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
PEM
cat > /opt/canaco/deploy/certs/origin.key <<"PEM"
-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
PEM
chmod 600 /opt/canaco/deploy/certs/origin.key
cd /opt/canaco && docker compose -f docker-compose.prod.yml restart nginx
'
```

> Una llave privada pasada por Run Command queda en el historial de tu terminal y en los registros de actividad del script. Si te incomoda, usa temporalmente el Serial Console (sección 7.2) para pegarla.

## 7. Operar la VM sin SSH

### 7.1 `az vm run-command invoke` (equivale a SSM Run Command)

Ejecuta un script como **root** a través del agente de Azure en la VM, sin puertos abiertos. Restricciones documentadas (verificado en learn.microsoft.com, 2026-10-27):

| Característica | Detalle |
|----------------|---------|
| Salida | Solo los **últimos 4,096 bytes** (usa `tail`) |
| Duración máxima | **90 minutos** (luego expira); el mínimo ronda los 20 segundos |
| Concurrencia | **Un solo script a la vez** por VM; no se puede cancelar uno en ejecución |
| Interactivo | No soporta scripts que pidan entrada |
| Requisito | La VM necesita salida por el puerto 443 para devolver el resultado y el agente de Azure en marcha |
| Comportamiento de la CLI | Es **síncrona**: el comando espera a que termine el script y devuelve la salida (con `--no-wait` no espera) |

Patrones útiles (todos usan `tail` por el límite de 4 KB):

```bash
RUN="az vm run-command invoke -g $RG -n $VM --command-id RunShellScript --query value[0].message -o tsv"

# Estado de los contenedores
$RUN --scripts "docker compose -f /opt/canaco/docker-compose.prod.yml ps"

# Logs de la aplicación
$RUN --scripts "docker compose -f /opt/canaco/docker-compose.prod.yml logs --tail 50 web"

# Datos de ejemplo (opcional)
$RUN --scripts "cd /opt/canaco && docker compose -f docker-compose.prod.yml exec -T web python manage.py seed_news"
```

**Superusuario sin preguntas interactivas** (Run Command no admite prompts): `createsuperuser --noinput` lee las variables `DJANGO_SUPERUSER_*`.

```bash
SU_PASS=$(openssl rand -base64 18)       # contraseña temporal; guárdala
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript \
  --scripts "cd /opt/canaco && docker compose -f docker-compose.prod.yml exec -T \
    -e DJANGO_SUPERUSER_USERNAME=admin \
    -e DJANGO_SUPERUSER_EMAIL=$OWNER_EMAIL \
    -e DJANGO_SUPERUSER_PASSWORD='$SU_PASS' \
    web python manage.py createsuperuser --noinput" \
  --query "value[0].message" -o tsv
echo "$SU_PASS"
```

> La contraseña viaja dentro del texto del script, que queda en el historial de tu shell y en los registros de Azure. Úsala solo como **contraseña temporal** y cámbiala de inmediato desde el panel de administración. Si el modelo de usuario del proyecto exige campos adicionales, `--noinput` fallará y te dirá cuáles faltan.

### 7.2 Shell interactivo: opciones y costos

| Opción | Costo | Seguridad | Cuándo usarla |
|--------|-------|-----------|---------------|
| **Run Command** (arriba) | Gratis | Sin puertos abiertos | Lo habitual: casi todo se resuelve así |
| **Serial Console** (portal: VM > Help > Serial console) | Gratis | Sin red; requiere usuario con contraseña local y diagnósticos de arranque habilitados | Rescate (no arranca la red, error de `fstab`). Con la VM de esta guía, que usa solo llave SSH, **tendrías que crear antes una contraseña local** con Run Command (`passwd`) y volver a bloquearla después. Verificar en learn.microsoft.com/azure/virtual-machines/boot-diagnostics |
| **Azure Bastion** | **Cuesta por hora, mientras exista** (de cientos de dólares al mes en SKU Standard; el SKU Developer es más barato pero con limitaciones; verificar precios en azure.microsoft.com/pricing/details/azure-bastion) | Sin IP pública para administrar | Equipos que necesitan shell a diario. **Para un proyecto de ~15 USD/mes no tiene sentido** |
| **SSH temporal desde tu IP** | Gratis | Abre un puerto a Internet mientras dure | Último recurso (abajo) |

SSH temporal restringido a tu IP actual (y cerrarlo al terminar):

```bash
MY_IP=$(curl -fsS https://api.ipify.org)
az network nsg rule create -g "$RG" --nsg-name "$NSG" -n tmp-ssh \
  --priority 200 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes "$MY_IP" --destination-port-ranges 22
ssh "$ADMIN@$(az network public-ip show -g "$RG" -n "$PIP" --query ipAddress -o tsv)"
# ...al terminar, ciérralo SIEMPRE:
az network nsg rule delete -g "$RG" --nsg-name "$NSG" -n tmp-ssh
```

> La IP pública de la VM pasa por Cloudflare solo para los puertos 80/443 del dominio; el SSH a la IP directa **no** pasa por Cloudflare, por eso se limita a tu IP. Es un hueco intencional y temporal; con Run Command casi nunca lo necesitarás.

## 8. CI/CD en Azure con GitHub Actions (OIDC)

Esta sección describe un job de despliegue **alternativo** para agregar junto al de AWS o en su lugar. **No modifica el workflow del repositorio**: es un ejemplo para que lo adaptes.

### 8.1 Cómo funciona (comparación con AWS)

```
GitHub Actions ──(token OIDC de la ejecución)──► Microsoft Entra ID
                                                   │ valida: emisor + subject + audiencia
                                                   ▼
                                       credencial federada de la app registration
                                                   │ emite un token de acceso de Azure (corto)
                                                   ▼
                          rol RBAC sobre el RG ──► az vm run-command invoke ──► VM
```

| AWS | Azure |
|-----|-------|
| Proveedor OIDC de GitHub en IAM | No se crea: Entra ID ya confía en tokens según la **credencial federada** que declares |
| Rol con política de confianza (`sub = repo:...:environment:production`) | **App registration + service principal** con una **credencial federada** (emisor, subject y audiencia) |
| Política del rol (solo `AWS-RunShellScript` en instancias con etiqueta) | **Asignación de rol RBAC** acotada a un alcance (RG o la VM) |
| `role-to-assume` | `client-id` + `tenant-id` + `subscription-id` (ninguno es secreto) |

Alternativa equivalente: una **identidad administrada asignada por el usuario** (user-assigned managed identity) con credencial federada. Funciona igual para este caso; la app registration es la ruta más documentada para GitHub y la que se usa aquí.

### 8.2 Crear la app registration, la credencial y el rol

```bash
GH_REPO=JoryerJL/proyectoweb
GH_ENV=production
SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

# 1) App registration + service principal
APP_ID=$(az ad app create --display-name canaco-github-deploy --query appId -o tsv)
SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)

# 2) Credencial federada: solo tokens del entorno "production" de este repositorio
cat > fic.json <<EOF
{
  "name": "github-production",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:${GH_REPO}:environment:${GH_ENV}",
  "description": "GitHub Actions deploy (production environment)",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
az ad app federated-credential create --id "$APP_ID" --parameters fic.json

# 3) Rol RBAC acotado al grupo de recursos (no a la suscripción)
RG_ID=$(az group show -n "$RG" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
  --role "Virtual Machine Contributor" --scope "$RG_ID"

echo "AZURE_CLIENT_ID=$APP_ID  AZURE_TENANT_ID=$TENANT_ID  AZURE_SUBSCRIPTION_ID=$SUB_ID"
```

Necesitas permisos en Entra ID para crear app registrations (el propietario de una cuenta personal los tiene).

**Por qué "Virtual Machine Contributor" sobre el RG, y qué permite:**

| Rol | Alcance | Permite |
|-----|---------|---------|
| Virtual Machine Contributor (rol integrado) | Solo el RG `canaco-prod-rg` | Administrar VM (crear, iniciar, detener, **ejecutar Run Command**, borrar) y discos/IP asociados dentro del RG. **No** da acceso a las credenciales de la VM ni administra la red virtual ni cuentas de almacenamiento |
| Owner / Contributor en la suscripción | Suscripción | Demasiado: un token robado podría tocar todo |

El alcance por RG es el equivalente a la condición por etiqueta `Project=canaco` del rol de AWS: acota **dónde** puede actuar. Aun así, quien ejecuta Run Command corre como **root** en la VM, igual que con SSM; por eso el entorno `production` debe limitarse a `master` (sección 8.3).

**Alternativa más estricta: rol personalizado** con solo lo necesario. Acciones relevantes (verificadas en la referencia de permisos de Microsoft.Compute): `Microsoft.Compute/virtualMachines/runCommand/action` (ejecutar Run Command) y `Microsoft.Compute/virtualMachines/read` (leer la VM). Puede que el comando necesite alguna lectura adicional (p. ej. `Microsoft.Compute/virtualMachines/instanceView/read` o `Microsoft.Compute/locations/runCommands/read`): **probar en tu suscripción y ajustar según el error `AuthorizationFailed`** (no verificado de extremo a extremo).

```bash
cat > role-canaco-runcommand.json <<EOF
{
  "Name": "Canaco Run Command Operator",
  "IsCustom": true,
  "Description": "Run shell scripts on canaco VMs; read-only otherwise.",
  "Actions": [
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Compute/virtualMachines/instanceView/read",
    "Microsoft.Compute/virtualMachines/runCommand/action"
  ],
  "NotActions": [],
  "AssignableScopes": ["${RG_ID}"]
}
EOF
az role definition create --role-definition role-canaco-runcommand.json
# y en el paso 3 usa --role "Canaco Run Command Operator" en lugar de "Virtual Machine Contributor"
```

### 8.3 Configurar GitHub

1. Settings > Environments > `production` (el mismo del despliegue de AWS) restringido a la rama `master`, con *Required reviewers* opcionales.
2. Agregar **variables** (no secretos; no son sensibles) al entorno: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` (`canaco-prod-rg`), `AZURE_VM_NAME` (`canaco-vm`).
3. Si cambias el nombre del repositorio o del entorno, **actualiza el `subject`** de la credencial federada (`az ad app federated-credential update`): un subject que no coincide produce `AADSTS70021`.

### 8.4 Job de despliegue de ejemplo

Para agregar a `.github/workflows/ci-cd.yml` (alternativo o adicional al job `deploy` de AWS; reutiliza `needs.build.outputs.short_sha`). En el repositorio las acciones se fijan por **SHA** con el comentario de versión; en el ejemplo se muestra la versión mayor para legibilidad: sustituye cada una por el SHA del commit correspondiente (`gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq .object.sha`).

```yaml
  deploy-azure:
    name: Deploy to Azure VM (Run Command)
    runs-on: ubuntu-latest
    needs: [build, infra]
    if: github.event_name == 'push' && github.ref == 'refs/heads/master'
    environment: production
    permissions:
      id-token: write
      contents: read
    concurrency:
      group: deploy-production-azure
      cancel-in-progress: false
    timeout-minutes: 30
    env:
      IMAGE_TAG: ${{ needs.build.outputs.short_sha }}
      SITE_URL: https://canaco-az.jjjl.dev
    steps:
      - name: Check deploy configuration
        id: gate
        env:
          CLIENT_ID: ${{ vars.AZURE_CLIENT_ID }}
        run: |
          if [ -z "$CLIENT_ID" ]; then
            echo "::notice::AZURE_CLIENT_ID is not set in the production environment; skipping Azure deploy."
            echo "enabled=false" >> "$GITHUB_OUTPUT"
          else
            echo "enabled=true" >> "$GITHUB_OUTPUT"
          fi

      - name: Azure login (OIDC)
        if: steps.gate.outputs.enabled == 'true'
        uses: azure/login@v3   # fijar por SHA como el resto del workflow
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}

      - name: Deploy with Run Command
        if: steps.gate.outputs.enabled == 'true'
        env:
          RG: ${{ vars.AZURE_RESOURCE_GROUP }}
          VM: ${{ vars.AZURE_VM_NAME }}
        run: |
          # El tag se escribe en .env para que un reinicio conserve esta versión.
          cat > deploy.sh <<EOF
          set -euo pipefail
          export HOME=/root
          cd /opt/canaco
          git pull --ff-only
          if grep -q '^IMAGE_TAG=' .env; then
            sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${IMAGE_TAG}|" .env
          else
            echo "IMAGE_TAG=${IMAGE_TAG}" >> .env
          fi
          docker compose -f docker-compose.prod.yml pull web
          docker compose -f docker-compose.prod.yml up -d --remove-orphans
          docker image prune -af
          echo DEPLOY_OK
          EOF

          # El comando es síncrono: espera a que termine el script (máx. 90 min en Azure).
          output=$(az vm run-command invoke \
            --resource-group "$RG" --name "$VM" \
            --command-id RunShellScript \
            --scripts @deploy.sh \
            --query "value[0].message" -o tsv)
          echo "$output"
          # No dependemos del código de salida: exigimos la marca final del script.
          grep -q '^DEPLOY_OK' <<<"$output" || { echo "Deployment failed." >&2; exit 1; }

      - name: Smoke test
        if: steps.gate.outputs.enabled == 'true'
        run: |
          for i in $(seq 1 30); do
            if curl -fsS "${SITE_URL}/healthz/"; then
              echo
              echo "Smoke test passed (attempt $i)."
              exit 0
            fi
            sleep 5
          done
          echo "Smoke test failed" >&2
          exit 1
```

Notas sobre el ejemplo:

- La versión mayor de `azure/login` vigente al 2026-10-27 es `v3` (última publicación `v3.1.0`); **verificar** en github.com/Azure/login/releases antes de fijar el SHA.
- `az vm run-command invoke` es **síncrono**: la CLI bloquea hasta que el script termina. El límite lo pone Azure (90 minutos para este tipo de comando); el `timeout-minutes: 30` del job es el que realmente manda. A diferencia de SSM no hace falta un bucle de sondeo. La salida solo conserva los **últimos 4,096 bytes**: la marca `DEPLOY_OK` va al final por eso.
- Solo puede haber **un script activo por VM**: el `concurrency` evita que dos despliegues se pisen (si uno falla por "otra operación en curso", reintenta).
- Si el paso `Smoke test` usa el hostname de Cloudflare y las rutas están bloqueadas por la caché o por un modo "Under Attack", el curl puede fallar sin que la app esté mal.

## 9. FinOps en Azure

### 9.1 Etiquetas

Mismas claves que en AWS. En Azure **no existe `Backup=daily`** (no hay un equivalente a DLM por etiqueta en esta guía); `ManagedBy` pasa a `azure-cli` (o `bicep` si usas la sección 13).

| Etiqueta | Valor | Significado |
|----------|-------|-------------|
| `Project` | `canaco` | Agrupa el costo del proyecto |
| `Application` | `canaco-web` | Componente de aplicación |
| `Environment` | `prod` | Ambiente |
| `Owner` | `joryer` | Responsable |
| `CostCenter` | `m4-proyectoweb` | Centro de costo |
| `ManagedBy` | `azure-cli` | Indica cómo se gestiona (no editar a mano si es Bicep) |
| `Repository` | `github.com/JoryerJL/proyectoweb` | Origen del código |

**Las etiquetas no se heredan solas del RG a los recursos** (a diferencia de la propagación de etiquetas de EC2 a EBS en el stack de AWS). Los comandos de la sección 4 ya etiquetan cada recurso que creamos con `--tags $TAGS`, pero los **discos** que genera `az vm create` pueden quedar sin etiqueta. Asegúralo con la política integrada **"Inherit a tag from the resource group"** (id `cd3aa116-8754-49c9-a813-ad46512ece54`; también existe "Inherit a tag from the resource group **if missing**", id `ea3f2387-9b95-492a-a190-fcdc54f7b070`, que no reemplaza valores existentes). Ambas usan el efecto `modify` y requieren una identidad con el rol *Contributor*:

```bash
for TAG in Project Application Environment Owner CostCenter ManagedBy Repository; do
  az policy assignment create \
    --name "inherit-$TAG" \
    --display-name "Inherit tag $TAG from resource group" \
    --policy cd3aa116-8754-49c9-a813-ad46512ece54 \
    --params "{\"tagName\": {\"value\": \"$TAG\"}}" \
    --resource-group "$RG" \
    --mi-system-assigned --location "$LOCATION" \
    --identity-scope "$RG_ID" --role Contributor
done
```

(`RG_ID` se definió en 8.2; si no lo tienes: `RG_ID=$(az group show -n "$RG" --query id -o tsv)`.) La política corrige recursos **nuevos o modificados**; para los existentes, crea una tarea de remediación (`az policy remediation create`; verificar los parámetros en la documentación). Cost Management también tiene un ajuste de **tag inheritance** que copia etiquetas de suscripción/RG a los datos de costo (verificar en learn.microsoft.com/azure/cost-management-billing/costs/enable-tag-inheritance).

Análisis de costo por etiqueta: Portal > Cost Management > Cost analysis > *Group by* > Tag > `Project`. A diferencia de AWS, **no hay que "activar" las etiquetas de costos**.

### 9.2 Presupuesto con alertas por correo

`az consumption budget create` existe pero está en **Preview** y su ejemplo documentado no muestra notificaciones por correo (verificado 2026-10-27); no lo uses para esto. El camino fiable es **Bicep** con `Microsoft.Consumption/budgets` (alcance: el grupo de recursos). Guarda `budget.bicep`:

```bicep
// budget.bicep: presupuesto mensual del RG con alertas por correo.
param budgetName string = 'canaco-monthly'
param monthlyBudgetUsd int = 20
param ownerEmail string
@description('Primer día de un mes, p. ej. 2026-11-01T00:00:00Z')
param startDate string

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: monthlyBudgetUsd
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [ownerEmail]
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [ownerEmail]
      }
    }
  }
}
```

```bash
az deployment group create -g "$RG" --template-file budget.bicep \
  --parameters ownerEmail="$OWNER_EMAIL" startDate="$(date -u +%Y-%m-01T00:00:00Z)"
```

Equivale al `canaco-monthly` de AWS: aviso al 80 % del gasto **real** y al 100 % del **pronosticado**. Como el gasto estimado ronda los 15 USD (tabla de abajo), el monto por defecto es 20 USD; con 10 USD la alerta de pronóstico se dispararía desde el primer día. Los datos de costo tardan hasta unas 24 horas en aparecer y los presupuestos se evalúan periódicamente (no son un tope: **solo avisan, no apagan nada**). El presupuesto de este ejemplo cubre todo el RG, por lo que no necesita filtro por etiqueta (el recurso admite filtros por etiqueta si lo pones a nivel de suscripción; verificar el esquema en learn.microsoft.com/azure/templates/microsoft.consumption/budgets).

### 9.3 Detener no es lo mismo que desasignar (importante)

| Acción | Estado | ¿Cobra cómputo? | Cuándo |
|--------|--------|-----------------|--------|
| Apagar **desde dentro** del sistema (`shutdown`) o `az vm stop` | *Stopped (allocated)* | **Sí** (sigue reservada) | Casi nunca lo que quieres |
| **`az vm deallocate`** | *Stopped (deallocated)* | **No** | Para dejar de pagar cómputo |
| `az vm start` | Running | Sí | Volver a encender |

```bash
az vm deallocate -g "$RG" -n "$VM"     # deja de cobrar cómputo; la app queda fuera de línea
az vm start -g "$RG" -n "$VM"
```

Aun desasignada, **siguen cobrando el disco y la IP pública estática** (verificado en la tabla de estados de facturación de VM de Microsoft: "Disks and Networking continue to incur charges"). Con una VM desasignada la IP se conserva (es estática), el equivalente a detener una EC2 con Elastic IP.

### 9.4 Estimación mensual (aproximada)

Precios de lista bajo demanda de la **API pública de precios minoristas de Azure** (consultada el **2026-10-27**), 730 h/mes, Linux, USD. Verifícalos en la [calculadora de precios de Azure](https://azure.microsoft.com/pricing/calculator/) y en la [página de precios de VM Linux](https://azure.microsoft.com/pricing/details/virtual-machines/linux/) antes de decidir.

| Concepto | Cálculo | `mexicocentral` | `southcentralus` |
|----------|---------|-----------------|------------------|
| VM `Standard_B2ats_v2` | 0.0103 / 0.0113 USD/h × 730 | 7.52 | 8.25 |
| Disco Standard SSD E4 (32 GiB) | tarifa mensual del tier | 2.64 | 2.40 |
| IP pública estática Standard | 0.005 USD/h × 730 | 3.65 | 3.65 |
| Instantáneas incrementales (7 diarias) | ~0.12-0.15 USD/GiB-mes de lo ocupado, pocos GiB | 0.50 - 1.00 | 0.50 - 1.00 |
| Transferencia de salida | Los primeros 100 GiB/mes son gratis (verificar); Cloudflare cachea estáticos | ~0 | ~0 |
| Cost Management y presupuestos | Sin costo | 0 | 0 |
| **Total aprox.** | | **~14.5 - 15** | **~15 - 15.5** |

Con una **cuenta nueva**: las 750 h/mes de `B2ats_v2` durante 12 meses cubren la VM (queda solo disco e IP, a cargo del crédito de 200 USD en los primeros 30 días y luego de tu tarjeta). Comparado con AWS (~13-14 USD) el costo es similar; el ahorro real en Azure viene del primer año gratuito.

### 9.5 Palancas de ahorro

| Palanca | Efecto | Costo / riesgo |
|---------|--------|----------------|
| `az vm deallocate` fuera de uso | Cero cómputo | App fuera de línea; disco e IP siguen cobrando |
| Auto-shutdown | Igual, programado | Solo para pruebas |
| Reservas de 1 o 3 años / Savings Plan | Ahorro relevante en cómputo (verificar en la página de precios) | Compromiso de pago |
| Eliminar IP pública | Ahorra 3.65 USD/mes | Rompe el diseño (Cloudflare necesita una IP de origen) |
| Reducir retención de instantáneas | Menos GiB | Menos historial |

## 10. Respaldos

| Opción | Costo | Ventajas | Inconvenientes |
|--------|-------|----------|----------------|
| **Instantáneas incrementales del disco** (manuales o programadas por ti) | Solo almacenamiento de lo cambiado (~0.12 USD/GiB-mes, ver 9.4) | Baratas, nativas, restauran el disco completo | No hay programador integrado en un solo comando: lo programas tú |
| **Azure Backup** (bóveda + política) | Cuota por instancia protegida + almacenamiento (verificar en azure.microsoft.com/pricing/details/backup) | Programación, retención y restauración desde el portal | Más costoso y más piezas que administrar |
| **Volcado lógico `pg_dump`** | Almacenamiento donde lo guardes | Restaura en cualquier PostgreSQL | Hay que sacar el archivo de la VM |

Para este proyecto: **instantáneas incrementales + `pg_dump` antes de cambios grandes**.

### 10.1 Instantánea manual del disco del sistema

```bash
DISK_ID=$(az vm show -g "$RG" -n "$VM" --query storageProfile.osDisk.managedDisk.id -o tsv)
SNAP="canaco-os-$(date -u +%F)"
az snapshot create -g "$RG" -n "$SNAP" --source "$DISK_ID" --incremental true --tags $TAGS
az snapshot list -g "$RG" -o table
```

### 10.2 Programarlas (ejemplo con GitHub Actions)

Un workflow con `schedule:` que se autentica por el mismo OIDC, crea la instantánea del día y borra las que superen 7. Requiere dar a la app el rol **Disk Snapshot Contributor** (rol integrado; verificar el nombre) sobre el RG:

```bash
az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
  --role "Disk Snapshot Contributor" --scope "$RG_ID"
```

```bash
# Núcleo del paso (después de azure/login): crear la de hoy y conservar las 7 más recientes
az snapshot create -g "$RG" -n "canaco-os-$(date -u +%F)" \
  --source "$(az vm show -g "$RG" -n "$VM" --query storageProfile.osDisk.managedDisk.id -o tsv)" \
  --incremental true
az snapshot list -g "$RG" --query "sort_by([?starts_with(name,'canaco-os-')],&timeCreated)[:-7].name" -o tsv \
  | xargs -r -I{} az snapshot delete -g "$RG" -n {}
```

(El borrado de instantáneas requiere también un permiso de eliminación sobre ellas; si el rol no lo trae, usa un rol personalizado. Verificar.)

### 10.3 Volcado lógico de PostgreSQL

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts '
set -e
cd /opt/canaco
mkdir -p /var/backups/canaco
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U canaco canaco \
  | gzip > /var/backups/canaco/canaco-$(date +%F).sql.gz
ls -lh /var/backups/canaco | tail -5
' --query "value[0].message" -o tsv
```

El archivo queda en la VM (la salida de Run Command es de solo 4 KB, no sirve para extraerlo) y también dentro de las instantáneas del disco. Para guardarlo fuera de la VM necesitas una cuenta de almacenamiento y subirlo con `az storage blob upload` usando una identidad de la VM (fuera del alcance de esta guía).

### 10.4 Restaurar

**Base de datos desde un volcado**:

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts '
cd /opt/canaco
gunzip -c /var/backups/canaco/canaco-AAAA-MM-DD.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U canaco canaco
'
```

**Disco completo desde una instantánea** (la VM debe estar desasignada):

```bash
SNAP_ID=$(az snapshot show -g "$RG" -n canaco-os-AAAA-MM-DD --query id -o tsv)
az disk create -g "$RG" -n canaco-os-restored --source "$SNAP_ID" --sku StandardSSD_LRS --tags $TAGS
az vm deallocate -g "$RG" -n "$VM"
az vm update -g "$RG" -n "$VM" --os-disk canaco-os-restored     # cambia el disco del sistema (verificar con az vm update --help)
az vm start -g "$RG" -n "$VM"
```

Los archivos subidos viven en el volumen `media_files` y quedan en las instantáneas. Si la VM falla por hardware, el **service healing** de Azure la recupera automáticamente (misma IP y discos).

## 11. Actualizaciones y rollback

Es idéntico a la guía de AWS porque depende de Docker, no del proveedor:

- **Despliegue**: el job `deploy-azure` (sección 8.4) hace `git pull`, fija `IMAGE_TAG=<sha corto>` en `.env`, `docker compose pull web`, `up -d --remove-orphans`, poda imágenes y prueba `/healthz/`. Como la versión queda en `.env`, un reinicio conserva la misma imagen.
- **Despliegue manual**: con Run Command ejecuta el mismo script (`deploy.sh` del ejemplo).
- **Rollback**: cambia `IMAGE_TAG` en `.env` a un SHA anterior (existe una imagen por commit en GHCR) y levanta de nuevo:

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts '
set -e
cd /opt/canaco
sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=<sha-anterior>|" .env
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
' --query "value[0].message" -o tsv
```

Si también debe volver atrás el código de `master`, revierte el commit y deja que el flujo despliegue.

- **Parches del sistema operativo**: Ubuntu aplica actualizaciones de seguridad automáticas (`unattended-upgrades`). La imagen `latest` solo se usa al crear la VM; para cambiar de versión mayor de Ubuntu, crea una VM nueva y restaura (no reemplaces el disco sin respaldo).

## 12. Eliminar todo

```bash
az group delete --name "$RG" --yes --no-wait
```

Borra **todo lo que esté dentro del grupo de recursos**: la VM, el disco del sistema (**con la base de datos**, aunque tenga `Detach`: ese ajuste solo protege si borras la VM suelta, no el RG), la NIC, la IP pública, el NSG, la VNet, las instantáneas y el presupuesto del RG. Si quieres conservar los datos, haz una instantánea o un `pg_dump` y cópialo **fuera** del RG antes.

**Lo que no se borra** (está fuera del RG) y puede seguir cobrando o dejando permisos:

| Recurso fuera del RG | Qué hacer |
|----------------------|-----------|
| Registro DNS en Cloudflare | Borrarlo a mano (si no, apunta a una IP que ya no es tuya) |
| App registration `canaco-github-deploy` (vive en Entra ID, no en el RG) | `az ad app delete --id "$APP_ID"` |
| Asignaciones de política creadas a nivel de RG | Se van con el RG; si las pusiste en la suscripción, bórralas con `az policy assignment delete` |
| Rol personalizado (si creaste uno) | `az role definition delete --name "Canaco Run Command Operator"` |
| Variables del entorno `production` en GitHub | Borrarlas a mano |

Para dejar de pagar sin destruir: `az vm deallocate` (sección 9.3) y recuerda que el disco y la IP seguirán cobrando.

## 13. Opcional: infraestructura como código con Bicep

Lo que hicimos con comandos se puede describir en un archivo declarativo, como el stack de CDK. Mapa de equivalencias:

| CDK (`infra/canaco_infra/stack.py`) | Bicep (`main.bicep`) |
|-------------------------------------|----------------------|
| `ec2.Vpc` (subredes públicas, sin NAT) | `Microsoft.Network/virtualNetworks` |
| `ec2.SecurityGroup` con rangos de Cloudflare | `Microsoft.Network/networkSecurityGroups` |
| `ec2.CfnEIP` | `Microsoft.Network/publicIPAddresses` (Standard, Static) |
| `ec2.Instance` + `UserData` | `Microsoft.Compute/virtualMachines` + `customData` con `loadTextContent('cloud-init.yaml')` |
| `Tags.of(app)` | parámetro `tags` aplicado a cada recurso |
| `budgets.CfnBudget` | `Microsoft.Consumption/budgets` (opcional) |
| `cdk deploy` | `az deployment group create` |

Qué **no** incluye: el rol de despliegue (se hace con la CLI, sección 8) y los respaldos programados. Guarda estos dos archivos juntos: `cloud-init.yaml` (el de la sección 5; conserva los marcadores `__DOMAIN__` y `__REPO_URL__`) y `main.bicep`.

```bicep
// main.bicep: VM de Canaco en Azure. Se despliega en un grupo de recursos existente:
//   az group create -n canaco-prod-rg -l mexicocentral
//   az deployment group create -g canaco-prod-rg --template-file main.bicep --parameters ...
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'canaco'
param vmName string = '${prefix}-vm'
param vmSize string = 'Standard_B2ats_v2'
param adminUsername string = 'azureuser'
@description('Contenido de la llave pública SSH (por ejemplo, el de ~/.ssh/id_rsa.pub)')
param sshPublicKey string
@description('Hostname que atenderá Django')
param domain string
param repoUrl string = 'https://github.com/JoryerJL/proyectoweb.git'
param osDiskSizeGb int = 32
param tags object = {
  Project: 'canaco'
  Application: 'canaco-web'
  Environment: 'prod'
  Owner: 'joryer'
  CostCenter: 'm4-proyectoweb'
  ManagedBy: 'bicep'
  Repository: 'github.com/JoryerJL/proyectoweb'
}
@description('Rangos IPv4 de Cloudflare (https://www.cloudflare.com/ips-v4, consultados 2026-10-27)')
param cloudflareIpv4 array = [
  '173.245.48.0/20'
  '103.21.244.0/22'
  '103.22.200.0/22'
  '103.31.4.0/22'
  '141.101.64.0/18'
  '108.162.192.0/18'
  '190.93.240.0/20'
  '188.114.96.0/20'
  '197.234.240.0/22'
  '198.41.128.0/17'
  '162.158.0.0/15'
  '104.16.0.0/13'
  '104.24.0.0/14'
  '172.64.0.0/13'
  '131.0.72.0/22'
]

// cloud-init con los marcadores sustituidos (loadTextContent exige una ruta literal)
var cloudInit = replace(replace(loadTextContent('cloud-init.yaml'), '__DOMAIN__', domain), '__REPO_URL__', repoUrl)

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${prefix}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'allow-cloudflare-web'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: cloudflareIpv4
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: [
            '80'
            '443'
          ]
        }
      }
      // Sin regla para el puerto 22: el acceso es por Run Command.
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: ['10.20.0.0/16']
    }
    subnets: [
      {
        name: '${prefix}-subnet'
        properties: {
          addressPrefix: '10.20.1.0/24'
        }
      }
    ]
  }
}

resource pip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${prefix}-ip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${prefix}-nic'
  location: location
  tags: tags
  properties: {
    networkSecurityGroup: {
      id: nsg.id
    }
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: vnet.properties.subnets[0].id
          }
          publicIPAddress: {
            id: pip.id
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: vmName
  location: location
  tags: tags
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: osDiskSizeGb
        deleteOption: 'Detach'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            primary: true
            deleteOption: 'Delete'
          }
        }
      ]
    }
  }
}

output publicIp string = pip.properties.ipAddress
output vmName string = vm.name
```

Despliegue:

```bash
az group create -n "$RG" -l "$LOCATION" --tags $TAGS

az deployment group create \
  --resource-group "$RG" \
  --template-file main.bicep \
  --parameters domain="$DOMAIN" sshPublicKey="$(cat ~/.ssh/id_rsa.pub)"
```

(Usa tu archivo de llave pública real; `az vm create --generate-ssh-keys` crea `~/.ssh/id_rsa.pub`.) Para ver qué cambiaría antes de aplicar: `az deployment group what-if ...` con los mismos parámetros. Para el presupuesto, despliega por separado `budget.bicep` (sección 9.2).

> **Estado de validación:** al escribir esta guía **no había Azure CLI ni el CLI de Bicep instalados** en la máquina, por lo que `main.bicep` **no se pudo compilar ni validar** automáticamente. Antes de usarlo ejecuta `az bicep build --file main.bicep` (y `az deployment group validate ...`), y revisa que las versiones de API (`@2024-05-01`, `@2024-07-01`, `@2023-05-01`) sigan vigentes en learn.microsoft.com/azure/templates; la documentación ya muestra versiones más recientes para algunos tipos, que también se pueden usar.

## 14. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| `az vm create`: `SkuNotAvailable` o `The requested VM size ... is not available` | Ese tamaño no está disponible en esa región para tu suscripción | `az vm list-skus -l <región> --size Standard_B2ats ...`; prueba otra región (p. ej. `southcentralus`) |
| `QuotaExceeded` / `Operation could not be completed as it results in exceeding approved ... Cores quota` | Las cuentas nuevas tienen cuotas bajas por región | Portal > Cuotas (Quotas) > solicita aumento, o cambia de región |
| `cloud-init status` = `error` | El script falló (`docker` no se instaló, sin red) | `cloud-init status --long`; `tail -100 /var/log/cloud-init-output.log /var/log/canaco-bootstrap.log` con Run Command; corrige y ejecuta `/usr/local/sbin/canaco-bootstrap.sh` |
| Apt: `Could not get lock /var/lib/dpkg/lock-frontend` | `unattended-upgrades` activo en el primer arranque | El script espera 300 s (`DPkg::Lock::Timeout`); si falla, repítelo unos minutos después |
| Error 521/522 en Cloudflare | Contenedores caídos, aún arrancando, o el NSG no deja pasar a Cloudflare | `docker compose ps` por Run Command; revisa la regla `allow-cloudflare-web` y que los rangos estén al día |
| Timeout al abrir la IP directa en el navegador | El NSG solo permite Cloudflare: es lo esperado | Prueba por el dominio, o desde la VM con Run Command (`curl -k https://localhost/healthz/`) |
| Error 525/526 | Modo SSL incorrecto o certificado de origen inválido | Usar `Full`; con `Full (strict)` verificar `origin.pem` |
| `CSRF verification failed` o 400 `DisallowedHost` | `DJANGO_CSRF_TRUSTED_ORIGINS`/`ALLOWED_HOSTS` no coinciden con el hostname | Corregir en `.env` (valor de `DOMAIN`) y `docker compose up -d` |
| `docker pull` denegado (`denied` / `unauthorized`) | Paquete GHCR privado | Hacerlo público (Package settings > Change visibility) |
| Contenedores terminados por falta de memoria (`Killed`, `OOM`) | 1 GiB de RAM | Confirmar el swap (`swapon --show`); subir de tamaño (`az vm resize -g "$RG" -n "$VM" --size <tamaño>`, reinicia la VM) |
| `az vm run-command invoke` falla o no devuelve salida | Agente de la VM sin arrancar, sin salida por el 443, o hay otro Run Command en curso | Espera el primer arranque; revisa `az vm get-instance-view`; reintenta |
| `AADSTS70021` / `No matching federated identity record` | El `subject` de la credencial no coincide (repo, entorno o rama) | Compara con `repo:JoryerJL/proyectoweb:environment:production` y corrige con `az ad app federated-credential update` |
| `AuthorizationFailed` al ejecutar el despliegue | El rol no cubre `runCommand/action` o está en otro alcance | Revisa `az role assignment list --assignee <APP_ID>` y el alcance (RG correcto) |
| La alerta del presupuesto no llega | Presupuesto sin correo, o aún no hay datos de costo (hasta ~24 h) | Revisa el recurso `canaco-monthly` y los correos no deseados |

## 15. AWS vs Azure para este proyecto

| Criterio | AWS (`despliegue-ec2.md`) | Azure (esta guía) |
|----------|---------------------------|-------------------|
| Infraestructura como código | CDK (Python) | Bicep (declarativo) o la secuencia de comandos de la CLI |
| Unidad de borrado | Stack de CloudFormation (`cdk destroy`) | Grupo de recursos (`az group delete`) |
| Acceso sin SSH | SSM Session Manager (shell interactivo) | Run Command (solo comandos); el shell interactivo exige Serial Console o Bastion (este último cuesta) |
| Despliegue desde GitHub | OIDC + rol IAM + SSM `send-command` (con sondeo) | OIDC + app registration + RBAC + `az vm run-command invoke` (síncrono) |
| Firewall | Security Group con los CIDR de Cloudflare | NSG con los CIDR de Cloudflare |
| IP fija | Elastic IP | IP pública estática Standard |
| Respaldos | DLM diario, retención de 7, por etiqueta | Instantáneas incrementales (programadas por ti) o Azure Backup |
| Autorrecuperación | Alarma de CloudWatch | Service healing (sin configuración) |
| Etiquetas | Se propagan a EBS | Hay que heredarlas con Azure Policy |
| Costo mensual aprox. | ~13 - 14 USD (t3.micro, us-east-1) | ~15 USD (B2ats_v2 + SSD 32 GiB + IP) |
| Capa gratuita | Según la fecha de creación de la cuenta (ver guía de EC2) | 200 USD por 30 días + 750 h/mes de B1s, B2pts v2 o B2ats v2 por 12 meses |
| Dificultad para un principiante | Media (CDK + bootstrap + IAM) | Media (conceptos nuevos: suscripción, RG, RBAC; la CLI es directa) |

En resumen: la **arquitectura es la misma** (nginx + gunicorn + Postgres en una VM detrás de Cloudflare con el origen cerrado); lo que cambia es el vocabulario y tres detalles prácticos: el grupo de recursos como unidad de todo, Run Command en lugar de SSM interactivo, y heredar etiquetas con una política en vez de depender de la propagación automática.

## Referencias

- [Guía de AWS (EC2)](despliegue-ec2.md)
- [Azure CLI: `az vm create`](https://learn.microsoft.com/cli/azure/vm)
- [Run Command en VM Linux](https://learn.microsoft.com/azure/virtual-machines/linux/run-command)
- [Servicios gratuitos de Azure](https://azure.microsoft.com/pricing/free-services/)
- [Calculadora de precios](https://azure.microsoft.com/pricing/calculator/)
- [Imágenes de Ubuntu en Azure](https://documentation.ubuntu.com/azure/en/latest/azure-how-to/instances/find-ubuntu-images/)
- [Estados y facturación de VM](https://learn.microsoft.com/azure/virtual-machines/states-billing)
- [Políticas integradas de etiquetas](https://learn.microsoft.com/azure/governance/policy/samples/built-in-policies)
- [Plantillas Bicep de Azure](https://learn.microsoft.com/azure/templates/)
