' JARVIS Silent Launcher - Runs without console window
' Usage: wscript.exe start_jarvis_silent.vbs

Dim objShell, jarvisPath, pythonPath, mainPath

Set objShell = CreateObject("WScript.Shell")

jarvisPath = "C:\Users\paulo\jarvis"
pythonPath = jarvisPath & "\.venv\Scripts\python.exe"
mainPath = jarvisPath & "\main.py"

' Check if virtual environment python exists
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")

If Not fso.FileExists(pythonPath) Then
    pythonPath = "python"
End If

' Change to JARVIS directory
objShell.CurrentDirectory = jarvisPath

' Run JARVIS in voice mode (hidden window)
' 0 = Hidden window
objShell.Run """" & pythonPath & """ """ & mainPath & """ --voice", 0, False

Set objShell = Nothing
Set fso = Nothing