Dim root
root = Replace(WScript.ScriptFullName, "launcher\run_voz.vbs", "")
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & root & "core"" && python voz.py", 0, False
