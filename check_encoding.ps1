$bytes = [System.IO.File]::ReadAllBytes('c:\Users\User\Desktop\tt\Whatsapp_Chatbot\frontend\flows.html')
Write-Host "First 4 bytes (hex):"
Write-Host ($bytes[0].ToString('X2'))
Write-Host ($bytes[1].ToString('X2'))
Write-Host ($bytes[2].ToString('X2'))
Write-Host ($bytes[3].ToString('X2'))
Write-Host "File size: $($bytes.Length) bytes"

# Check if UTF-16 LE BOM
if ($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
    Write-Host "Encoding: UTF-16 LE (BOM detected)"
} elseif ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
    Write-Host "Encoding: UTF-16 BE (BOM detected)"
} elseif ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "Encoding: UTF-8 with BOM"
} else {
    Write-Host "Encoding: UTF-8 (no BOM) or ASCII"
}
