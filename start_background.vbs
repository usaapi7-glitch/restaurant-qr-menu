Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
repoDir = fso.GetParentFolderName(WScript.ScriptFullName)

cmd = "cmd /c cd /d """ & repoDir & """ && (if not exist ""venv"" (python -m venv venv && venv\Scripts\pip install -r requirements.txt)) && venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8085 > """ & repoDir & "\server.log"" 2>&1"
shell.Run cmd, 0, False

MsgBox "Restaurant QR Menu Server background mein start ho gaya hai!" & vbCrLf & "URL: http://localhost:8085/admin" & vbCrLf & vbCrLf & "Band karne ke liye stop_server.bat chalayein.", 64, "Restaurant QR Menu"
