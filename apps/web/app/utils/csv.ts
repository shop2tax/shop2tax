/**
 * Shared CSV import option constants used by Bank + Marketplace wizards.
 */
export const CSV_DELIMITER_OPTIONS = [
  { value: ',', label: 'Komma (,)' },
  { value: ';', label: 'Semikolon (;)' },
  { value: '\t', label: 'Tab' },
]

export const CSV_ENCODING_OPTIONS = [
  { value: 'utf-8', label: 'UTF-8' },
  { value: 'utf-8-sig', label: 'UTF-8 (BOM)' },
  { value: 'iso-8859-1', label: 'ISO-8859-1' },
  { value: 'windows-1252', label: 'Windows-1252' },
]
