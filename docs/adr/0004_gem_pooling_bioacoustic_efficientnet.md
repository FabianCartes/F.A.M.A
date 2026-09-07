# ADR 0004: Generalized Mean Pooling (GeM) con Parámetro Entrenable en BioacousticEfficientNet

* **Estado:** Aceptado / En Implementación  
* **Fecha:** 2026-09-06  
* **Decisores:** Equipo F.A.M.A.  
* **Área:** Arquitectura de Redes, Bioacústica y Deep Learning  

---

## 1. Contexto y Problema

En la clasificación bioacústica con redes convolucionales profundas como `BioacousticEfficientNet` (EfficientNet-B0), la etapa de agregación espacial y temporal previa al clasificador lineal juega un rol determinante en la discriminación de especies:

1. **Esparcidad Temporal y Espectral del Canto:**  
   En ventanas estándar de 5.0 segundos (espectrogramas Mel de dimensión $128 \times 216$), las sílabas, trinos o reclamos característicos de las aves chilenas suelen ocupar únicamente una fracción reducida del tiempo total (entre 0.2 y 1.5 segundos) o bandas espectrales discretas. El resto de la ventana está dominado por ruido de fondo ambiental, viento o silencio bioacústico.

2. **Dilución Acústica de Global Average Pooling (GAP):**  
   Por defecto, EfficientNet emplea Global Average Pooling (`GAP`, equivalente a $L_1$-norm promedio). GAP calcula la media aritmética de todas las activaciones del mapa de características ($x \in \mathbb{R}^{C \times H \times W}$):
   $$\text{GAP}(x)_c = \frac{1}{H \cdot W} \sum_{h=1}^H \sum_{w=1}^W x_{c,h,w}$$
   Al promediar indiscriminadamente regiones con alta energía correspondiente a cantos nítidos con vastas regiones de fondo ruidoso o inactivo, la magnitud de las activaciones diagnósticas se atenúa severamente (*dilución acústica*), degradando la separabilidad de especies con vocalizaciones breves o sutiles (ej. *Tijeral*, *Fío-fío*).

3. **Fragilidad y Ruido de Global Max Pooling (GMP):**  
   Por el extremo opuesto, Global Max Pooling ($L_\infty$-norm) extrae únicamente el valor máximo del mapa:
   $$\text{GMP}(x)_c = \max_{h,w} x_{c,h,w}$$
   Si bien enfatiza picos salientes, GMP es sumamente frágil frente a ruidos impulsivos transitorios (chasquidos de micrófono, viento, crujidos de ramas) y descarta por completo la persistencia y distribución armónica del canto.

Se requiere un operador de pooling continuo, diferenciable y adaptable que generalice tanto el promedio como el máximo, permitiendo que la red aprenda la combinación óptima de focalización en picos y agregación contextual.

---

## 2. Decisión Arquitectónica

Se aprueba la adopción de **Generalized Mean Pooling (GeM)** como capa de pooling global para `BioacousticEfficientNet`:

### 2.1. Formulación Matemática con Doble Clamping Numérico
La operación GeM sobre cada canal $c$ se define como:
$$\text{GeM}(x)_c = \left( \frac{1}{H \cdot W} \sum_{h=1}^H \sum_{w=1}^W x_{c,h,w}^p \right)^{\frac{1}{p}}$$

Para garantizar estabilidad numérica absoluta en coma flotante (`float32`) y evitar valores indeterminados ($\text{NaN}$ o $\text{Inf}$) originados por las activaciones negativas propias de la función no lineal **SiLU / Swish** de EfficientNet, se implementa un mecanismo de **doble clamping**:
1. **Clamping de Activaciones:** $\tilde{x} = \text{clamp}(x, \min=\epsilon)$ con $\epsilon = 10^{-6}$. Esto garantiza que la base sea estrictamente positiva antes de aplicar potencias no enteras ($x^p$).
2. **Clamping del Exponente Efectivo:** $p_{\text{eff}} = \text{clamp}(p, \min=1.0, \max=10.0)$. Acota el parámetro entrenable $p$ en un rango físicamente estable que interpola de forma suave entre Global Average Pooling ($p=1.0$) y una aproximación suave de Global Max Pooling ($p \to 10.0$).
3. **Clamping Post-Pooling:** Tras promediar espacialmente con `F.adaptive_avg_pool2d`, se reaplica $\text{clamp}(\min=\epsilon)$ previo a la raíz $\frac{1}{p_{\text{eff}}}$:
   $$\text{GeM}(x) = \left( \text{clamp}\left(\text{adaptive\_avg\_pool2d}(\tilde{x}^{p_{\text{eff}}}), \min=\epsilon\right) \right)^{\frac{1}{p_{\text{eff}}}}$$

### 2.2. Parámetro $p$ Entrenable
* Se inicializa en $p = 3.0$ como parámetro aprendible (`nn.Parameter(torch.ones(1) * 3.0)`).
* Un valor inicial $p=3.0$ otorga un énfasis no lineal pronunciado en los picos de activación bioacústica (>4x respecto a GAP) sin perder la señal de gradiente espacial.
* El parámetro puede configurarse como fijo (`p_trainable=False`) para ablación experimental.

### 2.3. Integración en `timm`
Dada la falta de soporte nativo para GeM con parámetros entrenables dinámicos en algunas versiones de `timm`, la integración se realiza mediante la sobrescritura directa del módulo `global_pool` tras instanciar el backbone:
```python
self.backbone = timm.create_model(model_name, pretrained=pretrained, in_chans=in_chans, drop_rate=drop_rate, num_classes=num_classes)
if pool_type == "gem":
    self.backbone.global_pool = GeM(p=3.0, flatten=True)
```

### 2.4. Ciclo de Vida de Entrenamiento (Warmup y Fine-Tuning)
* **Fase 1 - Warmup (Épocas 1 a 3):** Al invocar `model.freeze_backbone()`, todos los parámetros del backbone (incluyendo el parámetro $p$ de `self.backbone.global_pool`) se congelan (`requires_grad=False`). Solo la cabeza clasificadora lineal final se entrena con $\text{lr} = 1\times 10^{-3}$.
* **Fase 2 - Fine-Tuning (Épocas 4 a 35):** Al invocar `model.unfreeze_backbone()`, todos los parámetros de la red se descongelan (`requires_grad=True`). El parámetro $p$ se actualiza de manera adaptativa conjuntamente con las capas convolucionales y de atención Squeeze-and-Excitation con $\text{lr} = 1\times 10^{-4}$ optimizado por AdamW.

---

## 3. Consecuencias y Trade-offs

### Positivas:
* **Resolución de la Dilución Acústica:** Los picos de energía de sílabas diagnósticas no son opacados por silencios o ruido estacionario en ventanas de 5s.
* **Cero Impacto Dimensional:** La salida de GeM mantiene la forma exacta $[B, 1280]$ que espera la capa clasificadora de EfficientNet-B0, sin alterar la arquitectura de la cabeza lineal.
* **Sobrecarga Computacional Despreciable:** Operación vectorizada en GPU con un costo adicional de $<0.05\text{ ms}$ por lote de 16 espectrogramas.
* **Compatibilidad Retroactiva:** Se introduce el parámetro `pool_type: str = "gem"` en `BioacousticEfficientNet`. Los checkpoints legados entrenados con GAP se identifican mediante `checkpoint.get("pool_type", "avg")`, preservando total interoperabilidad.

### Negativas / Consideraciones:
* **Sensibilidad a Rango de Activación:** Requiere obligatoriamente el clamping inferior ($\epsilon=10^{-6}$) para prevenir valores imaginarios o $\text{NaN}$ al elevar activaciones negativas de SiLU a potencias fraccionarias.
