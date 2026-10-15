param(
    [string]$SqlPath = (Join-Path $PSScriptRoot '../sql/002_seed_mock_data.sql'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../reports/pictures')
)

# Render the SQL seed directly; no database or additional packages are required.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$sql = Get-Content -LiteralPath $SqlPath -Raw -Encoding UTF8
$features = @()
foreach ($block in [regex]::Matches($sql, '(?s)INSERT INTO gis_lab\.(?<table>\w+).*?VALUES\s*(?<rows>.*?);')) {
    foreach ($row in [regex]::Matches($block.Groups['rows'].Value, "(?m)^\('(?<code>[^']+)',\s*'(?<name>[^']+)'(?<rest>.*)$")) {
        $rest = $row.Groups['rest'].Value
        $geometry = [regex]::Match($rest, "ST_GeomFromText\('(?<wkt>[^']+)',\s*(?<srid>\d+)\)")
        $point = [regex]::Match($rest, 'ST_MakePoint\((?<x>[-\d.]+),\s*(?<y>[-\d.]+)\),\s*(?<srid>\d+)')
        if (-not $geometry.Success -and -not $point.Success) { continue }
        if ($geometry.Success) {
            $wkt = $geometry.Groups['wkt'].Value
            $srid = [int]$geometry.Groups['srid'].Value
        } else {
            $wkt = 'POINT(' + $point.Groups['x'].Value + ' ' + $point.Groups['y'].Value + ')'
            $srid = [int]$point.Groups['srid'].Value
        }
        $rings = @()
        foreach ($ring in [regex]::Matches($wkt, '\(([^()]+)\)')) {
            $points = @()
            foreach ($coordinate in $ring.Groups[1].Value.Split(',')) {
                $xy = $coordinate.Trim() -split '\s+'
                $points += ,@([double]::Parse($xy[0], [cultureinfo]::InvariantCulture), [double]::Parse($xy[1], [cultureinfo]::InvariantCulture))
            }
            $rings += ,$points
        }
        $features += [pscustomobject]@{ Table=$block.Groups['table'].Value; Code=$row.Groups['code'].Value; Name=$row.Groups['name'].Value; Wkt=$wkt; Srid=$srid; Rings=$rings }
    }
}
$business = @($features | Where-Object Table -in @('construction_areas', 'gas_pipelines', 'water_pipelines', 'gas_devices', 'demo_roads'))
if ($business.Count -ne 47 -or $features.Count -ne 51) { throw "Unexpected seed counts: business=$($business.Count), geometries=$($features.Count). Check the SQL parser." }

$ink = [System.Drawing.ColorTranslator]::FromHtml('#183449')
$muted = [System.Drawing.ColorTranslator]::FromHtml('#597082')
$colors = @{
    construction_areas='#86BAA8'; gas_pipelines='#C8483E'; water_pipelines='#227FB5';
    gas_devices='#733EA0'; demo_roads='#6A7481'; invalid_geometry_cases='#C8483E'
}
$fonts = @{}
foreach ($size in @(13,16,18,20,22,26,30,40,46)) {
    $fonts[$size] = [System.Drawing.Font]::new('Microsoft YaHei', $size, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
}

function Text($g, [string]$value, [float]$x, [float]$y, [int]$size=20, $color=$ink) {
    $brush = [System.Drawing.SolidBrush]::new($color)
    $g.DrawString($value, $fonts[$size], $brush, $x, $y)
    $brush.Dispose()
}
function Line($g, $color, [float]$width, [float]$x1, [float]$y1, [float]$x2, [float]$y2) {
    $pen = [System.Drawing.Pen]::new($color,$width)
    $g.DrawLine($pen,$x1,$y1,$x2,$y2)
    $pen.Dispose()
}
function New-Canvas([int]$width,[int]$height) {
    $bitmap = [System.Drawing.Bitmap]::new($width,$height)
    $bitmap.SetResolution(180,180)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::White)
    return @{Bitmap=$bitmap; Graphics=$graphics}
}
function Map-Point($map, $coordinate) {
    return [System.Drawing.PointF]::new(($map.Left + ($coordinate[0]-$map.Xmin)*$map.Scale), ($map.Top + ($map.Ymax-$coordinate[1])*$map.Scale))
}
function Label($g, $map, [string]$value, $coordinate, [float]$dx=0, [float]$dy=0, $color=$ink, [int]$size=16) {
    $p = Map-Point $map $coordinate
    $extent = $g.MeasureString($value,$fonts[$size])
    $x = $p.X + $dx - $extent.Width/2
    $y = $p.Y + $dy - $extent.Height/2
    $back = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(225,255,255,255))
    $g.FillRectangle($back,[float]($x-2),[float]$y,[float]($extent.Width+4),[float]$extent.Height)
    $back.Dispose()
    Text $g $value $x $y $size $color
}
function New-Map($g, $rect, $bounds, [double]$step=500) {
    $scale = [math]::Min($rect[2]/($bounds[1]-$bounds[0]),$rect[3]/($bounds[3]-$bounds[2]))
    $width = ($bounds[1]-$bounds[0])*$scale
    $height = ($bounds[3]-$bounds[2])*$scale
    $map = @{Left=$rect[0]+($rect[2]-$width)/2; Top=$rect[1]+($rect[3]-$height)/2; Width=$width; Height=$height; Scale=$scale; Xmin=$bounds[0]; Xmax=$bounds[1]; Ymin=$bounds[2]; Ymax=$bounds[3]}
    $background = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#F8FAFC'))
    $g.FillRectangle($background,[float]$map.Left,[float]$map.Top,[float]$width,[float]$height)
    $background.Dispose()
    $grid = [System.Drawing.ColorTranslator]::FromHtml('#DEE6EC')
    for ($x=[math]::Ceiling($bounds[0]/$step)*$step; $x -le $bounds[1]; $x+=$step) {
        $p=Map-Point $map @($x,$bounds[2]); Line $g $grid 1 $p.X $map.Top $p.X ($map.Top+$height)
        Text $g ([string]$x) ($p.X-22) ($map.Top+$height+10) 16 $muted
    }
    for ($y=[math]::Ceiling($bounds[2]/$step)*$step; $y -le $bounds[3]; $y+=$step) {
        $p=Map-Point $map @($bounds[0],$y); Line $g $grid 1 $map.Left $p.Y ($map.Left+$width) $p.Y
        Text $g ([string]$y) ($map.Left-58) ($p.Y-10) 16 $muted
    }
    $border=[System.Drawing.Pen]::new($muted,1)
    $g.DrawRectangle($border,[float]$map.Left,[float]$map.Top,[float]$width,[float]$height); $border.Dispose()
    Text $g 'X / m' ($map.Left+$width-45) ($map.Top+$height+38) 16 $muted
    Text $g 'Y / m' ($map.Left-55) ($map.Top-29) 16 $muted
    return $map
}

# Labels use feature codes to keep crowded intersections readable.
$anchors = @{
    A001=@(140,870); A002=@(1740,100); A003=@(740,1800); A004=@(2540,60); A005=@(-300,-440);
    A006=@(800,2520); A007=@(2220,950); A008=@(1280,340); A009=@(3550,1750); A010=@(1540,1510);
    G001=@(700,100); G002=@(800,500); G003=@(230,1000); G004=@(500,-180); G005=@(3200,3000);
    G006=@(750,1500); G007=@(1500,820); G008=@(2450,800); G009=@(300,650); G010=@(230,230);
    G011=@(220,2100); G012=@(-390,-300); W001=@(500,-70); W002=@(1840,840); W003=@(3750,3000);
    W004=@(500,1810); W005=@(-390,-390); W006=@(2300,200); W007=@(300,2400); W008=@(1110,400);
    W009=@(1780,1000); W010=@(1600,600); R001=@(1510,250); R002=@(2010,700); R003=@(3450,100)
}
$offsets = @{
    G001=@(0,18); G002=@(0,-16); G003=@(0,-17); G004=@(30,-8); G005=@(0,-17); G006=@(0,-18);
    G007=@(-30,0); G008=@(25,0); G009=@(-30,0); G010=@(-28,-13); G011=@(0,-17); G012=@(0,-18);
    W001=@(35,0); W002=@(30,0); W003=@(0,-17); W004=@(35,0); W005=@(-25,15); W006=@(32,0);
    W007=@(0,-18); W008=@(0,17); W009=@(0,-17); W010=@(0,-17); R001=@(0,17); R002=@(0,-17); R003=@(0,17);
    D001=@(-24,-18); D002=@(28,-15); D003=@(0,-20); D004=@(32,22); D005=@(-12,22); D006=@(0,-20);
    D007=@(0,-22); D008=@(25,18); D009=@(0,-22); D010=@(32,-12); D011=@(37,13); D012=@(25,-14)
}
function Draw-Features($g, $map, $items, [bool]$labels=$true) {
    $saved=$g.Save()
    $g.SetClip([System.Drawing.RectangleF]::new($map.Left,$map.Top,$map.Width,$map.Height))
    foreach ($table in @('construction_areas','demo_roads','water_pipelines','gas_pipelines','gas_devices','invalid_geometry_cases')) {
        foreach ($feature in $items | Where-Object Table -eq $table) {
            $color=[System.Drawing.ColorTranslator]::FromHtml($colors[$table])
            $pen=[System.Drawing.Pen]::new($color,3)
            if ($table -eq 'water_pipelines') { $pen.Width=4; $pen.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash }
            if ($table -eq 'demo_roads') { $pen.Width=7 }
            if ($feature.Wkt.StartsWith('POLYGON')) {
                $path=[System.Drawing.Drawing2D.GraphicsPath]::new([System.Drawing.Drawing2D.FillMode]::Alternate)
                foreach ($ring in $feature.Rings) {
                    $points=[System.Drawing.PointF[]]@($ring | ForEach-Object { Map-Point $map $_ })
                    $path.AddPolygon($points)
                }
                $fill=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(48,$color))
                if ($feature.Code -eq 'A008') { $pen.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash }
                $g.FillPath($fill,$path); $g.DrawPath($pen,$path)
                $fill.Dispose(); $path.Dispose()
            } elseif ($feature.Wkt.StartsWith('LINESTRING')) {
                $points=[System.Drawing.PointF[]]@($feature.Rings[0] | ForEach-Object { Map-Point $map $_ })
                $g.DrawLines($pen,$points)
                if ($feature.Code -eq 'INV002') {
                    $p=$points[0]; $g.DrawEllipse($pen,($p.X-6),($p.Y-6),12,12)
                }
            } else {
                $p=Map-Point $map $feature.Rings[0][0]
                $fill=[System.Drawing.SolidBrush]::new($color)
                if ($feature.Code -eq 'D011') {
                    $fill.Color=[System.Drawing.ColorTranslator]::FromHtml('#DC821B')
                    $g.FillEllipse($fill,($p.X-8),($p.Y-8),16,16)
                } else { $g.FillEllipse($fill,($p.X-6),($p.Y-6),12,12) }
                $g.DrawEllipse([System.Drawing.Pens]::White,($p.X-6),($p.Y-6),12,12)
                $fill.Dispose()
            }
            $pen.Dispose()
        }
    }
    if ($labels) {
        foreach ($feature in $items) {
            $anchor=$anchors[$feature.Code]
            if (-not $anchor) { $anchor=$feature.Rings[0][0] }
            if ($anchor[0] -lt $map.Xmin -or $anchor[0] -gt $map.Xmax -or $anchor[1] -lt $map.Ymin -or $anchor[1] -gt $map.Ymax) { continue }
            $offset=$offsets[$feature.Code]; if (-not $offset) { $offset=@(0,0) }
            $color=[System.Drawing.ColorTranslator]::FromHtml($colors[$feature.Table])
            if ($feature.Table -eq 'construction_areas') { $color=$ink }
            Label $g $map $feature.Code $anchor $offset[0] $offset[1] $color
        }
    }
    $g.Restore($saved)
}
function Legend($g,[float]$x,[float]$y) {
    $entries=@(@('construction_areas','施工区 · 10'),@('gas_pipelines','燃气管线 · 12'),@('water_pipelines','水务管线 · 10'),@('gas_devices','燃气设备 · 12'),@('demo_roads','模拟道路 · 3'))
    foreach($entry in $entries) {
        $color=[System.Drawing.ColorTranslator]::FromHtml($colors[$entry[0]])
        if ($entry[0] -eq 'gas_devices') {
            $brush=[System.Drawing.SolidBrush]::new($color)
            $g.FillEllipse($brush,($x+14),($y+6),14,14)
            $brush.Dispose()
        } else { Line $g $color 5 $x ($y+13) ($x+42) ($y+13) }
        Text $g $entry[1] ($x+54) $y 20
        $x+=360
    }
}
function Save-Canvas($canvas,[string]$name) {
    $path=Join-Path $OutputDirectory $name
    $canvas.Bitmap.Save($path,[System.Drawing.Imaging.ImageFormat]::Png)
    $canvas.Graphics.Dispose(); $canvas.Bitmap.Dispose()
    Write-Output $path
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$canvas=New-Canvas 2400 2050; $g=$canvas.Graphics
Text $g '模拟城市空间数据 · 全域总览' 95 40 46
Text $g '直接读取 002_seed_mock_data.sql  |  EPSG:3857  |  平面坐标单位：米  |  等比例绘制' 98 108 22 $muted
Legend $g 100 160
$map=New-Map $g @(110,245,2190,1645) @(-650,4100,-650,3250) 500
Draw-Features $g $map $business
$bar=Map-Point $map @(3000,-420)
Line $g $ink 4 $bar.X $bar.Y ($bar.X+500*$map.Scale) $bar.Y
Line $g $ink 2 $bar.X ($bar.Y-6) $bar.X ($bar.Y+6)
Line $g $ink 2 ($bar.X+500*$map.Scale) ($bar.Y-6) ($bar.X+500*$map.Scale) ($bar.Y+6)
Text $g '500 m（图上平面距离）' ($bar.X-5) ($bar.Y+12) 18 $muted
Text $g '读图：A=施工区，G=燃气管线，W=水务管线，D=燃气设备，R=道路；编号与 SQL 一致。' 100 1955 22
Text $g '蓝色虚线与红色实线可重叠；A003 留空为孔洞；橙色 D011 为告警设备。几何异常与 SRID 示例见细节图。' 100 1995 20 $muted
Save-Canvas $canvas 'seed_mock_data_overview.png'

$canvas=New-Canvas 2500 1950; $g=$canvas.Graphics
Text $g '模拟数据细节 · 空间关系与边界案例' 85 35 46
Text $g '上排为业务数据放大图；下排展示 SQL 中的几何异常与坐标系输入。各地图面板独立缩放。' 88 105 22 $muted
Text $g '01  施工一区 / 二区：交叉、重叠与边界接触' 95 175 26
$map=New-Map $g @(105,245,1120,600) @(-100,2050,-250,1150) 250
Draw-Features $g $map $business
Text $g 'G003 / W009 位于北边界；D006 位于 A001 东边界。' 100 910 20 $muted
Text $g 'G004 与 W001 部分重叠，蓝色虚线间隙显示红色管线。' 100 945 20 $muted

Text $g '02  施工三区：孔洞与穿越要素' 1340 175 26
$map=New-Map $g @(1370,245,960,600) @(-50,1050,1050,2050) 200
Draw-Features $g $map $business
Label $g $map '200 m × 200 m 孔洞' @(500,1430) 0 0 $ink 18
Text $g 'D004=(500,1500) 位于孔洞内；D005 位于施工区实体内。' 1340 910 20 $muted
Text $g 'G006、W004 穿过孔洞；孔洞部分不属于 A003。' 1340 945 20 $muted

Line $g ([System.Drawing.ColorTranslator]::FromHtml('#DEE6EC')) 2 85 1000 2400 1000
Text $g '03  几何异常：保留原始坐标' 95 1040 26
$map=New-Map $g @(110,1120,1080,550) @(-15,115,-15,115) 25
$invalid=@($features | Where-Object Table -eq 'invalid_geometry_cases')
Draw-Features $g $map $invalid $false
Label $g $map 'INV001 自相交点 (50,50)' @(50,50) 0 -28 $ink 18
Label $g $map 'INV002 重复点 (10,10)' @(10,10) 135 0 $ink 18
Text $g 'INV001：蝴蝶面自相交；INV002：两个顶点重合，线长为 0。' 100 1730 20 $muted
Text $g '此处展示 SQL 原始几何，未自动修复。' 100 1765 20 $muted

Text $g '04  SRID 输入示例：分别解释坐标' 1340 1040 26
$wgs=@($features | Where-Object Code -eq 'SRID001')[0]
$merc=@($features | Where-Object Code -eq 'SRID002')[0]
$lon=$wgs.Rings[0][0][0]; $lat=$wgs.Rings[0][0][1]
$mx=6378137*$lon*[math]::PI/180
$my=6378137*[math]::Log([math]::Tan([math]::PI/4+$lat*[math]::PI/360))
Text $g 'SRID001  ·  WGS84 输入点' 1340 1130 26
Text $g "原始 EPSG:4326：($lon, $lat)，单位为度" 1340 1190 22
Text $g ('转换为 EPSG:3857：({0:F2}, {1:F2}) m' -f $mx,$my) 1340 1240 22
Text $g '上面的转换值仅作读图说明；SQL 保存的仍是 4326 原始点。' 1340 1290 20 $muted
Text $g 'SRID002  ·  Web Mercator 输入点' 1340 1390 26
Text $g ('原始 EPSG:3857：({0}, {1})，单位为米' -f $merc.Rings[0][0][0],$merc.Rings[0][0][1]) 1340 1450 22
Text $g '目标坐标系同为 3857，坐标保持 (500,500)。' 1340 1500 22
Text $g '示例点单独说明，避免与局部模拟城市混用坐标。' 1340 1580 22 $muted
Text $g 'EPSG:3857 图上距离并非所有纬度上的真实地面距离。' 1340 1630 20 $muted
Text $g 'import_batches 是导入批次元数据，不含几何，因此不绘制空间位置。' 1340 1730 20 $muted
Legend $g 100 1850
Save-Canvas $canvas 'seed_mock_data_details.png'
foreach($font in $fonts.Values) { $font.Dispose() }
Write-Output "Parsed $($features.Count) geometries; rendered $($business.Count) business features plus 4 diagnostic examples."
