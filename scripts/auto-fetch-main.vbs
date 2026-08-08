' Launches auto-fetch-main.ps1 with no visible console window.
' Task Scheduler running powershell.exe directly flashes a console on every
' run; WScript.Shell.Run with intWindowStyle 0 suppresses it completely.
Option Explicit

Dim shell, fso, scriptDir, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
' No -ExecutionPolicy override: LocalMachine is RemoteSigned and these scripts
' are local and unsigned, which RemoteSigned already permits.
command = "powershell.exe -NoProfile -NonInteractive -File """ & _
          scriptDir & "\auto-fetch-main.ps1"""

' 0 = hidden window, False = do not wait for completion.
shell.Run command, 0, False
