Dim root
root = Replace(WScript.ScriptFullName, "launcher\run_telegram.vbs", "")
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & root & "interfaces"" && node telegram.js", 0, False
