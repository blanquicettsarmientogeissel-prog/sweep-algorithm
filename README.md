# 🌀 Sweep Algorithm & OSRM Routing Map

Este repositorio contiene la solución completa para la **Optimización de Rutas de Vehículos (VRP)** utilizando la heurística del **Algoritmo del Barrido (Sweep Algorithm)** y trazados reales por carretera mediante la **API de OSRM (Open Source Routing Machine)**.

## 🌍 Enlace Público al Mapa Interactivo
Puedes visualizar los resultados del ruteo en vivo en el siguiente enlace:
👉 **[Ver Mapa Interactivo en GitHub Pages](https://blanquicettsarmientogeissel-prog.github.io/sweep-algorithm/)**

---

## 🛠️ Características Principales
- **Algoritmo del Barrido (Sweep Algorithm)**: Agrupa los puntos de entrega por ángulo polar respecto al depósito principal (Bodega) y por capacidad del vehículo.
- **Ruteo Vial con OSRM**: Traza las rutas sobre las calles reales calculando distancias exactas en kilómetros y tiempos estimados de viaje.
- **Visualización Interactiva**: Panel de control con métricas clave (vehículos, carga total, distancia total, paradas por ruta) y capas personalizadas.

---

## 🚀 Ejecución del Proyecto
Para ejecutar la generación del mapa y actualización automática en GitHub:

```bash
python sweep_routing_osrm.py
```
O usando PowerShell:
```powershell
.\generate_map.ps1
```