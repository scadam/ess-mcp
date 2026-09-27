param([Parameter(Mandatory)][string] $Path, [string] $Pdf = '')
# Opens the colleagues' output read-only in desktop Word: lists revisions and the comment threads, optionally
# exports a PDF with markup, then accepts everything in memory and prints the resulting section text.
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($Path, $false, $true, $false)
  "opened: pages=$($doc.ComputeStatistics(2)) revisions=$($doc.Revisions.Count) comments=$($doc.Comments.Count)"
  foreach ($revision in $doc.Revisions) {
    $kind = @{ 1 = 'insert'; 2 = 'delete' }[[int]$revision.Type]
    $text = ($revision.Range.Text -replace '\s+', ' ').Trim()
    "  revision: $($revision.Author) $kind '$($text.Substring(0, [Math]::Min(70, $text.Length)))'"
  }
  foreach ($comment in $doc.Comments) {
    $parent = if ($comment.Ancestor) { " (reply to $($comment.Ancestor.Author))" } else { " on '$(($comment.Scope.Text).Substring(0, 30))...'" }
    $text = $comment.Range.Text
    "  comment: $($comment.Author)$parent : $($text.Substring(0, [Math]::Min(80, $text.Length)))"
  }
  if ($Pdf) { $doc.ExportAsFixedFormat($Pdf, 17, $false, 0, 0, 1, 1, 7) }
  $doc.Revisions.AcceptAll()
  $inSection = $false
  foreach ($paragraph in $doc.Paragraphs) {
    $text = ($paragraph.Range.Text -replace '[\r\a]', '').Trim()
    if ($text -match '^[46]\. ') { $inSection = $text -match '^4\. ' }
    if ($text -match '^5\. ') { $inSection = $true }
    if ($inSection -and $text) { "  accepted: $text" }
  }
  $doc.Close($false)
} finally {
  $word.Quit($false)
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
exit 0
