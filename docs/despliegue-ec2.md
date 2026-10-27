# Despliegue en AWS con CDK, Cloudflare y GitHub Actions

La infraestructura de producción se define como código en [`infra/`](../infra/README.md) (AWS CDK en Python). Un solo `cdk deploy` crea la red, la instancia EC2, el rol de GitHub, el presupuesto y los respaldos. Después, cada push a `master` despliega automáticamente por SSM, sin SSH y sin llaves de AWS guardadas en GitHub.

## Ruta rápida

1. **Antes del deploy**: haz push a `master` para que el CI publique la imagen en GHCR y vuelve **público** el paquete `proyectoweb` (la EC2 no compila imágenes: solo las descarga).
2. `cd infra && uv sync && cdk deploy -c budgetEmail=tu@correo.com`
3. Crear en Cloudflare un registro `A` (proxy activado) de `canaco.jjjl.dev` hacia la `ElasticIp` del output.
4. En GitHub: entorno `production` (solo rama `master`) con la variable `AWS_DEPLOY_ROLE_ARN` (output `DeployRoleArn`).
5. Activar las etiquetas de costos (sección FinOps) y confirmar la suscripción del correo del presupuesto.
6. Verificar: `https://canaco.jjjl.dev/healthz/` responde `ok`.

## 1. Arquitectura

```
Visitante
   │ HTTPS
   ▼
Cloudflare (proxy, SSL "Full")
   │ HTTPS 443 (solo IP de Cloudflare)
   ▼
Elastic IP ─► EC2 (Amazon Linux 2023, t3.micro, subred pública, sin NAT)
               └─ Docker Compose (proyecto canaco-prod)
                   ├─ nginx :80/:443 ─► gunicorn (web :8000) ─► PostgreSQL 17 (volumen)
                   └─ certificado autofirmado u Origin CA

GitHub Actions ─ OIDC ─► rol canaco-github-deploy ─► SSM Run Command ─► EC2
Operador ─────── aws ssm start-session ───────────────────────────────► EC2
```

| Decisión | Motivo |
|----------|--------|
| Sin puerto 22 | El acceso y el despliegue usan SSM; no hay llaves SSH que custodiar |
| Security group solo con IP de Cloudflare | Nadie llega al origen sin pasar por Cloudflare |
| Sin NAT ni endpoints | Ahorra costo (un NAT cuesta más que la instancia) |
| Instancia única con Postgres en contenedor | Mínimo costo; los respaldos cubren el riesgo (sección 9) |
| Créditos de CPU `standard` | Evita cargos inesperados de `unlimited` en instancias t3 |
| IMDSv2 obligatorio, disco cifrado gp3 | Línea base de seguridad |
| AMI fijada en `cdk.context.json`, protección contra terminación, disco raíz con `DeleteOnTermination=false` | Una AMI nueva no reemplaza la instancia ni borra PostgreSQL por accidente |

## 2. Requisitos previos

- AWS CLI con credenciales de administrador (solo para el `cdk deploy`) y la cuenta ya inicializada con `cdk bootstrap` (stack `CDKToolkit`).
- CDK CLI y `uv` instalados.
- Dominio en Cloudflare (no se usa Route 53).
- Proveedor OIDC de GitHub ya creado en la cuenta (el stack lo importa). Si tu cuenta no lo tiene, créalo una vez:

  ```bash
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com
  ```
- Imagen ya publicada en GHCR y paquete **público** (GitHub > Packages > `proyectoweb` > Package settings > Change visibility). El orden importa: push a `master` (el CI publica la imagen), volver público el paquete y **después** `cdk deploy`. Sin imagen descargable, el primer arranque deja el stack detenido con un aviso en `/var/log/canaco-bootstrap.log` (nunca compila en la instancia, que tiene 1 GiB de RAM).

## 3. Crear la infraestructura

```bash
cd infra
uv sync
uv run pytest                                  # opcional
cdk deploy -c budgetEmail=tu@correo.com
```

Parámetros opcionales (`-c monthlyBudgetUsd=20 -c instanceType=t3.small ...`): ver [`infra/README.md`](../infra/README.md). Outputs: `ElasticIp`, `InstanceId`, `DeployRoleArn`, `SsmSessionCommand`.

> `budgetEmail` es obligatorio: AWS enviará un correo de confirmación de suscripción; confírmalo para recibir alertas.

## 4. Cloudflare

1. DNS > registro `A`, nombre `canaco`, contenido = `ElasticIp`, **Proxied** (nube naranja).
2. SSL/TLS > modo **Full**. Funciona con el certificado autofirmado que genera nginx.
3. (Opcional, recomendado) **Full (strict)** con un certificado de origen:
   1. SSL/TLS > Origin Server > Create Certificate (hostname `canaco.jjjl.dev`).
   2. En la EC2 (`aws ssm start-session`), guardar los archivos como `/opt/canaco/deploy/certs/origin.pem` y `origin.key` (`chmod 600 origin.key`).
   3. `cd /opt/canaco && docker compose -f docker-compose.prod.yml restart nginx`.
   4. Cambiar el modo a Full (strict). Los archivos en `deploy/certs/` no se versionan.

Las IP reales de los visitantes se leen de `CF-Connecting-IP` (nginx confía solo en los rangos de Cloudflare).

## 5. GitHub

1. Settings > Environments > crear `production`.
2. En ese entorno, agregar la **variable** (no secreto) `AWS_DEPLOY_ROLE_ARN` con el output `DeployRoleArn`.
3. Settings > Actions > General: los permisos por defecto pueden ser de solo lectura; el job de despliegue declara `id-token: write` por sí mismo.
4. **Restringe el entorno a `master`**: Settings > Environments > `production` > Deployment branches and tags > *Selected branches and tags* > `master`. Opcionalmente agrega *Required reviewers*. El rol ejecuta comandos como root en la instancia vía SSM; sin esta restricción, cualquier rama (o pull request del repositorio) que use el entorno podría asumirlo.

Mientras la variable `AWS_DEPLOY_ROLE_ARN` no exista, el job de despliegue se omite sin fallar.

El rol solo confía en tokens de `repo:JoryerJL/proyectoweb:environment:production` y solo puede ejecutar `AWS-RunShellScript` en instancias con la etiqueta `Project=canaco`. Si cambias el nombre del repositorio o del entorno, vuelve a ejecutar `cdk deploy -c githubRepo=...`.

## 6. Primer arranque

El `user data` instala Docker, Compose v2 y git, crea 2 GiB de swap, clona el repositorio en `/opt/canaco`, genera `/opt/canaco/.env` con secretos aleatorios (solo si no existe) y levanta el stack. Tarda unos minutos.

```bash
aws ssm start-session --target <InstanceId>      # output SsmSessionCommand
sudo tail -f /var/log/canaco-bootstrap.log
sudo docker compose -f /opt/canaco/docker-compose.prod.yml ps
```

El `user data` solo corre una vez. Por `user_data_causes_replacement=False`, modificarlo en el stack **no reemplaza** la instancia (no se pierde la base de datos), pero tampoco se reejecuta: aplica los cambios manualmente por SSM.

Después de crear la instancia, hacer un primer despliegue (push a `master` o `Re-run` del workflow) fija `IMAGE_TAG` en `.env`.

### Crear el superusuario y datos de ejemplo

```bash
aws ssm start-session --target <InstanceId>
cd /opt/canaco
sudo docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
sudo docker compose -f docker-compose.prod.yml exec web python manage.py seed_news   # opcional
```

## 7. Despliegues y rollback

El job `deploy` (solo en `master`) asume el rol por OIDC, localiza la instancia por etiquetas (`Project=canaco`, `Environment=prod`), ejecuta por SSM `git pull`, escribe `IMAGE_TAG=<sha corto>` en `.env`, hace `pull` y `up -d`, y prueba `/healthz/`. Como la versión queda en `.env`, un reinicio conserva la misma imagen.

**Rollback**: por SSM, `cd /opt/canaco`, cambiar `IMAGE_TAG` en `.env` a un SHA anterior (existe una imagen por commit en GHCR) y ejecutar `docker compose -f docker-compose.prod.yml up -d`. Si el código de `master` también debe volver atrás, revierte el commit y deja que el flujo despliegue.

## 8. FinOps

### Etiquetas

Todas se aplican al stack completo (`Tags.of(app)`); se propagan al volumen EBS.

| Etiqueta | Valor | Significado |
|----------|-------|-------------|
| `Project` | `canaco` | Agrupa el costo del proyecto; filtra el presupuesto y el despliegue |
| `Application` | `canaco-web` | Componente de aplicación |
| `Environment` | `prod` | Ambiente |
| `Owner` | `joryer` | Responsable |
| `CostCenter` | `m4-proyectoweb` | Centro de costo |
| `ManagedBy` | `cdk` | Indica que no se edita a mano |
| `Repository` | `github.com/JoryerJL/proyectoweb` | Origen del código |
| `Backup` | `daily` | Solo instancia/volumen; lo selecciona la política DLM |

**Activar las etiquetas de costos** (solo aparecen después de crear los recursos y pueden tardar hasta 24 horas en estar disponibles):

```bash
aws ce update-cost-allocation-tags-status --cost-allocation-tags-status \
  TagKey=Project,Status=Active TagKey=Environment,Status=Active TagKey=CostCenter,Status=Active
```

Sin activar `Project`, el presupuesto no verá costos y no alertará.

### Presupuesto

`canaco-monthly`: presupuesto de costo mensual (por defecto 15 USD) filtrado por `user:Project$canaco`. Envía correo a `budgetEmail` al 80 % del gasto real y al 100 % del gasto pronosticado. Los respaldos DLM y la alarma de CloudWatch (1 alarma, dentro de las 10 gratuitas) llevan la misma etiqueta.

### Estimación mensual (us-east-1, aproximada)

Precios de lista bajo demanda; verifícalos en la [calculadora de AWS](https://calculator.aws/) antes de decidir.

| Concepto | Cálculo | USD/mes |
|----------|---------|---------|
| EC2 t3.micro | 0.0104 USD/h × 730 h | 7.59 |
| EBS gp3 20 GiB | 0.08 USD/GiB-mes | 1.60 |
| IPv4 público (Elastic IP) | 0.005 USD/h × 730 h | 3.65 |
| Snapshots DLM (7, incrementales) | ~0.05 USD/GiB-mes, pocos GiB | 0.50 - 1.00 |
| Transferencia de salida | Primeros 100 GiB/mes gratis; Cloudflare cachea estáticos | ~0 |
| CloudWatch (1 alarma), Budgets (1), SSM | Dentro de la capa gratuita | 0 |
| **Total** | | **~13 - 14** |

Por eso el presupuesto por defecto es 15 USD: con 10 USD la alerta de pronóstico se dispararía desde el primer día.

### Capa gratuita

- Cuentas creadas **antes del 15 de julio de 2025**: 750 h/mes de t2/t3.micro durante 12 meses (la IPv4 pública se cobra aparte).
- Cuentas creadas **a partir de esa fecha**: plan gratuito basado en créditos (alrededor de 100 USD, ampliables a 200 USD con tareas de inicio), válido hasta agotarlos o por 6 meses; el uso de EC2 descuenta de esos créditos. Esta información proviene de fuentes de terceros; confirma las condiciones de tu cuenta en la consola de Billing.

### Palancas de ahorro

| Palanca | Efecto | Costo |
|---------|--------|-------|
| Detener la instancia fuera de uso | Deja de cobrar cómputo; el EBS y la IPv4 se siguen cobrando | La app queda fuera de línea |
| t4g.micro (Graviton) | ~20 % más barato | Requiere imagen `linux/arm64` en CI y `-c instanceType` (el stack hoy usa x86_64) |
| Savings Plan / Reserved (1 año) | Hasta ~30 - 40 % menos en cómputo | Compromiso de pago |
| Reducir retención DLM o el disco | Menos GiB de snapshots | Menor historial |

## 9. Respaldos

- **Snapshots EBS** diarios (03:00 UTC) con retención de 7, por la política DLM sobre volúmenes con `Backup=daily`.
- **Volcado lógico** de PostgreSQL (recomendado antes de cambios grandes):

```bash
cd /opt/canaco
sudo docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U canaco canaco | gzip > ~/canaco-$(date +%F).sql.gz
```

Restaurar: `gunzip -c archivo.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U canaco canaco`.
Los archivos subidos viven en el volumen `media_files` y también quedan en los snapshots.

La alarma `StatusCheckFailed_System` recupera automáticamente la instancia (misma IP y disco) si falla el hardware subyacente.

## 10. Eliminar todo

```bash
cd infra && cdk destroy -c budgetEmail=tu@correo.com
```

La instancia tiene protección contra terminación: primero desactívala (`aws ec2 modify-instance-attribute --instance-id <id> --no-disable-api-termination`) o `cdk destroy` fallará. Se eliminan la VPC, la instancia, la Elastic IP, el rol de despliegue, el presupuesto y la política DLM.

**Se conservan** (y cobran hasta que los borres a mano):

| Recurso retenido | Costo aproximado | Cómo borrarlo |
|------------------|------------------|---------------|
| Volumen raíz EBS (contiene la base de datos; `DeleteOnTermination=false`) | ~1.60 USD/mes (20 GiB gp3) | `aws ec2 delete-volume --volume-id <id>` (hazle un respaldo antes si lo necesitas) |
| Snapshots ya creados | ~0.05 USD/GiB-mes | `aws ec2 delete-snapshot` |

Tampoco se tocan el proveedor OIDC (no lo creó el stack), el bootstrap `CDKToolkit` ni el registro DNS en Cloudflare, que debes borrar a mano.

## 11. Actualizar la AMI a propósito

La AMI de Amazon Linux 2023 queda fijada en `infra/cdk.context.json` (clave `ssm:account=...:parameterName=/aws/service/ami-amazon-linux-latest/...`). Un `cdk deploy` nunca la cambia solo. Para actualizar de forma deliberada:

1. Respalda la base de datos (sección 9) y verifica que exista un snapshot reciente.
2. Desactiva la protección contra terminación (`aws ec2 modify-instance-attribute --instance-id <id> --no-disable-api-termination`): CloudFormation necesita borrar la instancia anterior. Luego `cd infra && cdk context --reset <número o clave de la entrada ssm>` y `cdk deploy -c budgetEmail=...`.
3. Cambiar la AMI **reemplaza la instancia**: el volumen raíz anterior se conserva (sin borrar) pero el nuevo arranca vacío; restaura el volcado de PostgreSQL y revisa que la Elastic IP se reasocie. Borra el volumen viejo cuando termines.

Para evitar el reemplazo en el futuro, aplica parches dentro de la instancia (`sudo dnf upgrade`) en lugar de cambiar la AMI.

## 12. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| Error 521/522 en Cloudflare | Contenedores caídos o aún arrancando | `docker compose ps` y revisar `/var/log/canaco-bootstrap.log` |
| Error 525/526 | Modo SSL incorrecto o certificado de origen inválido | Usar `Full`; con `Full (strict)` verificar `origin.pem` |
| `docker pull` denegado | Paquete GHCR privado | Hacerlo público |
| `CSRF verification failed` | `DJANGO_CSRF_TRUSTED_ORIGINS` incorrecto | Corregir en `.env` y `up -d` |
| Despliegue: `AccessDenied` en `AssumeRoleWithWebIdentity` | Falta el entorno `production` o la variable | Revisar la sección 5 |
| Despliegue: no encuentra la instancia | Instancia detenida o sin etiquetas | Iniciarla; verificar `Project=canaco` |
| `aws ssm start-session` falla | Falta el plugin o el agente no está en línea | Instalar `session-manager-plugin`; esperar el primer arranque |
| El presupuesto no alerta | Etiqueta `Project` sin activar | Sección 8 |
| Contenedores terminados por falta de memoria | 1 GiB de RAM | Usar `-c instanceType=t3.small` |
