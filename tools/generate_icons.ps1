$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$iconDir = Join-Path $PSScriptRoot '..\static\img\icons'
$iconDir = [System.IO.Path]::GetFullPath($iconDir)
if (-not (Test-Path $iconDir)) {
    New-Item -ItemType Directory -Path $iconDir | Out-Null
}

$sizes = 48,72,96,120,128,144,152,167,180,192,256,384,512

foreach ($size in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#1E1B4B'))

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $radius = [Math]::Max(6, [int]($size * 0.18))
    $diameter = $radius * 2
    $path.AddArc(0, 0, $diameter, $diameter, 180, 90)
    $path.AddArc($size - $diameter, 0, $diameter, $diameter, 270, 90)
    $path.AddArc($size - $diameter, $size - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc(0, $size - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()

    $shadowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(32, 245, 158, 11))
    $panelBrush = New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml('#F8FAFC'))
    $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml('#1E1B4B'))
    $sf = New-Object System.Drawing.StringFormat
    $sf.Alignment = 'Center'
    $sf.LineAlignment = 'Center'

    $graphics.FillPath($shadowBrush, $path)
    $graphics.FillPath($panelBrush, $path)

    $fontSize = [Math]::Max(8, [int]($size * 0.34))
    $font = New-Object System.Drawing.Font('Arial', $fontSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $graphics.DrawString('PP', $font, $textBrush, 0, 0, $sf)

    $outputPath = Join-Path $iconDir "icon-$size.png"
    $bmp.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)

    $graphics.Dispose()
    $bmp.Dispose()
    $font.Dispose()
    $shadowBrush.Dispose()
    $panelBrush.Dispose()
    $textBrush.Dispose()
    $path.Dispose()
    $sf.Dispose()
}

Get-ChildItem $iconDir -Filter 'icon-*.png' | Sort-Object Name | Select-Object -ExpandProperty Name
