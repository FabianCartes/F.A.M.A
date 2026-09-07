# ADR 0006: Inferencia de Ensamble Ponderado Multi-Modelo (Soft Voting) con Diversidad Estructural

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Inferencia Bioacústica, Fusión de Modelos (*Ensemble Learning*) y Arquitectura de Deep Learning  

---

## 1. Contexto y Problema

A pesar de haber alcanzado un nuevo récord de desempeño con **84.38% Macro F1** mediante Ventaneo Denso (ADR 0005), los modelos individuales de Deep Learning basados en una única arquitectura o mecanismo de atención alcanzan un límite estadístico asintótico debido a sus sesgos inductivos inherentes:

1. **Sesgo Inductivo de Agregación Espacial (GAP vs GeM):**
   * El modelo campeón ([`checkpoints/efficientnet_gpu_pipeline_35e_best.pt`](../../checkpoints/efficientnet_gpu_pipeline_35e_best.pt)) utiliza **Global Average Pooling (GAP)**, el cual promedia uniformemente las activaciones en tiempo y frecuencia. Si bien está calibrado óptimamente con los pesos preentrenados de ImageNet en `timm`, tiende a diluir eventos acústicos discretos de alta energía.
   * El modelo alternativo ([`checkpoints/efficientnet_gem_35e_best.pt`](../../checkpoints/efficientnet_gem_35e_best.pt)) implementa **Generalized Mean Pooling (GeM, $p \approx 3.0$)**, el cual focaliza su gradiente de atención en picos espectro-temporales salientes (trinos agudos y llamadas percusivas), aunque con una pérdida de calibración global cuando opera en solitario (77.73% F1 individual).

2. **Varianza Estocástica y Errores No Correlacionados:**
   * La evaluación de errores individuales muestra que los falsos positivos y confusiones (ej. Tapaculo vs Turca, Zorzal vs Fío-fío) no se distribuyen idénticamente entre modelos con distintos inductores o dinámicas de pooling.
   * En la literatura de Machine Learning y bioacústica de clase mundial (BirdCLEF, DCASE, Lakshminarayanan et al., *Deep Ensembles*), la combinación ponderada de modelos con diversidad estructural o estocástica neutraliza el ruido y reduce drásticamente la varianza de predicción.

3. **Necesidad de una Costura (*Seam*) Desacoplada y Profunda:**
   * El sistema debe permitir combinar $K \ge 2$ checkpoints sin duplicar código de inferencia, sin romper `predict_audio_tta` ni `evaluate_test_set`, respetando el Principio de Sustitución de Liskov mediante un módulo profundo `EnsembleClassifier(nn.Module)` que encapsule la votación suave (*Soft Voting*).

---

## 2. Decisión Arquitectónica

Se aprueba la implementación de un módulo de ensamble ponderado en tiempo de inferencia:

### 2.1 Módulo `EnsembleClassifier(nn.Module)`
Se diseña un módulo profundo que hereda de `nn.Module` y encapsula una lista de submodelos y sus respectivos pesos normalizados:

$$\hat{P}_{\text{ensemble}}(y = c \mid X) = \sum_{k=1}^K w_k \cdot \text{Softmax}(z_k(X))_c, \quad \text{donde } \sum_{k=1}^K w_k = 1$$

Para satisfacer la interfaz estándar de los clasificadores de PyTorch esperada por `predict_audio_tta`, el forward del ensamble retorna los logaritmos de las probabilidades combinadas:

$$\hat{z}_{\text{ensemble}} = \log\left(\hat{P}_{\text{ensemble}} + \epsilon\right)$$

De este modo, cualquier consumidor que aplique `torch.softmax(logits, dim=-1)` recupera exactamente la distribución de probabilidades combinadas sin requerir modificaciones en `predict_audio_tta`.

### 2.2 Selección de Checkpoints y Ponderación Óptima
Se formaliza la combinación de los dos modelos representativos con diversidad estructural:
* **Modelo Primario (80% peso, $w_1 = 0.80$):** `efficientnet_gpu_pipeline_35e_best.pt` (GAP estándar, máxima precisión global).
* **Modelo Secundario (20% peso, $w_2 = 0.20$):** `efficientnet_gem_35e_best.pt` (GeM Pooling $p \approx 3.0$, atención a picos salientes).
* **Inferencia:** Evaluada bajo ventaneo denso (`hop_seconds=1.0`) y agregación temporal `max`.

### 2.3 Exposición en Línea de Comandos (CLI)
Se añade soporte en `backend/poc/evaluate.py`:
* `--checkpoints`: Lista de rutas a checkpoints `.pt` para construir el ensamble.
* `--weights`: Lista opcional de pesos flotantes (normalizados automáticamente). Si se omite, se aplica voto uniforme ($1/K$).

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Ruptura de la Barrera del 85% F1:** La combinación de representaciones complementarias (GAP + GeM) supera a cualquier modelo individual, alcanzando **85.06% Macro F1** y **85.71% Macro Precision**.
* **Arquitectura Profunda y Limpia:** `EnsembleClassifier` respeta Liskov; el pipeline de TTA y los DataLoaders no requieren cambios.
* **Cero Reentrenamiento Adicional:** Reutiliza los modelos ya entrenados en VRAM.

### Negativas / Riesgos:
* **Mayor Consumo de Memoria VRAM y Latencia:** Cargar 2 modelos EfficientNet-B0 requiere ~100 MB de VRAM (despreciable en la GPU RTX 2050 de 4 GB). La latencia por audio se duplica ligeramente de ~90 ms a ~180 ms, manteniéndose muy por debajo del umbral interactivo de 500 ms.
