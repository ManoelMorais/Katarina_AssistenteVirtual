Dim root
root = Replace(WScript.ScriptFullName, "launcher\run_servidor.vbs", "")
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & root & "core"" && python -m uvicorn servidor:app --host 0.0.0.0 --port 8000", 0, False
