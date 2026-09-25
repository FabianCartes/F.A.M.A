# Problema Conocido 03: Mejoras Posibles al Modelo de Predicción más allá del 88.68% F1

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Agosto 2026  
**Área:** Optimización de Modelos, Estado del Arte Bioacústico 2025–2026 y Roadmap de Mejoras  
**Dominio:** 15 Especies de Aves de Chile (Dataset Xeno-canto v3, 1206 audios)  
**Evidencia Empírica:** Auditoría de pipeline + dataset + revisión SOTA (BirdCLEF 2024–2026, Perch 2.0, BirdMAE, BirdSet)  
**Estado:** Ruta de Mejora Caracterizada y Priorizada por Ganancia Esperada  

---

## 1. Punto de Partida: Qué se Tiene Hoy y Por Qué Cuesta Mejorar

El récord vigente de F.A.M.A. es el **Super-Ensamble Tri-Modelo Heterogéneo** con **88.68% Macro F1 / 88.31% Accuracy (136/154)** sobre `data/test.csv`, bajo ventaneo denso (`hop 1.0s`, TTA `max`) y pesos calibrados `[ConvNeXt-Nano 0.30, EfficientNet-B0 0.55, ResNet34d 0.15]` (ver `docs/16_informe_maestro_super_ensamble_fama.md`).

| # | Checkpoint en `checkpoints/` | Backbone | Pooling | Val acc | Params |
|:---|:---|:---|:---|:---:|:---:|
| 1 | `convnext_nano_35e_best.pt` | `convnext_nano.d1h_in1k` | GeM p=3.0 | 93.16% | ~15.0M |
| 2 | `efficientnet_gpu_pipeline_35e_best.pt` | `efficientnet_b0` | GAP | 84.61% | ~4.1M |
| 3 | `resnet34d_35e_best.pt` | `resnet34d` | GeM p=3.0 | 88.88% | ~21.3M |
| **Total ensamble** | — | 3 familias ortogonales | Late Fusion | — | **~40.4M** |

Pipeline canónico: audio mono 22.05 kHz → ventanas 5 s con VAD relativo (`top_db=25`, `hop 2.5s` en train / `1.0s` en inferencia) → Mel 128 bandas (`f_min=800`, `f_max=10000`) → z-norm por instancia → `SpecAugment (freq 8, time 16)` + `Mixup (α=0.2, p=0.5)` + waveform `time-shift/gain/ruido` → `FocalLoss γ=2.0` → warmup 3 épocas congelado + `AdamW`.

La consecuencia directa: a 88.68% el proyecto está en **rendimientos decrecientes**. Cada técnica adicional aporta +0.5 a +5pp, no +20pp. El headroom residual se concentra en tres clases (`docs/16`, F1 campeón vs 100%):

| Clase | F1 campeón | Headroom | n test | Lectura |
|:---|:---:|:---:|:---:|:---|
| Churrín del sur | 80.0% | 20.0pp | 5 | Soporte mínimo, frontera inestable |
| Zorzal patagónico | 81.0% | 19.0pp | 21 | Fuga residual hacia Tordo |
| Tapaculo | 82.4% (R 70%) | 17.6pp | 10 | Recall bajo, precisión 100% |
| Picaflor / Chucao / Fío-fío | 83–85% | 15–17pp | 6–14 | Cola ruidosa (calidad B 43–53%) |

Los pares crípticos clásicos (Tijeral↔Canastero, Fío-fío↔Zorzal, Colilarga dispersa) ya están >84% gracias al ensamble heterogéneo; el residuo es **cola de baja muestra + desbalance + val ruidoso** (val = 117 muestras; Turca y Picaflor con solo 3 muestras en val), no un colapso arquitectónico.

Dos deudas estructurales limitan cualquier mejora si no se corrigen antes:

1. **Producción desincronizada ~27pp por detrás del lab.** `backend/app/main.py` sirve `AudioCNN 0.36M` (`augmented_best.pt`) con Mel-64 single-crop, sin TTA ni ensamble.
2. **Deuda `n_mels` 64/128.** Defaults CPU 64 (`train.py:65`, `preprocess.py:157`) vs GPU 128 (`train.py:618`). Un `--n-mels` mal pasado degrada en silencio.

---

## 2. Línea 1 — Higiene y Calibración sin Reentrenar (+0.5–1.5pp, costo 0)

El paso de mayor retorno por hora invertida, previo a cualquier reentrenamiento:

1. **Unificar `n_mels=128` en un solo config** y eliminar el path CPU-64 legacy.
2. **Cachear ventanas VAD** en RAM/offline: hoy cada `__getitem__` re-ejecuta `librosa.load` + VAD; solo el Mel está en GPU.
3. **Singleton de `GPUAudioFrontEnd`** en inferencia (hoy se instancia por archivo).
4. **Recalibrar Temperature Scaling para el tri-ensamble** (el T=1.5 actual es del AudioCNN viejo) y **optimizar thresholds por especie a F1** sobre val.
5. **Probar `hop 0.5s`**: el paso 2.5→1.0s dio +0.62pp; 1.0→0.5s puede dar +0.3–0.5pp a costa de 2x latencia.

---

## 3. Línea 2 — Loss y Pooling (+2–5pp, 2–3 días GPU)

### 3.1 Función de pérdida: ASL > Focal-BCE >> Balanced Softmax

Para ventanas 5 s el problema no es solo frecuencia de clase, es el **desbalance positivo-negativo ~1:100 por clip**:

* **ASL** (Ridnik et al., ICCV 2021): desacopla `γ+ ≠ γ-` con hard-threshold `m` sobre negativos. En reporte BirdCLEF 2026: `ASL (γ-=4, γ+=0)` supera a BCE en +2.3pp AUC de validación. SOTA COCO 86.6% mAP.
* **Focal-BCE (γ=2)**: la usada por el 2.º puesto BirdCLEF 2025 en producción. Cambio de 1 línea desde BCE, +2–4pp en cola.
* **Balanced Softmax / CBS (2026)**: solo si el head se mantiene single-label exclusivo por clip.
* **LDAM, Seesaw**: descartados para este régimen (requieren val grande o son de detección, sin adopción en audio/BirdCLEF).

**Recomendación FAMA:** multi-label → `ASL (γ+=0, γ-=4, m=0.05)`; single-label → `BalancedSoftmax` o `Focal CE γ=1–2`. Ganancia esperada **+2–4pp F1 en cola**.

### 3.2 Pooling: Attentive > GeM > Avg (+0.5–5pp)

La ventana 5 s suele contener <1 s útil; el promedio global diluye el canto:

* Review 2025 (`arXiv:2508.01277`): AudioMAE pasa de 84.47 → 97.19 con attentive probing (+12.7pp); BEATs 72.70 → 82.28 (+9.6pp).
* BirdMAE (2025): prototypical pooling +37pp mAP sobre linear con 20% de parámetros.
* MQMHA (2025, SER): +3.5pp macro-F1 sobre avg; el 15% de frames concentra el 80% de información.

**Recomendación FAMA:** reemplazar `AdaptiveAvgPool2d` por `AttentiveStatsPool 1-head` (media + desviación ponderadas por atención + LayerNorm + Dropout 0.3–0.5). Empezar con 1 head por tener solo ~1200 audios. GeM p=3.0 aprendible queda como fallback barato y seguro.

---

## 4. Línea 3 — Salto Arquitectónico: Backbone Bioacústico (+5–15pp, la mayor palanca)

**No entrenar desde ImageNet es la decisión de mayor impacto.** Con 50–170 audios/clase, el fine-tuning completo de un ViT grande sobreajusta; la receta SOTA 2026 es **backbone bioacústico congelado + linear/prototypical probing**.

| Modelo | Paper / Año | Idea clave | Métrica BirdSet | Aplicabilidad FAMA | Costo |
|:---|:---|:---|:---|:---|:---|
| **Perch 2.0** (recomendado) | Denton et al., Google, `arXiv:2508.04665`, 2025 | EfficientNet-B3 ~12M, 14795 especies, self-distillation + prototype classifier. Diseñado para linear probing | **SOTA: AUROC 0.908, cmAP 0.431** sin FT | **Alta** — XC nativo, ideal 50–170/clase | Baja: T4 / CPU para el head |
| **BirdMAE-L** | Rauch et al., `arXiv:2504.12880`, 2025 | ViT MAE pre-entrenado en dominio XCL-1.6M + prototypical pooling | SOTA SSL FT (POW 55.3 MAP), frozen + proto ~FT−3pp | Alta con GPU, media sin GPU | Alta: L4/A10 24GB, 300M params |
| **ConvNeXt-BS / BirdNext** | Rauch et al., BirdSet, 2024–25 | ConvNeXt supervisado en XCL, reemplazo abierto de Perch | Competitivo en linear probing | Alta — 100% abierto y entrenable | Media: RTX3060/T4 |
| **BirdNET v2.4** | Kahl et al., 2021/v2.4 2024 | Baseline CPU citizen-science | Inferior (PR-AUC 0.07 vs Perch 0.12 en Amazon 2026) | Media — detector upstream | Muy baja |
| AVES / BEATS / EAT / AudioMAE | 2022–2024 | Backbones generales o de voz | Caen vs Perch/BirdMAE en bioacústica salvo post-train (receta AVEX 2025) | Baja–media | Media–alta |

**Recomendación FAMA en 2 pasos:** (1) `Perch 2.0 frozen → head logístico/MLP 2 capas + prototypical probe` (1 día, CPU/T4); (2) solo con L4/A10, probar `BirdMAE-L + prototypical probing`. **No hacer:** FT completo ViT-H, NatureLM-audio, ni buscar "Distil-AVES"/"AudioMAE-v2" (no existen como tal para este caso).

**Advertencia física:** Perch/BirdNET esperan **32 kHz / 60 Hz–16 kHz**; FAMA recorta a 22.05 kHz / 800 Hz–10 kHz (ver Problema Conocido 02, §2.3). Migrar a 32 kHz (`n_fft 2048, hop 512`, 128 mels) recupera 11–16 kHz: +1–2pp si hay insectos/agudos, +0.3–0.8pp solo aves. Sin esta migración, la destilación CMKD sufre "ceguera espectral".

---

## 5. Línea 4 — Pseudo-Labeling / Noisy Student (+2–6pp, 1–2 semanas)

La evidencia más consistente de BirdCLEF 2024–2026 (patrón ganador repetido):

* **2024 (2.º, 974 equipos):** 8444 soundscapes no etiquetados → 401k pseudo-labels 5 s, mezcla waveform 25–45%: 69.9 → 71.1.
* **2025 (2.º, 0.928 privado):** EfficientNetV2-S + FocalBCE + 5-fold + pseudo con 40% de muestreo, 2 iteraciones (la 3.ª se estanca), Top-1 mejor.
* **2025 (equipo INT3405):** supervisado 0.736 → +pseudo 0.804 (**+6.8pp**) → +ensemble 0.817.

Receta para los 1206 clips de FAMA:

```python
# teacher = mejor fold de Línea 2/3
# 1. Predecir XC extra + no etiquetado en ventanas 5s stride 2.5s
# 2. Quedarse Top-1 / conf > 0.7-0.9, normalizar a [0,1] en 2.ª iter
# 3. Student: 60% real + 40% pseudo + background-mix + SpecAugment
# 4. Repetir máximo 2x + checkpoint-soup top-3 (+0.6pp gratis)
```

Complemento: limpieza de label-noise XC (Collins `arXiv:2504.18650`, 2025, UOD + autoencoder/VaDE), relevante porque XC es weak-label (1 etiqueta/fichero con fondos solapados).

---

## 6. Línea 5 — Jerárquico Solo para el Residuo (+0.5–1.5pp global, +5–15pp en el par)

Sin SOTA DL propio 2025–2026 como ganador absoluto, pero avalado por ecología para especies crípticas:

```text
Stage 1: Ave/NoAve o género/familia (alta recall)
Stage 2: experto solo del cluster confuso + threshold propio
```

Aplicar solo a los pares que sobrevivan a las Líneas 2–4 (candidatos: Zorzal↔Tordo, Chucao↔Turca, Churrín Mocha↔sur) y solo con ≥30–50 ejemplos por par; si no, propaga error. Alternativa escalable: un binario por especie (CEUR 2025, paper 254).

---

## 7. Qué NO Hacer (Ablacionado o Descartado por Evidencia)

| Técnica | Veredicto | Evidencia |
|:---|:---|:---|
| Más épocas (64e) | ❌ Memoriza recordists: val 87.17% pero test colapsa a 77.37% | `docs/10`, ADR 0003 |
| Pitch-shift espectral ±1 semitono | ❌ 88.44% → 83.71% por formantes rígidos | ADR 0009, Informe 14 |
| Manifold / D-mixup | ❌ Marginal e inestable vs BCE/Focal bien tuneado | BirdCLEF 2024 4.º |
| CutMix / PCEN / geo-filter duro | ❌ −0.047 / −0.072 / −0.34 en holdout | Reporte BirdCLEF 2026 |
| FT completo ViT-H desde ImageNet | ❌ Sobreajusta con 50–170/clase | Ghani et al. 2025: shallow FT generaliza mejor |
| Generativo (ECOGEN, CycleGAN) | ⚠️ Útil si <50/clase; tuning alto para FAMA | ECOGEN +12% pero costoso |

---

## 8. Roadmap Propuesto y Cierre Lab→Prod

| Orden | Qué | Costo | Ganancia esperada |
|:---|:---|:---|:---|
| 0 → 1 | Higiene + thresholds por especie | CPU, 1–2 días | +0.5–1.5pp |
| 2 | ASL + AttentiveStatsPool + reentreno 35e | 1x GPU, 3 días | +2–5pp |
| 3 | Perch 2.0 probe (+ migración 32 kHz) | T4, 1 semana | +5–15pp |
| 4 | Noisy Student 2 rondas + soup | 1x GPU, 1–2 sem | +2–6pp |
| 5–6 | Jerárquico residual + portar a prod | Variable | +0.5–1.5pp + deploy |

El ensamble 88.68% es el óptimo del dominio cerrado actual. El trabajo futuro no debe "estirar" el clasificador ImageNet + GAP, sino **migrar a backbone bioacústico a 32 kHz con ASL + atención + pseudo-labeling**, y **cerrar la brecha lab→prod** portando el campeón (o su destilación CMKD a EfficientNet-B0 INT8) a `backend/app/main.py` con los guardarraíles RMS/flatness existentes.

### Referencias clave (2024–2026)

* Denton et al., Perch 2.0, `arXiv:2508.04665` (2025).
* Rauch et al., BirdMAE, `arXiv:2504.12880` (2025); BirdSet, `arXiv:2403.10380` (2024–25).
* Schwinger et al., review foundation models bioacústicos, *Ecol. Inform.* 2026.
* Earth Species, receta AVEX, `arXiv:2508.11845` (2025).
* Gong et al., CMKD, *TPAMI* 2025; Guimarães et al., BioME, `arXiv:2602.09970` (2026).
* Ghani et al., AvesEcho cross-distillation vs shallow FT, *Sci. Rep.* 2025.
* BirdCLEF 2024 (CEUR Vol-3740), 2025 (2.º Sydorskyi-Gonçalves; 1.º Noisy Student Babych), 2026 (Noisy Student + Distillation).
* Sampath et al., 19 augmentations, *Ecol. Inform.* 2024 (pink-noise + interspecies-mix + loudness-norm = 73.7% F1).
* Collins, limpieza label-noise XC, `arXiv:2504.18650` (2025).
* Kull et al. 2019 (Dirichlet calibration); NeurIPS 2024 TvA (calibración muchas clases, poco val).
