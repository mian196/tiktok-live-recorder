Set WshShell = CreateObject("WScript.Shell")
strPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.CurrentDirectory = strPath
WshShell.Run "cmd /c """ & strPath & "start.bat""", 0, False
Set WshShell = Nothing
