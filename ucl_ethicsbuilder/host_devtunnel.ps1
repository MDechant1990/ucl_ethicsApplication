# Share the Ethics Builder with colleagues through a Microsoft Dev Tunnel (UCL accounts only).
#
# One-off setup (already done once; repeat only if the tunnel expired or was deleted):
#   devtunnel user login                                    # sign in with your UCL account
#   devtunnel create ucl-ethics-builder -d "UCL Ethics Builder (test)" -e 30d
#   devtunnel port create ucl-ethics-builder -p 8501 --protocol http
#   devtunnel access create ucl-ethics-builder --tenant     # everyone in the UCL tenant, nobody else
#
# Each time:  powershell -ExecutionPolicy Bypass -File host_devtunnel.ps1
# Stop with Ctrl+C (stops the tunnel and the app). Never add anonymous access (-a / --allow-anonymous).

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tunnel = "ucl-ethics-builder"

# App in hosted mode, reachable only from this computer; the tunnel is the only way in from outside.
$env:ETHICS_HOSTED = "1"
$app = Start-Process -PassThru -NoNewWindow -WorkingDirectory $here `
    -FilePath "$here\.venv\Scripts\streamlit.exe" `
    -ArgumentList "run", "app.py", "--server.address", "localhost", "--server.port", "8501", "--server.headless", "true"

try {
    devtunnel show $tunnel
    devtunnel host $tunnel        # prints the https://...devtunnels.ms link to share
}
finally {
    Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
}
