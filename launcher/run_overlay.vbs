Dim root
root = Replace(WScript.ScriptFullName, "launcher\run_overlay.vbs", "")
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & root & "overlay"" && npx electron .", 0, False
