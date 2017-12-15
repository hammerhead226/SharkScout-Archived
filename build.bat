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

copy LICENSE* dist\
copy README* dist\
echo .rar\ > exclude
xcopy www dist\www /S /V /I /Y /EXCLUDE:exclude
del /F exclude

cd dist
for /f "skip=1 tokens=1-6" %%A in ('WMIC Path Win32_LocalTime Get Day^,Hour^,Minute^,Month^,Second^,Year /Format:table') do (
    if "%%B" NEQ "" (
        set /A FDATE=%%F*10000+%%D*100+%%A
        set /A FTIME=%%B*10000+%%C*100+%%E
    )
)
set YEAR_CURR=%FDATE:~0,4%
set /A YEAR_NEXT=%FDATE:~0,4%+1
SharkScout.exe -ut -uti -ue "%YEAR_CURR%-%YEAR_NEXT%" -uei "%YEAR_CURR%-%YEAR_NEXT%" --dump mongodump.gz
if %errorlevel% neq 0 exit /b %errorlevel%
ping localhost -n 4 >NUL
rmdir /S /Q mongo
cd ..

for /f %%i in ('git rev-parse HEAD') do set HASH=%%i
del /F SharkScout-%HASH:~0,7%-x86.zip
powershell -nologo -noprofile -command "& { Add-Type -A 'System.IO.Compression.FileSystem'; [IO.Compression.ZipFile]::CreateFromDirectory('dist', 'SharkScout-%HASH:~0,7%-x86.zip'); }"
if %errorlevel% equ 0 rmdir /S /Q dist
