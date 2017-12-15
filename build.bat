cd "%~dp0"

py SharkScout.py -h > nul
if %errorlevel% neq 0 exit /b %errorlevel%

pip3 install --upgrade pyinstaller
rmdir /S /Q dist
for /f %%i in ('where python') do set PYTHON=%%i
pyinstaller --noconfirm --clean --onefile --add-data "config.json;." --exclude-module matplotlib --exclude-module PyQt5 --icon "%PYTHON%,0" SharkScout.py
del /F SharkScout.spec
rmdir /S /Q __pycache__
rmdir /S /Q build

copy LICENSE dist\
copy README* dist\
echo .rar\ > exclude
xcopy www dist\www /S /V /I /Y /EXCLUDE:exclude
del /F exclude

for /f %%i in ('git rev-parse HEAD') do set HASH=%%i
del /F SharkScout-%HASH:~0,7%-x86.zip
powershell -nologo -noprofile -command "& { Add-Type -A 'System.IO.Compression.FileSystem'; [IO.Compression.ZipFile]::CreateFromDirectory('dist', 'SharkScout-%HASH:~0,7%-x86.zip'); }"
if %errorlevel% equ 0 rmdir /S /Q dist
