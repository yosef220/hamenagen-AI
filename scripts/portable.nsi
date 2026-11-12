;
; The portable editions as one file: an EXE that opens itself, once, into a
; folder the listener picks, then runs the player from there. No installation
; and nothing in the registry: the folder holds the program and its data
; (data\), and can be carried to another computer.
;
;   makensis /NOCD /DVERSION=1.3.0 /DSRCDIR=dist\win-unpacked /DOUTFILE=dist\Hamenagen-1.3.0-Portable.exe ^
;            /DICON=assets\icon.ico /DLABEL="גרסה ניידת" scripts\portable.nsi
;
; Silent (for tests): Hamenagen-1.3.0-Portable.exe /S /D=C:\some\folder
;
; Saved as UTF-8 with a byte-order mark, as NSIS needs for Hebrew.

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
RequestExecutionLevel user
ManifestDPIAware true

!include "MUI2.nsh"

Name "המנגן ${VERSION}"
Caption "המנגן ${VERSION} — ${LABEL}"
OutFile "${OUTFILE}"
InstallDir "$DESKTOP\Hamenagen"
BrandingText "המנגן — נגן מוזיקה קהילתי"

!define MUI_ICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_DIRECTORYPAGE_TEXT_TOP "המנגן ייפתח לתיקייה הזו ויפעל ממנה, בלי התקנה. הספרייה, ההגדרות והשירים שאהבת נשמרים בתוכה (בתיקייה data), כך שאפשר להעביר אותה למחשב אחר. אם כבר יש כאן גרסה קודמת — היא תתעדכן, והנתונים יישארו."
!define MUI_FINISHPAGE_RUN "$INSTDIR\Hamenagen.exe"
!define MUI_FINISHPAGE_RUN_TEXT "להפעיל את המנגן"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Hebrew"

Section "Hamenagen"
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
  File /r "${SRCDIR}\*.*"
SectionEnd
