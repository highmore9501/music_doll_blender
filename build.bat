@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  MusicDollBlender 打包脚本
rem  功能: 把 src 目录下的插件代码打包成 zip, 再重命名为
rem        根目录的 music_doll_blender.zip
rem  结果与 scripts\make_zip.py 生成的 zip 一致:
rem        顶层目录为 music_doll_blender
rem        不含 __pycache__ 与 .pyc 文件
rem  用法: 双击运行, 或命令行执行 build.bat
rem        加 --no-pause 参数则结束后不暂停
rem ============================================================

cd /d "%~dp0"

set "ROOT_DIR=%~dp0"
set "SOURCE_DIR=%ROOT_DIR%src"
set "FINAL_ZIP=%ROOT_DIR%music_doll_blender.zip"
set "TEMP_ZIP=%ROOT_DIR%music_doll_blender.new.zip"
set "PLUGIN_NAME=music_doll_blender"

if not exist "%SOURCE_DIR%\__init__.py" goto missing_source

echo [1/2] 打包 src 到临时 zip ...
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $source_dir='%SOURCE_DIR%'; $zip_path='%TEMP_ZIP%'; $top_dir='%PLUGIN_NAME%'; if(Test-Path -LiteralPath $zip_path){Remove-Item -LiteralPath $zip_path -Force}; $zip_archive=[System.IO.Compression.ZipFile]::Open($zip_path,'Create'); try{ $source_files=Get-ChildItem -LiteralPath $source_dir -Recurse -File | Where-Object { ($_.FullName -notlike '*\__pycache__\*') -and ($_.Extension -ne '.pyc') }; foreach($source_file in $source_files){ $relative_path=$source_file.FullName.Substring($source_dir.Length+1).Replace('\','/'); [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip_archive, $source_file.FullName, $top_dir + '/' + $relative_path, 'Optimal') }; Write-Host ('    packed files: ' + $source_files.Count) } finally { $zip_archive.Dispose() }"
if errorlevel 1 goto pack_failed
if not exist "%TEMP_ZIP%" goto pack_failed

echo [2/2] 重命名 zip 为 music_doll_blender.zip ...
move /y "%TEMP_ZIP%" "%FINAL_ZIP%" >nul
if errorlevel 1 goto rename_failed

echo.
echo 完成: %FINAL_ZIP%
call :print_size "%FINAL_ZIP%"
set "EXIT_CODE=0"
goto finish

:missing_source
echo.
echo 错误: 找不到 %SOURCE_DIR%\__init__.py
echo       请把 build.bat 放在仓库根目录后重新运行
set "EXIT_CODE=1"
goto finish

:pack_failed
echo.
echo 错误: 打包 zip 失败, 请查看上面的报错信息
if exist "%TEMP_ZIP%" del /f /q "%TEMP_ZIP%"
set "EXIT_CODE=1"
goto finish

:rename_failed
echo.
echo 错误: 重命名 zip 失败, 请确认 %FINAL_ZIP% 未被占用
set "EXIT_CODE=1"
goto finish

:finish
if /i "%~1"=="--no-pause" goto end
echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause
:end
endlocal & exit /b %EXIT_CODE%

rem 子过程: 用 %~z1 取文件大小并打印
:print_size
echo       大小 %~z1 字节
goto :eof
