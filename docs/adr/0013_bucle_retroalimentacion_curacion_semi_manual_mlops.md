# ADR 0013: Bucle de Retroalimentación Activa (RF_06) con Curación Semi-Manual Human-in-the-Loop

* **Estado:** Aceptado  
* **Fecha:** 2026-09-27  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** MLOps, Calidad de Datos, Arquitectura de Software Backend/Frontend e Inferencia Bioacústica  

---

## 1. Contexto y Problema

El Requerimiento Funcional **RF_06 (Retroalimentar predicción errónea / CU_INV_07)** de la memoria de título exige que los investigadores puedan validar o corregir en tiempo real las clasificaciones acústicas emitidas por los modelos de IA desplegados en la plataforma.

Al conectar este ciclo de retroalimentación con los subsistemas de entrenamiento, surge una disyuntiva de diseño crítica:

1. **Riesgo de Inyección Automática Ciega (*Data Poisoning*):**  
   Si cada audio con retroalimentación se volcara inmediatamente y sin supervisión en la carpeta de entrenamiento (`train/`), el sistema quedaría expuesto a degradación catastrófica:
   * Subida de audios accidentales, corruptos, grabaciones mudas o ruido no taxonómico.
   * Errores humanos involuntarios de digitación o clasificación.
   * Desbalance artificial severo que sesgaría las distribuciones de probabilidad de la red.
2. **Violación de Estratificación y Fuga de Datos (*Data Leakage*):**  
   El pipeline de entrenamiento de F.A.M.A ([`training.py`](../../backend/app/services/training.py)) no utiliza carpetas estáticas `train/` y `test/`. Aplica una partición matemática estratificada por grupos ([`grouped_stratified_split`](../../backend/poc/split.py)) sobre `metadata.csv` para asegurar que grabaciones de un mismo individuo acústico o sesión de campo no se filtren entre entrenamiento y validación.

---

## 2. Decisión Arquitectónica

Se aprueba formalmente implementar un **Bucle de Retroalimentación Activa en Dos Etapas** gobernado por el principio de **Curación Humana Supervisada (*Human-in-the-Loop MLOps*)**:

```
┌─────────────────────────────────┐
│ 1. Inferencia (PredictionView)  │ ──► POST /api/feedback (RF_06)
│    • Botón Validar (Acierto)    │       • Persiste en PostgreSQL (procesado=False)
│    • Botón Corregir (Nueva esp.)│       • Copia a GCS gs://<bucket>/feedback/<etiqueta>/
└─────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────┐
│ 2. Curación (IngestionView)                            │
│    Bandeja de auditoría de audios pendientes:          │
│    • [▶ Reproducir Audio]                              │
│    • [Aprobar]: Incorpora a raw/ + metadata.csv        │
│                 y marca procesado=True.                │
│    • [Descartar]: Rechaza ruido/accidentes sin         │
│                   alterar el dataset de train.         │
└────────────────────────────────────────────────────────┘
```

### 2.1 Etapa 1: Captura Rápida en Inferencia (RF_06)
* **Frontend ([`PredictionView.tsx`](../../frontend/components/views/PredictionView.tsx)):**  
  Inmediatamente después de ejecutar una inferencia, la tarjeta de resultado expone:
  * Botón `[Validar]`: Confirma la predicción (`fue_correcta = true`).
  * Botón `[Corregir]`: Despliega un selector con las clases oficiales del modelo activo (15 especies o 13 fallas de motor) y registra la corrección (`fue_correcta = false, etiqueta_corregida = ...`).
* **Backend ([`POST /api/feedback`](../../backend/app/main.py)):**  
  Persiste en PostgreSQL (tabla `retroalimentacion`) vinculada a la `prediccion` con el estado **`procesado = False`**, y despacha una copia de seguridad a GCS en la carpeta de cuarentena:
  `gs://<bucket>/feedback/<etiqueta_corregida>/<filename>`

### 2.2 Etapa 2: Bandeja de Curación y Auditoría Semi-Manual
* **Frontend ([`IngestionView.tsx`](../../frontend/components/views/IngestionView.tsx)):**  
  Se implementa un panel de curación conectado al servicio de ingesta y datasets:
  * Lista los audios con feedback pendiente (`procesado == False`).
  * Permite escuchar el audio y comparar la hipótesis del modelo versus la corrección del usuario.
* **Operaciones de Curación en Backend:**
  * `POST /api/feedback/{id}/approve`: Valida formalmente el audio, lo mueve canónicamente a `backend/data/raw/<dataset>/<etiqueta_corregida>/<filename>`, actualiza las entradas en `metadata.csv` y actualiza la fila a `procesado = True`.
  * `POST /api/feedback/{id}/reject`: Marca el registro como descartado/procesado sin transferir el audio al dataset, neutralizando cualquier intento de contaminación.

---

## 3. Consecuencias y Beneficios

* **Cumplimiento 100% de la Tesis:** Cierra formalmente el requerimiento **RF_06** y completa el objetivo específico **OE3 / OE4** (ciclo de mejora continua nube-local).
* **Inmunidad contra Envenenamiento de Datos:** Los datos de campo pasan por una compuerta estricta de aprobación antes de formar parte del conjunto de entrenamiento oficial.
* **Preservación Metodológica:** Los nuevos audios aprobados se integran armónicamente en el proceso de partición `grouped_stratified_split`, manteniendo libre de sesgos y fugas el cálculo de métricas de generalización (F1 Macro).
