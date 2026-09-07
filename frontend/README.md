# F.A.M.A. — Frontend Web (Next.js + Tailwind CSS)

Panel web minimalista y responsivo para inferencia bioacústica en tiempo real, desarrollado con **Next.js (App Router)**, **React**, **TypeScript** y **Tailwind CSS** bajo estética de Modo Oscuro nativo.

---

## 🛠️ Requisitos Previos

- **Node.js 18.18+** o **Node.js 20+**
- **npm** (o pnpm / yarn)
- Backend de F.A.M.A. (FastAPI) corriendo en `http://127.0.0.1:8000`

---

## 🚀 Puesta en Marcha

### 1. Instalar dependencias
```bash
npm install
```

### 2. Iniciar servidor de desarrollo
```bash
npm run dev
```

Abre en tu navegador: [http://localhost:3000](http://localhost:3000)

### 3. Compilar para producción
```bash
npm run build
npm run start
```

---

## 📡 Integración con el Backend
La aplicación envía los archivos `.wav` seleccionados mediante peticiones `multipart/form-data` hacia el endpoint:
- **`POST http://127.0.0.1:8000/api/predict`**

Y renderiza en tiempo real la clase bioacústica predicha, la confianza calibrada porcentual, el identificador en la base de datos PostgreSQL y el estado de persistencia en Google Cloud Storage.
