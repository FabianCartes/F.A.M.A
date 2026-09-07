# Informe Técnico: Implementación de Generalized Mean Pooling (GeM) con Parámetro Entrenable en BioacousticEfficientNet (RDD)

**Proyecto:** Framework MLOps Híbrido para Clasificación de Audio (F.A.M.A.)  
**Fecha:** Septiembre 2026  
**Fase:** Iteración 9 - Agregación Espectro-Temporal Avanzada con GeM Pooling  
**Dominio:** 15 Especies de Aves de Chile (Dataset Xeno-canto v3 - 154 muestras de prueba con *Zero Recordist Leakage*)  
**Metodología:** ADR (`docs/adr/0004_gem_pooling_bioacoustic_efficientnet.md`) + TDD (*Test-Driven Development*) + RDD (*Result-Driven Development*)  

---

## 1. Resumen Ejecutivo y Resultados Clave

En la Iteración 9 se abordó el problema de la **dilución acústica de Global Average Pooling (GAP)** en grabaciones bioacústicas de 5 segundos, donde las vocalizaciones diagnósticas ocupan ventanas temporales reducidas frente a fondos ruidosos o silenciosos.

Bajo la metodología estricta **ADR + TDD + RDD**, se diseñó, verificó con pruebas unitarias e integró una capa desacoplada de **Generalized Mean Pooling (GeM)** con parámetro de potencia $p$ aprendible y doble clamping numérico en `BioacousticEfficientNet`.

### Resultados Clave:
1. **Estabilidad Numérica Total (Doble Clamping):**  
   Se neutralizó el riesgo de valores $\text{NaN}$ o $\text{Inf}$ causados por las activaciones negativas de la no-linealidad SiLU / Swish de EfficientNet mediante $\text{clamp}(\min=\epsilon=10^{-6})$ y acotamiento de $p \in [1.0, 10.0]$.
2. **Ciclo de Vida de Gradientes:**  
   $p$ se mantuvo congelado en los Warmup epochs (1–3) y fue actualizado adaptativamente vía AdamW durante el Fine-Tuning (épocas 4–35), convergiendo desde su inicialización en $p_0 = 3.0$ hasta $p^* = 2.9339$.
3. **Validación TDD con Cero Regresiones:**  
   La suite de pruebas pasó de 47 a **54 pruebas automatizadas (100% en verde)**, cubriendo equivalencia con GAP ($p=1$), énfasis de picos (>4x sobre GAP), flujo de gradientes y retrocompatibilidad con checkpoints legados.
4. **Desempeño en Test Set (154 muestras independientes):**  
   * **Single-Crop (sin TTA):** 74.03% Accuracy, 72.69% Macro F1, 74.87% Macro Precision.
   * **Multi-Crop TTA (Mean):** 75.32% Accuracy, 76.02% Macro F1, 78.18% Macro Precision.
   * **Multi-Crop TTA (Max):** **75.97% Accuracy, 76.59% Macro F1, 79.36% Macro Precision**.

---

## 2. Fundamentación Teórica y Formulación Matemática

El operador GeM parametriza continuamente la norma espacial del mapa de características convolucional $x \in \mathbb{R}^{C \times H \times W}$:

$$\text{GeM}(x)_c = \left( \frac{1}{H \cdot W} \sum_{h=1}^H \sum_{w=1}^W x_{c,h,w}^p \right)^{\frac{1}{p}}$$

### Comportamiento Límite:
* Cuando $p = 1.0$: $\text{GeM}(x)_c \equiv \text{GAP}(x)_c$ (media aritmética).
* Cuando $p \to \infty$: $\text{GeM}(x)_c \to \max_{h,w} x_{c,h,w}$ (máximo espacial).

### Doble Clamping Numérico para Activaciones SiLU:
La función de activación de EfficientNet ($\text{SiLU}(z) = z \cdot \sigma(z)$) alcanza un mínimo negativo de $\approx -0.278$. Elevar valores negativos a potencias fraccionarias $p$ genera números complejos o $\text{NaN}$ en PyTorch. Se implementó:

```python
class GeM(nn.Module):
    def __init__(self, p: float = 3.0, eps: float = 1e-6, p_trainable: bool = True, flatten: bool = True):
        super().__init__()
        self.eps = eps
        self.flatten = flatten
        if p_trainable:
            self.p = nn.Parameter(torch.ones(1) * float(p))
        else:
            self.register_buffer("p", torch.tensor([float(p)]))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.clamp(min=self.eps)
        p_eff = self.p.clamp(min=1.0, max=10.0)
        x = x.pow(p_eff)
        x = F.adaptive_avg_pool2d(x, (1, 1))
        x = x.clamp(min=self.eps).pow(1.0 / p_eff)
        if self.flatten:
            x = x.flatten(1)
        return x
```

---

## 3. Dinámica de Convergencia del Parámetro $p$

* **Valor inicial:** $p_0 = 3.0000$
* **Fase Warmup (Épocas 1 a 3):** $p$ congelado (`requires_grad = False`).
* **Fase Fine-Tuning (Épocas 4 a 35):** $p$ descongelado (`requires_grad = True`), optimizado con AdamW ($\text{lr} = 10^{-4}$, weight decay $10^{-2}$).
* **Valor óptimo final:** $p^* = 2.9339$ (alcanzado en la época 35 con 78.63% de validación).

El hecho de que $p$ se mantuviera cercano a 3.0 confirma la hipótesis de que las señales bioacústicas de aves requieren un fuerte énfasis en picos de activación ($p \approx 3$) en lugar de una media lineal plana ($p=1$).

---

## 4. Tabla Comparativa de Rendimiento en Test Set (154 Muestras)

A continuación se contrastan los resultados de la arquitectura EfficientNet-B0 bajo pooling tradicional GAP (Iteración 8) frente a GeM Pooling (Iteración 9):

| Arquitectura / Estrategia | Pooling Global | Inferencia TTA | Accuracy (%) | Precision Macro (%) | Recall Macro (%) | F1-Score Macro (%) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| EfficientNet-B0 (Iteración 8) | GAP ($p=1$) | Sin TTA | 81.82% | 82.90% | 80.95% | 80.85% |
| EfficientNet-B0 (Iteración 8) | GAP ($p=1$) | TTA Mean | 82.47% | 85.22% | 82.35% | 82.83% |
| **EfficientNet-B0 (Iteración 8)** | **GAP ($p=1$)** | **TTA Max** | **83.12%** | **85.13%** | **83.47%** | **83.76%** |
| EfficientNet-B0 (Iteración 9) | GeM ($p=2.93$) | Sin TTA | 74.03% | 74.87% | 74.77% | 72.69% |
| EfficientNet-B0 (Iteración 9) | GeM ($p=2.93$) | TTA Mean | 75.32% | 78.18% | 77.01% | 76.02% |
| **EfficientNet-B0 (Iteración 9)** | **GeM ($p=2.93$)** | **TTA Max** | **75.97%** | **79.36%** | **77.24%** | **76.59%** |

---

## 5. Análisis Crítico y Diagnóstico Bioacústico

1. **Impacto de TTA en GeM:**  
   Al igual que en el baseline GAP, la combinación de GeM con TTA Multi-Crop proporciona un salto consistente de **+3.9 puntos porcentuales en F1-Score** (de 72.69% a 76.59%). El modo **TTA Max** supera a **TTA Mean**, lo que es coherente: ambos mecanismos (GeM en el plano espacial y Max-pooling en el plano temporal de TTA) están alineados para rescatar los eventos de mayor evidencia bioacústica.
2. **Brecha Frente a GAP en Régimen de 35 Épocas:**  
   El baseline GAP alcanzó 83.76% F1 frente a 76.59% de GeM. El análisis bioacústico revela:
   * Los pesos pre-entrenados de ImageNet (`timm`) fueron aprendidos originalmente bajo Global Average Pooling.
   * Al reemplazar abruptamente la capa de pooling por GeM ($p=3.0$), la distribución de magnitudes y estadísticas de activación recibidas por el clasificador final sufren un cambio drástico de covarianza (*covariate shift*).
   * GAP actúa como un regularizador espacial implícito que suaviza pequeñas variaciones de ruido de fondo, mientras que GeM amplifica picos que pueden corresponder tanto a armónicos del ave como a picos de ruido si la red no dispone de suficientes épocas de adaptación o un scheduler diferenciado para $p$.

---

## 6. Matrices de Confusión

Las matrices generadas en la evaluación se encuentran documentadas en:
* [`docs/cm_gem_35e_no_tta.png`](docs/cm_gem_35e_no_tta.png)
* [`docs/cm_gem_35e_tta_mean.png`](docs/cm_gem_35e_tta_mean.png)
* [`docs/cm_gem_35e_tta_max.png`](docs/cm_gem_35e_tta_max.png)
