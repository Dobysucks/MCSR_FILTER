$ErrorActionPreference = "Stop"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MCSR26SeedFilter --paths . mcsr_filter\__main__.py
Write-Host "Built dist\MCSR26SeedFilter.exe"
