;
; The portable editions as one file: an EXE that opens itself, once, into a
; folder the listener picks, then runs the player from there. No installation
; and nothing in the registry: the folder holds the program and its data
; (data\), and can be carried to another computer. The folder it offers is the
; user's own programs folder (%LOCALAPPDATA%\Programs\Hamenagen): no
; administrator needed, and the player can update itself there. Program Files
; would ask for permission at every update.
;
; Speed: the program (about 1.25GB with the AI model) travels inside as one 7z
; archive made of 128MB blocks, stored as is, and 7-Zip opens it on all the
; computer's cores at once. Up to 1.3.0 NSIS unpacked it with its own LZMA
; decoder, on one core, and in its "solid" mode it writes everything twice
; (to a temporary file, then to the folder); that took minutes.
;
;   7z a -t7z -mx=7 -m0=LZMA2:d=64m:c=128m -mmt=on payload\hamenagen.7z .\dist\win-unpacked\*
;   makensis /NOCD /DVERSION=1.3.1 /DPAYLOAD=payload\hamenagen.7z "/DSEVENZIP=C:\Program Files\7-Zip" ^
;            /DUNPACKED_KB=1300000 /DOUTFILE=dist\Hamenagen-1.3.1-Portable.exe /DICON=assets\icon.ico ^
;            "/DLABEL=גרסה ניידת" scripts\portable.nsi
;
; SEVENZIP is a 7-Zip of version 21 or later (7z.exe, 7z.dll and License.txt;
; 7-Zip is free software under the GNU LGPL, www.7-zip.org). Its license goes
; into the folder with the player.
;
; Silent (for tests): Hamenagen-1.3.1-Portable.exe /S /D=C:\some\folder
;
; Saved as UTF-8 with a byte-order mark, as NSIS needs for Hebrew.

Unicode true
RequestExecutionLevel user
ManifestDPIAware true

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef PBS_MARQUEE
  !define PBS_MARQUEE 0x08
!endif
!ifndef PBM_SETMARQUEE
  !define PBM_SETMARQUEE 0x40A
!endif

Name "המנגן ${VERSION}"
Caption "המנגן ${VERSION} — ${LABEL}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\Hamenagen"
BrandingText "המנגן — נגן מוזיקה קהילתי"

!define MUI_ICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_DIRECTORYPAGE_TEXT_TOP "המנגן ייפתח לתיקייה הזו ויפעל ממנה. התיקייה המוצעת היא תיקיית התוכנות של המשתמש שלך ב-Windows, ובהפעלה הראשונה יופיע קיצור דרך בשולחן העבודה. אפשר לבחור תיקייה אחרת, למשל בדיסק נייד. הספרייה, ההגדרות והשירים שאהבת נשמרים בתוך התיקייה (בתיקייה data). אם כבר יש בה גרסה קודמת, היא תתעדכן והנתונים יישארו."
!define MUI_FINISHPAGE_RUN "$INSTDIR\Hamenagen.exe"
!define MUI_FINISHPAGE_RUN_TEXT "להפעיל את המנגן"

!insertmacro MUI_PAGE_DIRECTORY
!define MUI_PAGE_HEADER_TEXT "פותח את המנגן"
!define MUI_PAGE_HEADER_SUBTEXT "המנגן נפתח לתיקייה שבחרת."
!define MUI_INSTFILESPAGE_FINISHHEADER_TEXT "המנגן מוכן"
!define MUI_INSTFILESPAGE_FINISHHEADER_SUBTEXT "כל הקבצים במקום."
!define MUI_INSTFILESPAGE_ABORTHEADER_TEXT "הפתיחה לא הושלמה"
!define MUI_INSTFILESPAGE_ABORTHEADER_SUBTEXT "שום דבר לא הופעל. אפשר לנסות שוב, גם לתיקייה אחרת."
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Hebrew"

Section "Hamenagen"
  !ifdef UNPACKED_KB
    AddSize ${UNPACKED_KB}
  !endif
  SetOutPath "$INSTDIR"
  ; A copy that is already here is updated in place: the program goes, the
  ; data folder stays. If the player is open, its program file is in use.
  IfFileExists "$INSTDIR\Hamenagen.exe" 0 fresh
    ClearErrors
    Delete "$INSTDIR\Hamenagen.exe"
    IfErrors 0 +3
      MessageBox MB_ICONEXCLAMATION|MB_OK "המנגן פתוח עכשיו. סגרו אותו ונסו שוב." /SD IDOK
      Abort
    RMDir /r "$INSTDIR\resources"
    RMDir /r "$INSTDIR\locales"
  fresh:

  ; 7-Zip and the program, into the temporary folder of this window.
  InitPluginsDir
  DetailPrint "מכין את הקבצים…"
  SetDetailsPrint none
  File "/oname=$PLUGINSDIR\7z.exe" "${SEVENZIP}\7z.exe"
  File "/oname=$PLUGINSDIR\7z.dll" "${SEVENZIP}\7z.dll"
  SetCompress off
  File "/oname=$PLUGINSDIR\hamenagen.7z" "${PAYLOAD}"
  SetCompress auto
  SetDetailsPrint both
  DetailPrint "פותח את המנגן לתיקייה…"

  ; 7-Zip has no steps to count, so the bar moves on its own meanwhile.
  FindWindow $1 "#32770" "" $HWNDPARENT
  ${If} $1 != 0
    GetDlgItem $1 $1 1004
    System::Call "user32::GetWindowLong(p r1, i -16) i .r2"
    IntOp $3 $2 | ${PBS_MARQUEE}
    System::Call "user32::SetWindowLong(p r1, i -16, i r3)"
    SendMessage $1 ${PBM_SETMARQUEE} 1 40
  ${EndIf}

  nsExec::Exec '"$PLUGINSDIR\7z.exe" x -y -aoa -bso0 -bse0 -bsp0 "-o$INSTDIR" "$PLUGINSDIR\hamenagen.7z"'
  Pop $0

  ${If} $1 != 0
    SendMessage $1 ${PBM_SETMARQUEE} 0 0
    System::Call "user32::SetWindowLong(p r1, i -16, i r2)"
  ${EndIf}
  Delete "$PLUGINSDIR\hamenagen.7z"

  ${If} $0 != 0
    DetailPrint "7-Zip: $0"
    MessageBox MB_ICONSTOP|MB_OK "לא הצלחתי לפתוח את המנגן לתיקייה הזו (קוד $0). אולי אין מספיק מקום בדיסק, או שאין הרשאה לכתוב בה. אפשר לנסות שוב, גם לתיקייה אחרת." /SD IDOK
    Abort
  ${EndIf}

  ; 7-Zip's license, beside the player that it opened.
  SetOutPath "$INSTDIR\resources\licenses"
  File "/oname=7-Zip.txt" "${SEVENZIP}\License.txt"
  SetOutPath "$INSTDIR"
  DetailPrint "המנגן מוכן."
SectionEnd
