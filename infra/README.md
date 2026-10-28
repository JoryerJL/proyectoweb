# Infraestructura de Canaco (AWS CDK, Python)

Define el stack `CanacoProdStack` en `us-east-1`: VPC pública sin NAT, una EC2 con Elastic IP, rol de despliegue para GitHub (OIDC), presupuesto, respaldos DLM y alarma de recuperación. Guía completa: [`../docs/despliegue-ec2.md`](../docs/despliegue-ec2.md).

## Ruta rápida

```bash
cd infra
uv sync                                   # instala dependencias
uv run pytest                             # pruebas de la infraestructura
cdk synth  -c budgetEmail=tu@correo.com   # solo genera la plantilla
cdk deploy -c budgetEmail=tu@correo.com   # crea los recursos (genera costos)
```

## Parámetros (`-c clave=valor`)

| Parámetro | Por defecto | Notas |
|-----------|-------------|-------|
| `budgetEmail` | (obligatorio) | Recibe las alertas del presupuesto; sin él, `synth` falla |
| `instanceType` | `t3.micro` | Debe ser x86_64 y de tipo burstable (créditos `standard`) |
| `domain` | `canaco.jjjl.dev` | Se usa en `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` |
| `repoUrl` | repositorio público en GitHub | Se clona en `/opt/canaco` |
| `githubSubPrefix` | `repo:JoryerJL@146901957/proyectoweb@1380498266` | Prefijo del claim `sub` autorizado en el rol OIDC (formato inmutable con IDs; se consulta con `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`) |
| `monthlyBudgetUsd` | `15` | Presupuesto mensual filtrado por la etiqueta `Project=canaco` |
| `owner` / `costCenter` | `joryer` / `m4-proyectoweb` | Etiquetas FinOps |

## Notas importantes

- El `user data` solo se ejecuta en el primer arranque. Está configurado con `user_data_causes_replacement=False`: editarlo no reemplaza la instancia (y no pierde la base de datos), pero tampoco se vuelve a ejecutar.
- El proveedor OIDC de GitHub ya existe en la cuenta y se importa, no se crea.
- `aws-cdk-lib` está fijado a una versión compatible con el CLI instalado (`cdk --version` 2.1128.x). Si actualizas el CLI, puedes subir la librería.
- Las IP de Cloudflare están en `canaco_infra/cloudflare_ips.py`; mantenlas sincronizadas con `deploy/nginx/cloudflare-realip.conf`.
- `cdk.context.json` se versiona a propósito: fija la AMI (evita reemplazar la instancia por una AMI nueva) y las zonas de disponibilidad. Contiene el ID de la cuenta (no es un secreto). La instancia tiene protección contra terminación y su disco raíz no se elimina al destruirla (ver guía, sección 10).
