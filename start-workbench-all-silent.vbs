Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & root & "\scripts\start-workbench-all.ps1"" -Background"
exitCode = shell.Run(cmd, 0, True)

If exitCode <> 0 Then
  MsgBox "Market Workbench 启动失败。" & vbCrLf & vbCrLf & "请查看日志：" & vbCrLf & root & "\data\run\workbench\" & vbCrLf & vbCrLf & "或双击 start-workbench-all-background.cmd 查看详细错误。", vbCritical, "Market Workbench"
Else
  shell.Run "http://127.0.0.1:5180/workbench.html", 1, False
  MsgBox "Market Workbench 已在后台启动。" & vbCrLf & vbCrLf & "页面: http://127.0.0.1:5180/workbench.html" & vbCrLf & "停止: 双击 stop-workbench-all.cmd", vbInformation, "Market Workbench"
End If
