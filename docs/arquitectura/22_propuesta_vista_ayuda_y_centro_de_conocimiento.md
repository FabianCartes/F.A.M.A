# Propuesta y Especificación: Vista de Ayuda y Centro de Conocimiento F.A.M.A. (`HelpView`)

**Estado:** `[PENDIENTE / BACKLOG]`  
**Fecha de Registro:** 27 de Septiembre de 2026  
**Módulo Destino:** `frontend/components/views/HelpView.tsx`  
**Referencia:** Requerimiento de Usuario — Guía Teórica, Operativa y Soporte en Plataforma

---

## 1. Visión y Objetivos

La **Vista de Ayuda y Centro de Conocimiento** (`HelpView`) tiene como propósito consolidar la documentación técnica, pedagógica y operativa directamente en la interfaz de usuario de F.A.M.A. 

F.A.M.A. no es un clasificador genérico, sino un **Framework Acústico Multi-dominio Adaptable** de grado industrial y científico. La vista de ayuda debe eliminar la brecha entre el usuario final (guardaparques, mecánicos, investigadores) y la complejidad matemática/computacional del sistema (MLOps, PyTorch, GeM Pooling, ensamble bayesiano).

---

## 2. Estructura de Subsecciones Propuesta

La vista se organizará modularmente en 4 secciones accesibles mediante navegación interna (pestañas o menú lateral de navegación rápida):

```
┌────────────────────────────────────────────────────────────────────────┐
│ Centro de Ayuda y Conocimiento F.A.M.A.                                │
├──────────────┬─────────────────────────────────────────────────────────┤
│ [1. Conceptos] │ 1. Conceptos de Machine Learning y Acústica Computacional│
│ [2. F.A.M.A.]  │ 2. Misión, Alcance y Objetivos de la Plataforma        │
│ [3. Funciones] │ 3. Manual Interactivo de Módulos y Funcionalidades     │
│ [4. Soporte]   │ 4. Diagnóstico, Telemetría y Canales de Soporte         │
└──────────────┴─────────────────────────────────────────────────────────┘
```

---

### Subsección 1: Conceptos de Entrenamiento y Machine Learning Acústico
*Objetivo:* Explicar con rigor pedagógico y claridad conceptual qué ocurre debajo del capó durante el preprocesamiento y entrenamiento.

1. **El Dominio Tiempo-Frecuencia (Espectrogramas Mel):**
   - Cómo se convierte una onda de presión sonora unidimensional (.wav) en una representación matricial bidimensional mediante STFT (Short-Time Fourier Transform).
   - Escala Mel y su correspondencia con la percepción coclear y auditiva.
   - Ventanas temporales: diferencias entre audios bioacústicos (5.0s @ 22.050 Hz) y mecánicos (1.5s/2.0s @ 32.000 Hz).

2. **Aumento de Datos en Espectrogramas (Data Augmentation):**
   - **VAD (Voice/Sound Activity Detection):** Detección de tramos activos de energía acústica descartando silencios inertes.
   - **Mixup Acústico:** Combinación lineal convexa de espectrogramas y etiquetas para regularizar fronteras de decisión y evitar sobreajuste.
   - **Mezcla Aditiva de Fondo (Additive Noise) & Balanceo RMS:** Inserción de ruido ambiente calibrado por energía cuadrática media para robustez en campo.
   - **Pitch Shift Espectral:** Variación tonal en GPU sin alterar duración temporal.

3. **Arquitecturas Neuronales Empleadas:**
   - **EfficientNet-B0:** Escalado compuesto balanceado (profundidad, ancho y resolución espectral).
   - **ConvNeXt-Nano:** Arquitectura convolucional modernizada con principios de Transformers visuales.
   - **ResNet-34d:** Red residual profunda con tallo modificado (anti-aliasing) óptima para patrones armónicos.
   - **PANNs-CNN14:** Redes convolucionales preentrenadas en AudioSet para sonidos industriales.

4. **GeM Pooling (Generalized Mean Pooling):**
   - Qué es y por qué supera al Average Pooling y Max Pooling en audio: permite a la red aprender a enfatizar armónicos salientes mientras ignora el ruido de fondo difuso mediante un parámetro $p$ entrenable.

5. **Funciones de Pérdida y Métricas:**
   - **Focal Loss:** Enfoque en ejemplos difíciles, atenuando el gradiente de muestras fácilmente clasificables ante desbalance de clases.
   - **F1-Score Macro vs. Accuracy:** Por qué en bioacústica y fallas raras el F1-Macro es la métrica de la verdad, evitando sesgos por clases dominantes.

6. **Super-Ensambles y Ponderación Bayesiana:**
   - Fusión de probabilidades a posteriori mediante combinación lineal convexa calibrada, explotando la complementariedad de las diferentes arquitecturas.

---

### Subsección 2: Objetivo y Misión de F.A.M.A.
*Objetivo:* Detallar el propósito de la plataforma, su diseño arquitectónico y sus dominios de aplicación.

1. **Misión del Proyecto:**
   - Proveer una plataforma integral de monitoreo acústico distribuido, open-source y soberana, libre de cajas negras propietarias.
2. **Los Dos Dominios de F.A.M.A.:**
   - **Bioacústica (Aves Chilenas):** Monitoreo pasivo de biodiversidad en bosques templados australes (15 especies prioritarias como Chucao, Turca, Rayadito, etc.).
   - **Diagnóstico Industrial (Motores Vehiculares):** Clasificación predictiva de 13 condiciones y fallas mecánicas críticas (falla de encendido, desgaste de frenos, nivel bajo de aceite, correa de accesorios, etc.).
3. **Pilares de Arquitectura:**
   - **Modularidad:** Separación limpia entre Ingesta, Entrenamiento, Catálogo de Modelos (Model Registry) e Inferencia.
   - **Trazabilidad:** Persistencia dual en PostgreSQL (metadatos e historial de inferencia) y Google Cloud Storage (audios originales y cuarentena de reentrenamiento).
   - **Human-in-the-Loop:** Curación semi-manual de datos de campo (RF_06).

---

### Subsección 3: Manual de Módulos y Funcionalidades
*Objetivo:* Servir de referencia práctica para cada pantalla y control de la aplicación.

1. **Dashboard General:**
   - Métricas globales en vivo (total audios, datasets, modelos activos).
   - Estado de salud de microservicios e infraestructura (FastAPI, GCS, PostgreSQL, Acelerador GPU/CUDA).
2. **Ingesta y Curación de Datos:**
   - Carga y validación de archivos .wav (detección de clipping, frecuencia y duración).
   - **Bandeja de Curación de Feedback (RF_06):** Cómo evaluar correcciones de campo, aprobarlas (incorporación canónica al dataset) o descartarlas.
3. **Entrenamiento de Modelos:**
   - Selección de dataset y modo (Modelo Individual vs. Dúo vs. Tríada Completa).
   - Ajuste de hiperparámetros (Batch size, Epochs, Learning Rate, Framework PyTorch).
   - **Física de Audio y Espectrograma:** Explicación de tasa de muestreo ($f_s$), duración de ventana, límites espectrales ($f_{\text{min}}, f_{\text{max}}$ y Nyquist), resolución Mel/STFT, ventaneo denso (`hop_seconds`), exponente GeM Pooling ($p$) y regularizaciones (Mixup, Pitch Shift).
   - **Ayudas Contextuales (Tooltips In-App):** Iconos de interrogación `(?)` junto al nombre de cada parámetro acústico que muestran en *hover/focus* un resumen didáctico de su función y un enlace para profundizar en el Centro de Ayuda.
   - Monitor de telemetría de hardware (temperatura, uso de VRAM y CPU).
4. **Predicción y Monitoreo:**
   - Selector dinámico de modelo con agrupación semántica (`<optgroup>`).
   - Contratos acústicos de inferencia automáticos.
   - Oscilograma y visor interactivo de forma de onda diezmado en 160 ventanas con métricas RMS y Peak dBFS.
   - Bucle de retroalimentación activa (validar acierto o sugerir corrección experta).

---

### Subsección 4: Diagnóstico, Telemetría y Soporte
*Objetivo:* Guiar en la resolución de incidencias y ofrecer canales de contacto y soporte técnico.

1. **Requisitos Técnicos de Audio para Inferencia:**
   - Formato requerido: `.wav` sin compresión destructiva (PCM 16 o 24 bits).
   - Frecuencia sugerida: 22.050 Hz (Bioacústica) / 32.000 Hz (Industrial).
   - Canales: Mono o estéreo (convertido automáticamente en frontend/backend).
2. **Diagnóstico Rápido de Errores Comunes:**
   - *Backend Desconectado:* Verificación de `API_BASE_URL` y puerto 8000.
   - *Acelerador en modo CPU Host:* Verificación del runtime CUDA y drivers NVIDIA.
   - *GCS Desconectado:* Configuración de credenciales de servicio `GOOGLE_APPLICATION_CREDENTIALS`.
3. **Endpoints de Autodiagnóstico:**
   - `/api/health`: Estado de conectividad integral.
   - `/api/training/hardware`: Telemetría de hardware y memoria GPU.
   - `/api/models`: Inspección del catálogo dinámico.
4. **Contacto y Mesa de Ayuda:**
   - Repositorio oficial, registro de incidencias (*Issue Tracker*) y equipo de ingeniería acústica de F.A.M.A.

---

## 3. Plan de Implementación (Backlog)

* **Tarea 1:** Crear `frontend/components/views/HelpView.tsx` siguiendo diseño modular con subnavegación por tabs.
* **Tarea 2:** Integrar opción `Ayuda` en [`Sidebar.tsx`](file:///home/kevin/Work/fama/frontend/components/Sidebar.tsx) y conectar estado de vista en [`AppShell.tsx`](file:///home/kevin/Work/fama/frontend/components/shell/AppShell.tsx) / [`page.tsx`](file:///home/kevin/Work/fama/frontend/app/page.tsx).
* **Tarea 3:** Desarrollar suite de pruebas TDD en `frontend/components/views/__tests__/HelpView.test.tsx` (asegurando renderizado de las 4 secciones y navegación sin errores).
* **Tarea 4:** Validar accesibilidad (`aria-selected`, navegación por teclado) y diseño responsivo móvil/escritorio.
* **Tarea 5:** Implementar componente de ayuda contextual (`TooltipHelp` / icono `?`) junto a cada parámetro del panel de Física de Audio en `TrainingView.tsx`, con explicación concisa en hover y enlace al Centro de Ayuda.

