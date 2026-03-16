Dim root
root = Replace(WScript.ScriptFullName, "launcher\run_loop.vbs", "")
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & root & "core"" && python loop_autonomo.py", 0, False
