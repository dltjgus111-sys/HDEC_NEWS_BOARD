@echo off
chcp 949 >nul
cd /d "%~dp0"
echo.
echo  ================================================
echo   건설 뉴스 보드 - 내 컴퓨터에서 테스트 실행
echo  ================================================
echo.

where python >nul 2>&1
if errorlevel 1 goto nopython

echo  뉴스를 수집하는 중입니다. 30초 정도 걸립니다...
echo.
python "scripts/build_news.py"
if errorlevel 1 goto failed

echo.
echo  [완료] 보드판을 브라우저로 엽니다.
start "" "index.html"
echo.
pause
exit /b 0

:nopython
echo  [오류] python 을 찾을 수 없습니다.
echo         https://www.python.org 에서 설치한 뒤 다시 실행하세요.
echo         설치 화면에서 "Add Python to PATH" 를 반드시 체크하세요.
echo.
pause
exit /b 1

:failed
echo.
echo  [실패] 위 메시지를 확인하세요.
echo         기사가 0건이면 data.js 는 그대로 유지됩니다.
echo.
pause
exit /b 1
