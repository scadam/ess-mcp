param([Parameter(Mandatory)][string] $Source, [Parameter(Mandatory)][string] $Commented, [string] $Pdf = '')
# Opens the draft in desktop Word (hidden), adds the demo's two comments the way a person would, saves a Word-authored
# copy, and optionally renders a PDF. Word is always closed, even on failure.
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($Source, $false, $false, $false)
  $word.UserName = 'Scott Adams'
  $word.UserInitials = 'SA'
  $asks = @(
    @{ start = 'Talk to your line manager before making any plans.'; text = '@HR Agent please add our rules for working temporarily from another country: how many days, what needs a panel and what to arrange.' },
    @{ start = 'Use your bank laptop and connect through the VPN.'; text = '@Compliance Agent can you review this section and add what we need to say about client data and conduct when working abroad?' })
  foreach ($ask in $asks) {
    $range = $doc.Content
    $find = $range.Find
    $find.ClearFormatting()
    if (-not $find.Execute($ask.start)) { throw "Text not found: $($ask.start)" }
    $paragraph = $range.Paragraphs(1).Range
    $null = $doc.Comments.Add($paragraph, $ask.text)
  }
  "pages: $($doc.ComputeStatistics(2)) comments: $($doc.Comments.Count) revisions: $($doc.Revisions.Count)"
  $doc.SaveAs2($Commented, 16)
  if ($Pdf) { $doc.ExportAsFixedFormat($Pdf, 17) }
  $doc.Close($false)
} finally {
  $word.Quit($false)
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
exit 0
