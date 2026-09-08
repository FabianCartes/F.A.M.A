# Banco de Audios .WAV de Prueba — F.A.M.A.

Esta carpeta contiene audios listos para arrastrar y soltar en la sección de **Predicción** del panel web ([http://localhost:3000](http://localhost:3000)).

---

## 🎯 1. Audios de Aves de Campo Reales (Test Set Ciego — Zero Recordist Leakage)

Estos audios provienen del conjunto oficial `test.csv` (154 muestras de campo de Xeno-Canto). **Fueron estrictamente aislados por grabador y ubicación**, lo que significa que el modelo **NUNCA los vio durante su entrenamiento**. Por lo tanto, el modelo no puede "recordarlos" por memorización, sino que debe aplicar generalización acústica pura.

| Archivo | Especie Real | Duración | Descripción Bioacústica |
| :--- | :--- | :---: | :--- |
| **`test_chucao_01.wav`** | *Scelorchilus rubecula* (Chucao) | 24.3s | Canto percusivo potente y silbidos de bosque templado lluvioso. |
| **`test_rayadito_01.wav`** | *Aphrastura spinicauda* (Rayadito) | 44.8s | Trinos agudos rápidos y llamadas de contacto en dosel de *Nothofagus*. |
| **`test_churrin_mocha_01.wav`** | *Eugralla paradoxa* (Churrín de la Mocha) | 50.6s | Llamadas graves rítmicas de suelo en sotobosque denso (especie 100% F1). |
| **`test_turca_01.wav`** | *Pteroptochos megapodius* (Turca) | 36.0s | Cantos resonantes y notas descendentes de matorral semiárido. |
| **`test_zorzal_patagonico_01.wav`** | *Turdus falcklandii* (Zorzal patagónico) | 7.0s | Frases melodiosas complejas y gorjeos urbanos/rurales. |
| **`test_tijeral_01.wav`** | *Sylviorthorhynchus desmursii* (Tijeral) | 4.4s | Silbidos agudos de frecuencia ultra-estrecha en pajonales. |
| **`test_chincol_01.wav`** | *Zonotrichia capensis* (Chincol) | 30.8s | Canto clásico estructurado en tema introductorio y trino final. |
| **`test_tordo_01.wav`** | *Curaeus curaeus* (Tordo) | 23.1s | Silbidos metálicos ásperos y notas de alarma gregarias. |

---

## 🛑 2. Audios de Control Negativo (Out-of-Distribution / No Biológicos)

Estos audios **NO contienen cantos de aves chilenas**. Se utilizan para evaluar cómo reacciona el modelo ante señales artificiales, ruido ambiental o silencio:

| Archivo | Tipo de Señal | Duración | Comportamiento Esperado |
| :--- | :--- | :---: | :--- |
| **`control_ruido_blanco.wav`** | Ruido Gaussiano Blanco | 5.0s | Planitud espectral uniforme. No tiene patrones biológicos armónicos. |
| **`control_viento_ambiental.wav`** | Ráfagas de Viento de Baja Frecuencia | 5.0s | Simula turbulencia de viento en micrófono de campo. |
| **`control_tono_puro_1khz.wav`** | Onda Senoidal Pura (1,000 Hz) | 5.0s | Tono sintético monofónico artificial sin armónicos. |

---

## 🚀 Cómo utilizarlos:
1. Abre tu navegador en [http://localhost:3000](http://localhost:3000).
2. Ve a la sección **Predicción**.
3. Abre esta carpeta en el Explorador de Archivos de Windows:  
   `C:\Users\fabia\Desktop\F.A.M.A\audios_prueba`
4. Arrastra cualquiera de los archivos `.wav` al recuadro punteado y pulsa **"Ejecutar inferencia bioacústica"**.
