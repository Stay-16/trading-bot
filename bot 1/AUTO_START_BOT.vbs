' Auto-start launcher — لا يظهر أي نافذة
' Task Scheduler: schtasks /create /tn "Bot1" /tr "wscript.exe C:\full\path\AUTO_START_BOT.vbs" /sc onlogon /delay 0000:30 /rl highest

Dim shell, fso
Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

botDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = botDir

' تشغيل البوت — مخفي تماماً
shell.Run "python main.py", 0, False

WScript.Sleep 3000

' تشغيل WebApp — مخفي تماماً
shell.Run "python run_webapp.py", 0, False
