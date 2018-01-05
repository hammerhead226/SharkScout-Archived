cd "%~dp0"

:: Create virtualenv
pip3 install --upgrade virtualenv
rmdir /S /Q venv
virtualenv venv
venv\Scripts\pip3 install backoff cherrypy^<11 genshi psutil pymongo pynumparser requests tqdm ws4py

:: Syntax test the script
venv\Scripts\python SharkScout.py -h > nul
if %errorlevel% neq 0 (
	rmdir /S /Q venv
	exit /B 1
)

:: Run pyinstaller
rmdir /S /Q dist
venv\Scripts\pip3 install pyinstaller
venv\Scripts\pyinstaller --noconfirm --clean --onefile --add-data "config.json;." --icon "venv\Scripts\python.exe,0" SharkScout.py
del /F SharkScout.spec
rmdir /S /Q __pycache__
rmdir /S /Q build

:: Syntax test the compiled script
cd dist
SharkScout.exe -h
if %errorlevel% neq 0 (
	cd ..
	rmdir /S /Q dist
	exit /B 1
)
cd ..

:: Copy files for distribution
copy LICENSE* dist\
copy README* dist\
echo .rar\ > exclude
xcopy www dist\www /S /V /I /Y /EXCLUDE:exclude
del /F exclude

:: Export TBA data for this year and next year
cd dist
for /f "skip=1 tokens=1-6" %%A in ('WMIC Path Win32_LocalTime Get Day^,Hour^,Minute^,Month^,Second^,Year /Format:table') do (
    if "%%B" NEQ "" (
        set /A FDATE=%%F*10000+%%D*100+%%A
        set /A FTIME=%%B*10000+%%C*100+%%E
    )
)
set YEAR_CURR=%FDATE:~0,4%
set /A YEAR_NEXT=%YEAR_CURR%+1
SharkScout.exe -ut -uti -ue "1992-%YEAR_NEXT%" -uei "%YEAR_CURR%-%YEAR_NEXT%" --dump mongodump.gz
if %errorlevel% neq 0 (
	cd ..
	rmdir /S /Q dist
	exit /B 1
)

:: Run the test script
..\venv\Scripts\pip3 install requests scrapy
..\venv\Scripts\python ..\SharkScout-Test.py SharkScout.exe --no-browser
if %errorlevel% neq 0 (
	cd ..
	rmdir /S /Q dist
	rmdir /S /Q venv
	exit /B 1
)

rmdir /S /Q mongo
cd ..
rmdir /S /Q venv

:: Make a distribution zip
for /f %%i in ('git rev-parse HEAD') do set HASH=%%i
del /F SharkScout-%HASH:~0,7%-x86.zip
powershell -nologo -noprofile -command "& { Add-Type -A 'System.IO.Compression.FileSystem'; [IO.Compression.ZipFile]::CreateFromDirectory('dist', 'SharkScout-%HASH:~0,7%-x86.zip'); }"
if %errorlevel% equ 0 rmdir /S /Q dist
