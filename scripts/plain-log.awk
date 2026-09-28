# Terminal output bypasses this filter. Keep every log line and warning, removing
# ANSI SGR decoration and known status icons; flush each complete line promptly.
BEGIN { escape = sprintf("%c", 27) }
{
  gsub(escape "\\[[0-9;]*m", "")
  sub(/^(⏳|✅|⏭️|⚠️|❌|ℹ️|📌) \[/, "[")
  print
  fflush()
}
