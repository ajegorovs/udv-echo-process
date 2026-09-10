# DOP3000-3010 manual - text-only OCR corpus

This directory is a text-only, page-traceable reconstruction of the 130-page
*DOP3000-3010 User's Manual* (software 6.6, revision 1).

## What is included

- One Markdown file per chapter, plus front matter and the original index.
- Every source page is marked with `<!-- source-pdf-page: N -->`.
- Reconstructed figure captions and in-context explanations retain the
  information carried by figures without including image files.
- Display equations on 21 equation-bearing pages are visually checked and rewritten in LaTeX.
- Complex tables and file-layout descriptions are retained as fixed-width text when forcing them into pipe tables would lose column relationships.

## Extraction notes

The PDF already contains an untagged text layer, so the body transcription uses
that higher-fidelity source rather than re-recognizing every glyph with a
generic OCR engine. Private-use mathematical glyphs were normalized to Unicode,
and equations were checked against rendered pages. Original wording, spelling,
units, and technical notation are retained where possible.

The reconstructed captions and **In context** paragraphs are editorial additions. They are clearly labeled and should not be treated as verbatim manual text.

## Contents

- [Front matter](00-front-matter.md) - source PDF pages 1-6
- [1. Doppler ultrasound velocimetry](01-doppler-ultrasound-velocimetry.md) - source PDF pages 7-12
- [2. Architecture of the velocimeter](02-architecture-of-the-velocimeter.md) - source PDF pages 13-16
- [3. Installing the software](03-installing-the-software.md) - source PDF pages 17-20
- [4. Using the velocimeter](04-using-the-velocimeter.md) - source PDF pages 21-30
- [5. Computation and display of data profiles](05-computation-and-display-of-data-profiles.md) - source PDF pages 31-40
- [6. Applying real time filters](06-applying-real-time-filters.md) - source PDF pages 41-42
- [7. Measuring the sound speed](07-measuring-the-sound-speed.md) - source PDF pages 43-44
- [8. The parameters](08-the-parameters.md) - source PDF pages 45-56
- [9. Auto correction of the aliasing](09-auto-correction-of-aliasing.md) - source PDF pages 57-60
- [10. Storing and reading measures](10-storing-and-reading-measures.md) - source PDF pages 61-80
- [11. Using the multiplexer](11-using-the-multiplexer.md) - source PDF pages 81-84
- [12. 2D / 3D Ultrasonic Doppler Velocimetry](12-2d-3d-ultrasonic-doppler-velocimetry.md) - source PDF pages 85-92
- [13. UDV Simulation software](13-udv-simulation-software.md) - source PDF pages 93-98
- [14. Measurement sample volume](14-measurement-sample-volume.md) - source PDF pages 99-102
- [15. Spectral content of the Doppler echo](15-spectral-content-of-the-doppler-echo.md) - source PDF pages 103-104
- [16. Theoretical basis of the Doppler frequency estimation](16-theoretical-basis-of-doppler-frequency-estimation.md) - source PDF pages 105-106
- [17. Ultrasonic transducers](17-ultrasonic-transducers.md) - source PDF pages 107-108
- [18. Ultrasonic field](18-ultrasonic-field.md) - source PDF pages 109-114
- [19. References](19-references.md) - source PDF pages 115-116
- [20. Ultrasonic data](20-ultrasonic-data.md) - source PDF pages 117-118
- [21. DOP3000 technical specifications](21-dop3000-technical-specifications.md) - source PDF pages 119-122
- [22. DOP3010 technical specifications](22-dop3010-technical-specifications.md) - source PDF pages 123-126
- [Index](23-index.md) - source PDF pages 127-130
