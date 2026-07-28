Add-Type -AssemblyName System.Web

$csvPath = "Direccciones para trabajo de Rutas.csv"
$capacidadVehiculo = 600.0
$outputPath = "mapa_rutas_sweep.html"

Write-Host "Leyendo archivo CSV: $csvPath..."
$lines = Get-Content -Path $csvPath -Encoding UTF8

$deposito = $null
$clientes = @()

# Parser del CSV
for ($i = 1; $i -lt $lines.Count; $i++) {
    $line = $lines[$i].Trim()
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line.Split(';')
    if ($parts.Count -lt 5) { continue }

    $id = $parts[0].Trim()
    $nombre = $parts[1].Trim()
    $direccion = $parts[2].Trim()
    $latStr = $parts[3].Trim().Replace(',', '.')
    $lonStr = $parts[4].Trim().Replace(',', '.')
    $pesoStr = if ($parts.Count -gt 5) { $parts[5].Trim().Replace(',', '.') } else { "0" }

    if ([string]::IsNullOrEmpty($latStr) -or [string]::IsNullOrEmpty($lonStr)) { continue }

    [double]$lat = 0
    [double]$lon = 0
    if (-not [double]::TryParse($latStr, [System.Globalization.NumberStyles]::Any, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$lat)) { continue }
    if (-not [double]::TryParse($lonStr, [System.Globalization.NumberStyles]::Any, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$lon)) { continue }

    [double]$peso = 0
    [double]::TryParse($pesoStr, [System.Globalization.NumberStyles]::Any, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$peso) | Out-Null

    $node = @{
        id = $id
        nombre = $nombre
        direccion = $direccion
        lat = $lat
        lon = $lon
        peso = $peso
    }

    if ($id -eq "0" -or $nombre.ToLower().Contains("bodega")) {
        $deposito = $node
    } else {
        $clientes += $node
    }
}

Write-Host "Bodega identificada: $($deposito.nombre) ($($deposito.lat), $($deposito.lon))"
Write-Host "Total clientes cargados: $($clientes.Count)"

# Algoritmo del Barrido (Sweep Algorithm)
$depLat = $deposito.lat
$depLon = $deposito.lon

foreach ($c in $clientes) {
    $dLat = $c.lat - $depLat
    $dLon = $c.lon - $depLon
    $rad = [Math]::Atan2($dLat, $dLon)
    $deg = ($rad * 180.0 / [Math]::PI)
    if ($deg -lt 0) { $deg += 360 }
    $c['angulo'] = $deg
}

# Ordenar por ángulo Sweep
$clientesOrdenados = $clientes | Sort-Object { $_['angulo'] }

# Agrupar en rutas respetando capacidad del vehículo
$rutas = @()
$rutaActual = @()
$cargaActual = 0.0

foreach ($c in $clientesOrdenados) {
    $pesoC = $c['peso']
    if ($cargaActual + $pesoC -le $capacidadVehiculo) {
        $rutaActual += $c
        $cargaActual += $pesoC
    } else {
        $rutas += ,$rutaActual
        $rutaActual = @($c)
        $cargaActual = $pesoC
    }
}
if ($rutaActual.Count -gt 0) {
    $rutas += ,$rutaActual
}

Write-Host "Se generaron $($rutas.Count) rutas con el Sweep Algorithm."

# Colores vivos para diferenciar las rutas
$colores = @('#1F77B4', '#FF7F0E', '#2CA02C', '#D62728', '#9467BD', '#8C564B', '#E377C2', '#BCBD22', '#17BECF', '#E63946', '#2A9D8F', '#F4A261', '#E76F51', '#457B9D')

# Consultar OSRM API para obtener geometrías de carretera
$detallesRutas = @()
$client = New-Object System.Net.WebClient
$client.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

for ($rIdx = 0; $rIdx -lt $rutas.Count; $rIdx++) {
    $r = $rutas[$rIdx]
    $nodesSeq = @($deposito) + $r + @($deposito)
    
    $coordsStr = ($nodesSeq | ForEach-Object { "$($_.lon.ToString('0.000000', [System.Globalization.CultureInfo]::InvariantCulture)),$($_.lat.ToString('0.000000', [System.Globalization.CultureInfo]::InvariantCulture))" }) -join ";"
    $url = "http://router.project-osrm.org/route/v1/driving/$coordsStr`?overview=full&geometries=geojson"
    
    Write-Host "Obteniendo ruta OSRM para Vehículo #$($rIdx+1) de $($rutas.Count)..."
    
    $geomList = @()
    [double]$distKm = 0
    [double]$durMin = 0

    try {
        $jsonStr = $client.DownloadString($url)
        $jsonObj = $jsonStr | ConvertFrom-Json
        if ($jsonObj.code -eq "Ok" -and $jsonObj.routes.Count -gt 0) {
            $distKm = [Math]::Round($jsonObj.routes[0].distance / 1000.0, 2)
            $durMin = [Math]::Round($jsonObj.routes[0].duration / 60.0, 1)
            $coords = $jsonObj.routes[0].geometry.coordinates
            foreach ($pt in $coords) {
                # [lat, lon]
                $latVal = $pt[1].ToString([System.Globalization.CultureInfo]::InvariantCulture)
                $lonVal = $pt[0].ToString([System.Globalization.CultureInfo]::InvariantCulture)
                $geomList += "[$latVal, $lonVal]"
            }
        }
    } catch {
        Write-Host "Servidor OSRM no disponible para la ruta $($rIdx+1). Usando trazado directo."
        foreach ($n in $nodesSeq) {
            $latVal = $n.lat.ToString([System.Globalization.CultureInfo]::InvariantCulture)
            $lonVal = $n.lon.ToString([System.Globalization.CultureInfo]::InvariantCulture)
            $geomList += "[$latVal, $lonVal]"
        }
    }

    $detallesRutas += @{
        geometria = $geomList
        distanciaKm = $distKm
        duracionMin = $durMin
    }
    Start-Sleep -Milliseconds 250
}

# Construir objeto JavaScript para Leaflet
$jsRutasData = @()
for ($rIdx = 0; $rIdx -lt $rutas.Count; $rIdx++) {
    $r = $rutas[$rIdx]
    $d = $detallesRutas[$rIdx]
    $color = $colores[$rIdx % $colores.Count]
    
    $pesoRuta = 0
    foreach ($c in $r) { $pesoRuta += $c.peso }

    $clientesJson = $r | ForEach-Object {
        $nEsc = [System.Web.HttpUtility]::JavaScriptStringEncode($_.nombre)
        $dEsc = [System.Web.HttpUtility]::JavaScriptStringEncode($_.direccion)
        "  { id: '$($_.id)', nombre: '$nEsc', direccion: '$dEsc', lat: $($_.lat.ToString([System.Globalization.CultureInfo]::InvariantCulture)), lon: $($_.lon.ToString([System.Globalization.CultureInfo]::InvariantCulture)), peso: $($_.peso.ToString([System.Globalization.CultureInfo]::InvariantCulture)), angulo: $($_.angulo.ToString('0.1', [System.Globalization.CultureInfo]::InvariantCulture)) }"
    }

    $geomJson = $d.geometria -join ", "

    $jsRutasData += @"
{
    id: $($rIdx + 1),
    color: '$color',
    distanciaKm: $($d.distanciaKm.ToString([System.Globalization.CultureInfo]::InvariantCulture)),
    duracionMin: $($d.duracionMin.ToString([System.Globalization.CultureInfo]::InvariantCulture)),
    pesoTotal: $($pesoRuta.ToString([System.Globalization.CultureInfo]::InvariantCulture)),
    geometria: [$geomJson],
    clientes: [
$($clientesJson -join ",`n")
    ]
}
"@
}

$depNombreEsc = [System.Web.HttpUtility]::JavaScriptStringEncode($deposito.nombre)
$depDirEsc = [System.Web.HttpUtility]::JavaScriptStringEncode($deposito.direccion)
$depositoJson = "{ id: '$($deposito.id)', nombre: '$depNombreEsc', direccion: '$depDirEsc', lat: $($deposito.lat.ToString([System.Globalization.CultureInfo]::InvariantCulture)), lon: $($deposito.lon.ToString([System.Globalization.CultureInfo]::InvariantCulture)) }"

$htmlContent = @"
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mapa de Rutas - Algoritmo del Barrido (Sweep Algorithm) & OSRM</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        body, html { margin: 0; padding: 0; height: 100%; font-family: 'Segoe UI', Roboto, Arial, sans-serif; }
        #map { width: 100%; height: 100vh; }
        
        .dashboard-panel {
            position: absolute;
            top: 15px;
            right: 15px;
            z-index: 1000;
            width: 330px;
            max-height: 90vh;
            overflow-y: auto;
            background: rgba(255, 255, 255, 0.96);
            backdrop-filter: blur(8px);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.25);
            border-left: 6px solid #1F77B4;
        }

        .dashboard-title { margin: 0 0 4px 0; font-size: 17px; font-weight: 700; color: #1e293b; }
        .dashboard-subtitle { margin: 0 0 12px 0; font-size: 12px; color: #64748b; }
        
        .stat-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 14px;
        }
        
        .stat-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 10px;
            text-align: center;
        }

        .stat-val { font-size: 16px; font-weight: 700; color: #0f172a; }
        .stat-lbl { font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: 600; }

        .route-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 8px;
        }

        .route-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-weight: 700;
            font-size: 13px;
            margin-bottom: 4px;
        }

        .route-stats { font-size: 11px; color: #475569; line-height: 1.5; }
        
        .custom-number-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            color: white;
            font-weight: bold;
            font-size: 11px;
            border: 2px solid white;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
        }
    </style>
</head>
<body>
    <div id="map"></div>

    <div class="dashboard-panel">
        <div class="dashboard-title">🌀 Algoritmo Sweep & OSRM</div>
        <div class="dashboard-subtitle">Ruteo de Vehículos VRP — Barranquilla / Soledad</div>
        
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-val" id="totalRutas">0</div>
                <div class="stat-lbl">Vehículos</div>
            </div>
            <div class="stat-card">
                <div class="stat-val" id="totalClientes">0</div>
                <div class="stat-lbl">Clientes</div>
            </div>
            <div class="stat-card">
                <div class="stat-val" id="totalPeso">0 kg</div>
                <div class="stat-lbl">Carga Total</div>
            </div>
            <div class="stat-card">
                <div class="stat-val" id="totalKm">0 km</div>
                <div class="stat-lbl">Distancia OSRM</div>
            </div>
        </div>

        <div style="font-weight: 700; font-size: 12px; color: #334155; margin-bottom: 8px;">Detalle por Ruta de Vehículo:</div>
        <div id="routeList"></div>
    </div>

    <script>
        const deposito = $depositoJson;
        const rutasData = [
$($jsRutasData -join ",`n")
        ];

        // Inicializar mapa
        const map = L.map('map').setView([deposito.lat, deposito.lon], 12);
        
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors, © CARTO'
        }).addTo(map);

        // Icono Depósito
        const depotIcon = L.divIcon({
            html: '<div style="background:#dc2626; color:white; border-radius:50%; width:34px; height:34px; display:flex; align-items:center; justify-content:center; border:3px solid white; box-shadow:0 3px 8px rgba(0,0,0,0.4);"><i class="fa-solid fa-warehouse"></i></div>',
            className: '',
            iconSize: [34, 34],
            iconAnchor: [17, 17]
        });

        L.marker([deposito.lat, deposito.lon], { icon: depotIcon })
            .addTo(map)
            .bindPopup(`
                <div style="font-family:sans-serif; width:220px;">
                    <h4 style="margin:0; color:#dc2626;"><i class="fa-solid fa-warehouse"></i> \${deposito.nombre}</h4>
                    <p style="margin:4px 0; font-size:12px; color:#475569;">\${deposito.direccion}</p>
                    <span style="background:#fee2e2; color:#991b1b; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:bold;">PUNTO ORIGEN Y DESTINO</span>
                </div>
            `);

        let totalClientes = 0;
        let totalPeso = 0;
        let totalKm = 0;

        const routeListDiv = document.getElementById('routeList');

        rutasData.forEach((r, idx) => {
            totalClientes += r.clientes.length;
            totalPeso += parseFloat(r.pesoTotal);
            totalKm += parseFloat(r.distanciaKm);

            // Trazado de línea OSRM
            const polyline = L.polyline(r.geometria, {
                color: r.color,
                weight: 4.5,
                opacity: 0.85
            }).addTo(map);

            polyline.bindTooltip(`Ruta #\${r.id} | \${r.distanciaKm} km | \${r.duracionMin} min`, { sticky: true });

            // Marcadores de Clientes
            r.clientes.forEach((c, stopIdx) => {
                const numberIcon = L.divIcon({
                    html: `<div class="custom-number-icon" style="background:\${r.color}; width:24px; height:24px;">\${stopIdx + 1}</div>`,
                    className: '',
                    iconSize: [24, 24],
                    iconAnchor: [12, 12]
                });

                L.marker([c.lat, c.lon], { icon: numberIcon })
                    .addTo(map)
                    .bindPopup(`
                        <div style="font-family:sans-serif; min-width:210px;">
                            <div style="background:\${r.color}; color:white; padding:3px 6px; border-radius:4px; font-weight:bold; font-size:11px; margin-bottom:6px;">
                                Ruta #\${r.id} — Parada \${stopIdx + 1} de \${r.clientes.length}
                            </div>
                            <h4 style="margin:0 0 4px 0;">📍 \${c.nombre} (ID: \${c.id})</h4>
                            <div style="font-size:12px; color:#475569;">
                                <b>Dirección:</b> \${c.direccion}<br>
                                <b>Demanda / Peso:</b> <span style="color:#16a34a; font-weight:bold;">\${c.peso} kg</span><br>
                                <b>Ángulo Sweep:</b> \${c.angulo}°
                            </div>
                        </div>
                    `);
            });

            // Card resumen por ruta
            const card = document.createElement('div');
            card.className = 'route-card';
            card.innerHTML = `
                <div class="route-header">
                    <span style="color:\${r.color}">● Vehículo #\${r.id}</span>
                    <span style="font-size:11px; background:#f1f5f9; padding:2px 6px; border-radius:4px;">\${r.clientes.length} paradas</span>
                </div>
                <div class="route-stats">
                    • Carga acumulada: <b>\${r.pesoTotal} / $capacidadVehiculo kg</b><br>
                    • Distancia por carretera: <b>\${r.distanciaKm} km</b><br>
                    • Tiempo estimado OSRM: <b>\${r.duracionMin} min</b>
                </div>
            `;
            routeListDiv.appendChild(card);
        });

        document.getElementById('totalRutas').innerText = rutasData.length;
        document.getElementById('totalClientes').innerText = totalClientes;
        document.getElementById('totalPeso').innerText = totalPeso + " kg";
        document.getElementById('totalKm').innerText = totalKm.toFixed(1) + " km";
    </script>
</body>
</html>
"@

[System.IO.File]::WriteAllText((Join-Path (Get-Location) $outputPath), $htmlContent, [System.Text.Encoding]::UTF8)
Write-Host "✅ Mapa interactivo creado exitosamente en: $outputPath"

$gitRepoDir = Join-Path (Get-Location) "Git\sweep-algorithm"
if (Test-Path $gitRepoDir) {
    $indexPath = Join-Path $gitRepoDir "index.html"
    $mapaGitPath = Join-Path $gitRepoDir "mapa_rutas_sweep.html"
    
    Copy-Item -Path $outputPath -Destination $indexPath -Force
    Copy-Item -Path $outputPath -Destination $mapaGitPath -Force
    Write-Host "📁 Mapa copiado a la carpeta de Git: $indexPath"

    # Copiar archivos fuente del proyecto
    $filesToCopy = @("sweep_routing_osrm.py", "requirements.txt", "Direccciones para trabajo de Rutas.csv", "generate_map.ps1")
    foreach ($f in $filesToCopy) {
        if (Test-Path $f) {
            Copy-Item -Path $f -Destination (Join-Path $gitRepoDir $f) -Force
        }
    }

    $gitExe = if (Test-Path "C:\Program Files\Git\cmd\git.exe") { "C:\Program Files\Git\cmd\git.exe" } else { "git" }
    
    Write-Host "`n==========================================================================="
    Write-Host "🚀 PUBLICANDO EN GITHUB Y DEPLOYING A GITHUB PAGES"
    Write-Host "==========================================================================="
    
    & $gitExe -C $gitRepoDir add .
    & $gitExe -C $gitRepoDir commit -m "Auto-update: Mapa interactivo Sweep Algorithm y ruteo OSRM"
    Write-Host "🌐 Subiendo cambios a GitHub..."
    & $gitExe -C $gitRepoDir push origin main

    $pubUrl = "https://blanquicettsarmientogeissel-prog.github.io/sweep-algorithm/"
    Write-Host "`n***************************************************************************"
    Write-Host "🌍 ¡TU MAPA ESTÁ PUBLICADO EN EL SIGUIENTE ENLACE PÚBLICO!"
    Write-Host "🔗 $pubUrl"
    Write-Host "***************************************************************************`n"
}

