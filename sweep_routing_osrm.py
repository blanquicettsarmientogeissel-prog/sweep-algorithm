#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
===============================================================================
RUTEO DE VEHÍCULOS CON ALGORITMO DEL BARRIDO (SWEEP ALGORITHM) Y OSRM
===============================================================================
Este script lee un archivo CSV de clientes y bodega, aplica la heurística del 
Algoritmo del Barrido (Sweep Algorithm) para agrupar clientes en rutas respetando
la capacidad del vehículo, obtiene los trazados sobre la malla vial real usando OSRM,
y genera un mapa interactivo visualizable en el navegador web con Folium.

Autor: Antigravity AI (Google DeepMind Team)
===============================================================================
"""

import csv
import math
import json
import os
import sys
import argparse
import urllib.request
import urllib.parse
from typing import List, Dict, Tuple, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Intentar importar folium. Si no está instalado, dar mensaje descriptivo.
try:
    import folium
    from folium import plugins
except ImportError:
    print("ERROR: La librería 'folium' no está instalada.")
    print("Por favor instala las dependencias ejecutando: pip install -r requirements.txt")
    print("o directamente: pip install folium requests")
    sys.exit(1)



# =============================================================================
# 1. LECTURA Y PROCESAMIENTO DE DATOS CSV
# =============================================================================

def cargar_datos_csv(file_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Lee el archivo CSV de direcciones de la ruta.
    Detecta automáticamente la Bodega (ID = 0) y extrae los clientes.

    Maneja el formato del CSV:
    - Separador de campos: ';'
    - Separador decimal en coordenadas y peso: ','
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No se encontró el archivo CSV en la ruta: {file_path}")

    deposito = None
    clientes = []

    with open(file_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        
        for row_idx, row in enumerate(reader, start=2):
            # Limpiar llaves y valores
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items() if k}
            
            id_str = row.get('ID', '')
            nombre = row.get('Nombre', '')
            direccion = row.get('Dirección', '')
            lat_str = row.get('Latitud', '').replace(',', '.')
            lon_str = row.get('Longitud', '').replace(',', '.')
            peso_str = row.get('Peso', '').replace(',', '.')

            # Validar campos esenciales
            if not lat_str or not lon_str:
                continue

            try:
                lat = float(lat_str)
                lon = float(lon_str)
            except ValueError:
                print(f"Advertencia: Fila {row_idx} omitida por coordenadas inválidas: {lat_str}, {lon_str}")
                continue

            # Peso / Demanda
            if peso_str in ('-', '', None):
                peso = 0.0
            else:
                try:
                    peso = float(peso_str)
                except ValueError:
                    peso = 0.0

            nodo = {
                'id': id_str,
                'nombre': nombre,
                'direccion': direccion,
                'lat': lat,
                'lon': lon,
                'peso': peso
            }

            # El ID 0 o la bodega principal es el depósito
            if id_str == '0' or 'bodega' in nombre.lower() or 'deposito' in nombre.lower():
                deposito = nodo
            else:
                clientes.append(nodo)

    if not deposito:
        if clientes:
            print("Advertencia: No se identificó ID 0 como Bodega. Asumiendo el primer registro como Depósito.")
            deposito = clientes.pop(0)
        else:
            raise ValueError("No se encontraron registros válidos en el CSV.")

    print(f"✅ Depósito cargado: {deposito['nombre']} ({deposito['lat']}, {deposito['lon']})")
    print(f"✅ Se cargaron {len(clientes)} clientes exitosamente.")
    return deposito, clientes


# =============================================================================
# 2. HEURÍSTICA DEL ALGORITMO DEL BARRIDO (SWEEP ALGORITHM)
# =============================================================================

def calcular_distancia_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica aproximada en km entre dos coordenadas."""
    R = 6371.0 # Radio medio de la Tierra en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def aplicar_sweep_algorithm(deposito: Dict[str, Any], 
                           clientes: List[Dict[str, Any]], 
                           capacidad_vehiculo: float,
                           angulo_inicio_grados: float = 0.0) -> List[List[Dict[str, Any]]]:
    """
    Ejecuta el Algoritmo del Barrido (Sweep Algorithm):
    1. Transforma las coordenadas geográficas de cada cliente a un ángulo polar (theta)
       con respecto al depósito (Bodega).
    2. Ordena los clientes según su ángulo polar theta en sentido antihorario.
    3. Agrupa secuencialmente a los clientes en rutas de vehículos de tal manera que la
       demanda acumulada (peso) no exceda la capacidad máxima especificada del vehículo.

    Retorna una lista de rutas, donde cada ruta es una lista de nodos de clientes.
    """
    dep_lat, dep_lon = deposito['lat'], deposito['lon']

    # 1. Calcular ángulo polar (en grados [0, 360)) para cada cliente
    for c in clientes:
        d_lat = c['lat'] - dep_lat
        d_lon = c['lon'] - dep_lon

        # atan2(dy, dx): dy es cambio en latitud (N-S), dx es cambio en longitud (E-W)
        angulo_rad = math.atan2(d_lat, d_lon)
        angulo_deg = math.degrees(angulo_rad) % 360.0
        
        # Ajuste según ángulo inicial de inicio del barrido (fase)
        angulo_ajustado = (angulo_deg - angulo_inicio_grados) % 360.0

        c['angulo'] = angulo_deg
        c['angulo_ajustado'] = angulo_ajustado
        c['dist_deposito'] = calcular_distancia_haversine(dep_lat, dep_lon, c['lat'], c['lon'])

    # 2. Ordenar clientes en dirección del barrido (por ángulo ajustado creciente)
    clientes_ordenados = sorted(clientes, key=lambda x: x['angulo_ajustado'])

    # 3. Construir rutas agrupando por capacidad del vehículo
    rutas = []
    ruta_actual = []
    carga_actual = 0.0

    for c in clientes_ordenados:
        peso_cliente = c['peso']

        # Si un solo cliente supera la capacidad del vehículo
        if peso_cliente > capacidad_vehiculo:
            print(f"⚠️ Advertencia: El cliente ID {c['id']} ({c['nombre']}) con peso {peso_cliente}kg "
                  f"excede la capacidad máxima del vehículo ({capacidad_vehiculo}kg). Se asignará en ruta individual.")
            if ruta_actual:
                rutas.append(ruta_actual)
                ruta_actual = []
                carga_actual = 0.0
            rutas.append([c])
            continue

        if carga_actual + peso_cliente <= capacidad_vehiculo:
            ruta_actual.append(c)
            carga_actual += peso_cliente
        else:
            # Cerrar ruta actual e iniciar nueva ruta
            rutas.append(ruta_actual)
            ruta_actual = [c]
            carga_actual = peso_cliente

    if ruta_actual:
        rutas.append(ruta_actual)

    print(f"\n🌀 Algoritmo del Barrido completado:")
    print(f"   • Clientes procesados: {len(clientes)}")
    print(f"   • Capacidad máxima por vehículo: {capacidad_vehiculo} kg")
    print(f"   • Rutas/Vehículos requeridos: {len(rutas)}")

    return rutas


# =============================================================================
# 3. INTEGRACIÓN CON API OSRM (OPEN SOURCE ROUTING MACHINE)
# =============================================================================

def obtener_ruta_osrm(nodos_ruta: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Obtiene el trazado vial exacto, la distancia (km) y la duración (minutos) 
    consultando el servidor de enrutamiento público OSRM (driving profile).

    Recibe nodos_ruta: [Depósito, Cliente_1, Cliente_2, ..., Cliente_K, Depósito]
    Retorna un diccionario con:
    - 'geometria': Lista de puntos [lat, lon] para dibujar en el mapa.
    - 'distancia_km': Distancia total por carretera.
    - 'duracion_min': Tiempo total estimado de viaje en minutos.
    """
    # Construir cadena de coordenadas para OSRM: lon1,lat1;lon2,lat2;...
    # ¡Importante!: OSRM requiere primero Longitud y luego Latitud.
    coords_str = ";".join([f"{n['lon']:.6f},{n['lat']:.6f}" for n in nodos_ruta])
    
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"

    req = urllib.request.Request(url, headers={'User-Agent': 'SweepRoutingApp/1.0 Python/3'})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('code') == 'Ok' and data.get('routes'):
                    osrm_route = data['routes'][0]
                    distance_meters = osrm_route.get('distance', 0.0)
                    duration_seconds = osrm_route.get('duration', 0.0)
                    
                    # Extraer coordenadas GeoJSON [lon, lat] y convertir a [lat, lon] para Folium
                    geojson_coords = osrm_route['geometry']['coordinates']
                    folium_coords = [[pt[1], pt[0]] for pt in geojson_coords]

                    return {
                        'geometria': folium_coords,
                        'distancia_km': round(distance_meters / 1000.0, 2),
                        'duracion_min': round(duration_seconds / 60.0, 1),
                        'es_osrm': True
                    }
    except Exception as e:
        print(f"   ⚠️ Consulta OSRM falló ({e}). Usando trazado de línea directa (Haversine).")

    # Fallback: Trazado directo en línea recta en caso de no disponer de conexión OSRM
    folium_coords = [[n['lat'], n['lon']] for n in nodos_ruta]
    dist_total = 0.0
    for i in range(len(nodos_ruta) - 1):
        dist_total += calcular_distancia_haversine(
            nodos_ruta[i]['lat'], nodos_ruta[i]['lon'],
            nodos_ruta[i+1]['lat'], nodos_ruta[i+1]['lon']
        )

    return {
        'geometria': folium_coords,
        'distancia_km': round(dist_total, 2),
        'duracion_min': round((dist_total / 30.0) * 60.0, 1), # Estimación a 30 km/h
        'es_osrm': False
    }


# =============================================================================
# 4. GENERACIÓN DEL MAPA INTERACTIVO CON FOLIUM
# =============================================================================

PALETA_COLORES = [
    '#1F77B4', '#FF7F0E', '#2CA02C', '#D62728', '#9467BD',
    '#8C564B', '#E377C2', '#7F7F7F', '#BCBD22', '#17BECF',
    '#E63946', '#2A9D8F', '#F4A261', '#E76F51', '#457B9D'
]

def crear_mapa_interactivo(deposito: Dict[str, Any], 
                           rutas: List[List[Dict[str, Any]]], 
                           detalles_rutas: List[Dict[str, Any]],
                           capacidad_vehiculo: float,
                           output_html: str = "mapa_rutas_sweep.html"):
    """
    Crea y guarda el mapa interactivo con Folium en un archivo HTML.
    Muestra:
    - Depósito con icono destacado de Bodega/Almacén.
    - Rutas diferenciadas por color siguiendo la malla vial de OSRM.
    - Marcadores para cada cliente indicando secuencia de visita, nombre, dirección y peso.
    - Panel lateral interactivo / Leyenda con resúmenes por vehículo.
    """
    center_lat, center_lon = deposito['lat'], deposito['lon']
    
    # Inicializar mapa Folium centrado en la Bodega
    mapa = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles='cartodbpositron',
        control_scale=True
    )

    # Añadir capa Satelital y OpenStreetMap opcionales
    folium.TileLayer('openstreetmap', name='OpenStreetMap').add_to(mapa)
    folium.TileLayer('cartodbdark_matter', name='Modo Oscuro').add_to(mapa)

    # 1. Marcador del Depósito (Bodega)
    popup_deposito = f"""
    <div style="font-family: Arial, sans-serif; min-width: 200px;">
        <h4 style="margin: 0 0 5px 0; color: #D62728;">🏭 {deposito['nombre']}</h4>
        <hr style="margin: 5px 0;">
        <b>ID:</b> {deposito['id']}<br>
        <b>Dirección:</b> {deposito['direccion']}<br>
        <b>Coordenadas:</b> {deposito['lat']:.6f}, {deposito['lon']:.6f}<br>
        <span style="background-color: #ffebee; color: #c62828; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block; margin-top: 5px;">PUNTO DE PARTIDA Y LLEGADA</span>
    </div>
    """
    folium.Marker(
        location=[deposito['lat'], deposito['lon']],
        popup=folium.Popup(popup_deposito, max_width=300),
        tooltip=f"<b>BODEGA PRINCIPAL:</b> {deposito['nombre']}",
        icon=folium.Icon(color='red', icon='home', prefix='fa')
    ).add_to(mapa)

    # Resumen para el panel flotante HTML
    resumen_html_items = []
    distancia_total_flota = 0.0
    peso_total_entregado = 0.0

    # 2. Dibujar cada Ruta de Vehículo
    for r_idx, (clientes_ruta, detalle) in enumerate(zip(rutas, detalles_rutas), start=1):
        color_hex = PALETA_COLORES[(r_idx - 1) % len(PALETA_COLORES)]
        peso_ruta = sum(c['peso'] for c in clientes_ruta)
        distancia_total_flota += detalle['distancia_km']
        peso_total_entregado += peso_ruta
        porcentaje_carga = (peso_ruta / capacidad_vehiculo) * 100.0

        # Crear FeatureGroup para cada vehículo (permite encender/apagar en el mapa)
        fg_ruta = folium.FeatureGroup(name=f"Ruta Vehículo #{r_idx} ({len(clientes_ruta)} clientes - {peso_ruta:.0f}kg)")

        # Dibujar trazado OSRM por carretera
        folium.PolyLine(
            locations=detalle['geometria'],
            color=color_hex,
            weight=4.5,
            opacity=0.85,
            tooltip=f"Vehículo #{r_idx} | Distancia: {detalle['distancia_km']} km | Tiempo: {detalle['duracion_min']} min"
        ).add_to(fg_ruta)

        # Dibujar marcadores de los clientes en orden de visita
        for stop_idx, c in enumerate(clientes_ruta, start=1):
            popup_cliente = f"""
            <div style="font-family: Arial, sans-serif; min-width: 220px;">
                <div style="background-color: {color_hex}; color: white; padding: 4px 8px; border-radius: 3px; font-weight: bold; margin-bottom: 6px;">
                    Ruta #{r_idx} — Parada {stop_idx} de {len(clientes_ruta)}
                </div>
                <h4 style="margin: 0 0 5px 0; color: #333;">📍 {c['nombre']} (ID: {c['id']})</h4>
                <hr style="margin: 5px 0;">
                <b>Dirección:</b> {c['direccion']}<br>
                <b>Peso / Demanda:</b> <span style="color: #2e7d32; font-weight: bold;">{c['peso']} kg</span><br>
                <b>Ángulo de Barrido:</b> {c['angulo']:.1f}°<br>
                <b>Dist. en línea recta a Bodega:</b> {c['dist_deposito']:.2f} km<br>
            </div>
            """

            # Crear icono numerado personalizado
            icon_html = f"""
            <div style="
                background-color: {color_hex};
                color: white;
                border-radius: 50%;
                width: 26px;
                height: 26px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 12px;
                border: 2px solid white;
                box-shadow: 0 2px 4px rgba(0,0,0,0.4);
            ">{stop_idx}</div>
            """
            
            custom_icon = folium.DivIcon(
                html=icon_html,
                icon_size=(26, 26),
                icon_anchor=(13, 13)
            )

            folium.Marker(
                location=[c['lat'], c['lon']],
                popup=folium.Popup(popup_cliente, max_width=320),
                tooltip=f"<b>Parada {stop_idx}:</b> {c['nombre']} ({c['peso']} kg)",
                icon=custom_icon
            ).add_to(fg_ruta)

        fg_ruta.add_to(mapa)

        # Agregar item a la leyenda HTML
        resumen_html_items.append(f"""
        <div style="margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #eee;">
            <strong style="color: {color_hex};">● Vehículo #{r_idx}</strong><br>
            <small>
                • Clientes: <b>{len(clientes_ruta)}</b><br>
                • Carga: <b>{peso_ruta:.0f} / {capacidad_vehiculo:.0f} kg</b> ({porcentaje_carga:.1f}%)<br>
                • Distancia OSRM: <b>{detalle['distancia_km']} km</b><br>
                • Tiempo aprox: <b>{detalle['duracion_min']} min</b>
            </small>
        </div>
        """)

    # 3. Añadir Cuadro de Mando / Leyenda Flotante en el Mapa
    leyenda_html = f"""
    <div style="
        position: fixed; 
        top: 15px; 
        right: 15px; 
        width: 290px; 
        max-height: 85vh; 
        overflow-y: auto; 
        background-color: rgba(255, 255, 255, 0.95);
        box-shadow: 0 0 15px rgba(0,0,0,0.2); 
        border-radius: 8px; 
        padding: 14px; 
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        z-index: 9999;
        border-left: 5px solid #1F77B4;
    ">
        <h3 style="margin-top: 0; margin-bottom: 6px; color: #111; font-size: 15px;">📊 Resumen Algoritmo Sweep</h3>
        <p style="margin: 0 0 10px 0; color: #666; font-size: 11px;">Optimizador de Rutas con OSRM</p>
        
        <div style="background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 5px; padding: 8px; margin-bottom: 10px;">
            <b>• Total Vehículos:</b> {len(rutas)}<br>
            <b>• Clientes Atendidos:</b> {sum(len(r) for r in rutas)}<br>
            <b>• Peso Total:</b> {peso_total_entregado:.0f} kg<br>
            <b>• Distancia Total:</b> {distancia_total_flota:.1f} km<br>
        </div>
        
        <h4 style="margin: 10px 0 6px 0; font-size: 13px; color: #333;">Detalle por Vehículo:</h4>
        {''.join(resumen_html_items)}
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(leyenda_html))

    # Control de Capas para activar/desactivar rutas individualmente
    folium.LayerControl(position='topleft').add_to(mapa)

    # Guardar en HTML
    mapa.save(output_html)
    print(f"\n🗺️ ¡Mapa interactivo generado con éxito en: {os.path.abspath(output_html)}")


import shutil
import subprocess

def buscar_ejecutable_git() -> str:
    """Busca el ejecutable de Git en el PATH o en rutas habituales de instalación en Windows."""
    git_cmd = shutil.which("git")
    if git_cmd:
        return git_cmd
    rutas_comunes = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Git\cmd\git.exe")
    ]
    for ruta in rutas_comunes:
        if os.path.exists(ruta):
            return ruta
    return "git"


def sincronizar_con_github(repo_dir: str):
    """
    Agrega, realiza commit y realiza push automático al repositorio GitHub,
    e imprime el enlace público de GitHub Pages.
    """
    git_bin = buscar_ejecutable_git()
    
    if not os.path.exists(repo_dir) or not os.path.exists(os.path.join(repo_dir, ".git")):
        print(f"⚠️ No se encontró la carpeta del repositorio Git en: {repo_dir}")
        return

    print("\n" + "=" * 75)
    print("🚀 PUBLICANDO EN GITHUB Y ENLACE DE GITHUB PAGES")
    print("=" * 75)
    
    def run_git(args: List[str]) -> Tuple[int, str]:
        cmd = [git_bin, "-C", repo_dir] + args
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return res.returncode, res.stdout + res.stderr
        except Exception as e:
            return 1, str(e)

    # 1. git add .
    code, out = run_git(["add", "."])
    if code != 0:
        print(f"⚠️ Error en 'git add': {out.strip()}")
        return

    # 2. git commit
    code, out = run_git(["commit", "-m", "Auto-update: Mapa interactivo Sweep Algorithm y ruteo OSRM"])
    if "nothing to commit" in out.lower() or "nada para hacer commit" in out.lower():
        print("ℹ️ No hay cambios nuevos en los archivos para commitear.")
    elif code == 0:
        print("✅ Cambios guardados (commit) en el repositorio local.")
    else:
        print(f"ℹ️ Estado commit: {out.strip()}")

    # 3. git push origin main
    print("🌐 Subiendo archivos a GitHub (git push origin main)...")
    code, out = run_git(["push", "origin", "main"])
    if code == 0:
        print("✅ ¡Archivos subidos exitosamente a GitHub!")
    else:
        # Reintentar con HEAD por si la rama predeterminada cambia
        code2, out2 = run_git(["push", "origin", "HEAD"])
        if code2 == 0:
            print("✅ ¡Archivos subidos exitosamente a GitHub!")
        else:
            print(f"⚠️ Nota de git push: {out2.strip()}")

    # 4. Construir URL pública de GitHub Pages
    code, remote_url = run_git(["config", "--get", "remote.origin.url"])
    url_publica = "https://blanquicettsarmientogeissel-prog.github.io/sweep-algorithm/"
    
    remote_clean = remote_url.strip()
    if "@github.com/" in remote_clean:
        repo_path = remote_clean.split("@github.com/")[1]
    elif "github.com/" in remote_clean:
        repo_path = remote_clean.split("github.com/")[1]
    else:
        repo_path = ""

    if repo_path:
        repo_path = repo_path.removesuffix(".git")
        parts = repo_path.split("/")
        if len(parts) >= 2:
            user, repo = parts[0], parts[1]
            url_publica = f"https://{user}.github.io/{repo}/"

    print("\n" + "⭐" * 40)
    print("🌍 ¡TU MAPA INTERACTIVO ESTÁ PUBLICADO EN EL SIGUIENTE ENLACE PÚBLICO! 🌍")
    print(f"👉 Link Directo: {url_publica}")
    print("⭐" * 40)
    print("\n💡 INSTRUCCIONES DE ACCESO:")
    print("   • Si acabas de hacer la primera publicación, GitHub Pages compilará el sitio en 1-2 minutos.")
    print("   • Si aún no has activado GitHub Pages en tu cuenta, hazlo en 10 segundos:")
    print("     1. Entra a tu repositorio: https://github.com/blanquicettsarmientogeissel-prog/sweep-algorithm")
    print("     2. Ve a 'Settings' (Configuración) -> 'Pages'.")
    print("     3. En 'Source', selecciona 'Deploy from a branch'.")
    print("     4. En 'Branch', selecciona 'main' y la carpeta '/ (root)', y presiona 'Save'.")
    print("   • A partir de ese momento, cada vez que ejecutes este script, el enlace público se actualizará automáticamente.\n")


# =============================================================================
# 5. FUNCIÓN PRINCIPAL / EJECUCIÓN
# =============================================================================

def ejecutar_ruteo_sweep(csv_file: str, capacidad_vehiculo: float, output_html: str):
    print("=" * 75)
    print("   OPTIMIZACIÓN DE RUTAS CON ALGORITMO DEL BARRIDO (SWEEP) Y OSRM")
    print("=" * 75)

    # 1. Cargar datos desde el archivo CSV
    deposito, clientes = cargar_datos_csv(csv_file)

    # 2. Aplicar Heurística de Barrido (Sweep Algorithm)
    rutas = aplicar_sweep_algorithm(
        deposito=deposito,
        clientes=clientes,
        capacidad_vehiculo=capacidad_vehiculo
    )

    # 3. Obtener trazados exactos de carretera y distancia mediante la API OSRM
    print("\n🌐 Obteniendo geometrías y distancias reales de la malla vial con OSRM...")
    detalles_rutas = []
    for idx, r in enumerate(rutas, start=1):
        # Crear la secuencia completa: Bodega -> Cliente 1 -> ... -> Cliente K -> Bodega
        secuencia_completa = [deposito] + r + [deposito]
        detalle = obtener_ruta_osrm(secuencia_completa)
        detalles_rutas.append(detalle)
        print(f"   🚗 Vehículo #{idx:02d}: {len(r):2d} clientes | Distancia: {detalle['distancia_km']:6.2f} km | Tiempo: {detalle['duracion_min']:5.1f} min")

    # 4. Generar el mapa interactivo HTML
    crear_mapa_interactivo(
        deposito=deposito,
        rutas=rutas,
        detalles_rutas=detalles_rutas,
        capacidad_vehiculo=capacidad_vehiculo,
        output_html=output_html
    )

    # 5. Copiar mapa generado a la carpeta del Repositorio Clonado
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.join(script_dir, "Git", "sweep-algorithm")
    if not os.path.exists(repo_dir):
        repo_dir = r"C:\Users\gilbe\Downloads\Sweep Algorithm\Git\sweep-algorithm"

    if os.path.exists(repo_dir):
        # index.html es necesario para que GitHub Pages lo sirva por defecto
        index_target = os.path.join(repo_dir, "index.html")
        mapa_target = os.path.join(repo_dir, "mapa_rutas_sweep.html")
        
        shutil.copyfile(output_html, index_target)
        shutil.copyfile(output_html, mapa_target)
        print(f"📁 Copiado mapa a la carpeta Git: {index_target}")

        # Copiar archivos fuente del proyecto a la carpeta clonada
        for file_name in ["sweep_routing_osrm.py", "requirements.txt", "Direccciones para trabajo de Rutas.csv", "generate_map.ps1"]:
            src_path = os.path.join(script_dir, file_name)
            dst_path = os.path.join(repo_dir, file_name)
            if os.path.exists(src_path):
                shutil.copyfile(src_path, dst_path)

        # 6. Sincronizar automáticamente con GitHub
        sincronizar_con_github(repo_dir)

    print("\n✅ Proceso completado exitosamente.")
    print(f"💡 Para visualizar las rutas localmente, abre el archivo '{output_html}' en tu navegador web.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generador de rutas VRP usando la heurística del Sweep Algorithm y la API de OSRM."
    )
    parser.add_argument(
        "--csv", 
        default="Direccciones para trabajo de Rutas.csv",
        help="Ruta al archivo CSV con las direcciones y coordenadas (por defecto: 'Direccciones para trabajo de Rutas.csv')."
    )
    parser.add_argument(
        "--capacidad", 
        type=float, 
        default=600.0,
        help="Capacidad máxima de carga por vehículo en kg (por defecto: 600.0)."
    )
    parser.add_argument(
        "--output", 
        default="mapa_rutas_sweep.html",
        help="Nombre del archivo HTML del mapa interactivo de salida (por defecto: 'mapa_rutas_sweep.html')."
    )

    args = parser.parse_args()

    # Si se ejecuta directamente sin argumentos o con archivo relativo por defecto
    ruta_csv = args.csv
    if not os.path.exists(ruta_csv):
        # Probar ruta en el directorio actual
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alt_csv = os.path.join(script_dir, "Direccciones para trabajo de Rutas.csv")
        if os.path.exists(alt_csv):
            ruta_csv = alt_csv

    ejecutar_ruteo_sweep(
        csv_file=ruta_csv,
        capacidad_vehiculo=args.capacidad,
        output_html=args.output
    )

